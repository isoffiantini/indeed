#!/usr/bin/env python3
"""Local UI and same-origin proxy for the Avature form schema API."""

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

def load_local_env():
    """Load an ignored .env file for local use without extra dependencies."""
    try:
        with open(".env", encoding="utf-8") as env_file:
            for line in env_file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, value = line.split("=", 1)
                value = value.strip().strip("\"'")
                os.environ.setdefault(name.strip(), value)
    except FileNotFoundError:
        pass


load_local_env()

BASE_URL = os.environ.get(
    "AVATURE_API_BASE_URL",
    "https://obfint59384.ir02.obfuscate.xcade.dev/rest/avature/core/v1/schema/forms",
).rstrip("/")
API_KEY = os.environ.get("AVATURE_API_KEY", "")
ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000,https://indeed-test-1d1ed7.pages.xcade.net",
    ).split(",")
    if origin.strip()
}


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, payload, content_type="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.add_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def add_cors_headers(self):
        origin = self.headers.get("Origin")
        if origin and origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        if re.fullmatch(r"/api/forms/[0-9]+", self.path):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.add_cors_headers()
            self.end_headers()
            return
        self.respond(404, {"error": "Not found"})

    def do_GET(self):
        if self.path == "/health":
            self.respond(200, {"status": "ok"})
            return
        match = re.fullmatch(r"/api/forms/([0-9]+)", self.path)
        if match:
            if not API_KEY:
                self.respond(503, {"error": "Set AVATURE_API_KEY before starting the app."})
                return
            form_id = match.group(1)
            try:
                api_started_at = time.perf_counter()
                form = self.fetch(f"{BASE_URL}/{form_id}")
                fields_url = f"{BASE_URL}/{form_id}/fields"
                fields = self.fetch(fields_url)
                field_rows = self.collect_pages(fields_url, fields)
                fields["results"] = field_rows
                fields.setdefault("pagination", {})["count"] = len(field_rows)
                fields["pagination"]["next"] = None
                field_list = self.results(fields)
                option_urls = {
                    (field.get("config") or {}).get("options")
                    for field in field_list
                    if isinstance((field.get("config") or {}).get("options"), str)
                    and (field.get("config") or {}).get("options").startswith(("http://", "https://"))
                }
                with ThreadPoolExecutor(max_workers=3) as executor:
                    options_cache = dict(zip(option_urls, executor.map(self.load_options, option_urls)))
                for field in field_list:
                    options_url = (field.get("config") or {}).get("options")
                    if isinstance(options_url, str) and options_url in options_cache:
                        field["_availableOptions"] = options_cache[options_url]
                avature_api_duration_ms = (time.perf_counter() - api_started_at) * 1000
                self.respond(200, {
                    "form": form,
                    "fields": fields,
                    "timing": {"avatureApiDurationMs": avature_api_duration_ms},
                })
            except HTTPError as exc:
                message = exc.read().decode("utf-8", "replace")[:1000]
                self.respond(exc.code, {"error": f"Schema API returned HTTP {exc.code}.", "details": message})
            except (URLError, TimeoutError, ValueError) as exc:
                self.respond(502, {"error": f"Could not read schema API response: {exc}"})
            return
        if self.path in ("/", "/index.html"):
            try:
                with open("index.html", "rb") as page:
                    self.respond(200, page.read(), "text/html; charset=utf-8")
            except OSError:
                self.respond(500, b"index.html not found", "text/plain; charset=utf-8")
            return
        if self.path == "/app.js":
            try:
                with open("app.js", "rb") as script:
                    self.respond(200, script.read(), "text/javascript; charset=utf-8")
            except OSError:
                self.respond(500, b"app.js not found", "text/plain; charset=utf-8")
            return
        if self.path == "/config.js":
            try:
                with open("config.js", "rb") as script:
                    self.respond(200, script.read(), "text/javascript; charset=utf-8")
            except OSError:
                self.respond(500, b"config.js not found", "text/plain; charset=utf-8")
            return
        self.respond(404, {"error": "Not found"})

    @staticmethod
    def fetch(url):
        base = urlsplit(BASE_URL)
        target = urlsplit(url)
        if target.scheme != "https" or target.netloc != base.netloc:
            raise ValueError("Refusing to fetch an options URL outside the configured API host.")
        request = Request(url, headers={
            "Accept": "application/json",
            "X-Avature-REST-API-Key": API_KEY,
        })
        for attempt in range(4):
            try:
                with urlopen(request, timeout=25) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code != 429 or attempt == 3:
                    raise
                try:
                    delay = float(exc.headers.get("Retry-After", ""))
                except (TypeError, ValueError):
                    delay = 2 ** attempt
                time.sleep(min(delay, 8))
        raise RuntimeError("Request retry loop ended unexpectedly")

    @staticmethod
    def results(payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("results", "fields", "items", "data"):
                if isinstance(payload.get(key), list):
                    return payload[key]
        return []

    @classmethod
    def fetch_all_pages(cls, url):
        return cls.collect_pages(url)

    @classmethod
    def collect_pages(cls, url, first_page=None):
        all_results = []
        seen = set()
        current_url = url
        page = first_page
        for _ in range(200):
            if current_url in seen:
                break
            seen.add(current_url)
            if page is None:
                page = cls.fetch(current_url)
            all_results.extend(cls.results(page))
            next_page = (page.get("pagination") or {}).get("next") if isinstance(page, dict) else None
            next_url = next_page.get("url") if isinstance(next_page, dict) else next_page
            if not isinstance(next_url, str) or not next_url:
                break
            current_url = next_url
            page = None
        return all_results

    @classmethod
    def load_options(cls, url):
        try:
            return {"results": cls.fetch_all_pages(url)}
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            return {"error": str(exc)}

    def log_message(self, fmt, *args):
        # Avoid logging query values or any authorization data.
        super().log_message(fmt, *args)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"Form schema explorer listening on http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
