# Indeed form schema API

Python proxy for the Form schema explorer. It calls Avature, fetches paginated fields and option lists, and keeps the Avature API key on the server.

## Deploy on Render

This repository includes a Render Blueprint in `render.yaml`. In Render, choose **New → Blueprint**, connect this GitHub repository, and select the repository root (leave Root Directory blank). Render will create a Python web service with `/health` as its health check.

When prompted, provide `AVATURE_API_KEY` as a secret. Do not add the key to GitHub or `render.yaml`. The Blueprint sets `HOST=0.0.0.0` and allows requests from the Pages UI at `https://indeed-test-1d1ed7.pages.xcade.net`. Render supplies the listening `PORT`.

After the first deploy, copy the service's HTTPS URL. In the Pages project on GitLab, open **Settings → CI/CD → Variables**, set `API_BASE_URL` to the Render service origin (for example, `https://indeed-schema-api.onrender.com`, without a trailing slash), and run the Pages pipeline again.

The Blueprint uses Render's free plan for this test service. Free web services can spin down when idle, so the first request after inactivity may take longer.

## Local use

Copy `.env.example` to `.env`, set `AVATURE_API_KEY` in `.env`, then run:

```bash
python3 server.py
```

The local server listens on `http://127.0.0.1:8000` by default.
