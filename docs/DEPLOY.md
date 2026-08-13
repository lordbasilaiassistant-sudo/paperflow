# Deploying paperflow as a live app

paperflow is a FastAPI app: the frontend (`app/static/`) talks to a Python
backend that runs the LLM extraction, Tesseract OCR, and a SQLite database.
That means it can't run on static hosting like GitHub Pages — it needs a host
that runs a container. This guide covers the options, cheapest-and-easiest
first. All of them use the [`Dockerfile`](../Dockerfile) at the repo root, which
already installs Tesseract, so the same image works everywhere.

## What you need first

- An **OpenAI-compatible API key** (the `LLM_API_KEY`). The defaults target
  [z.ai's free GLM flash tier](https://z.ai); any OpenAI-compatible endpoint
  works — set `LLM_BASE_URL` / `LLM_MODEL` to match.
- Nothing else. Tesseract, the Python deps, and the DB are all handled by the
  container.

### Environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `LLM_API_KEY` | **yes** | — | Your key. Set it as a secret in the host, never in the repo. |
| `LLM_BASE_URL` | no | `https://api.z.ai/api/paas/v4` | Any OpenAI-compatible endpoint. |
| `LLM_MODEL` | no | `glm-4.5-flash` | The extraction model. |
| `LLM_EXTRA_BODY` | no | `{"thinking":{"type":"disabled"}}` | Disables GLM reasoning tokens; harmless elsewhere. |
| `ROUTE_THRESHOLD` | no | `0.80` | Auto-accept confidence bar; lower = more automation, more false accepts. |
| `DATA_DIR` | no | `/app/data` (in Docker) | Where uploads, previews, and the SQLite db live. |
| `PORT` | no | `8000` | Most hosts inject this automatically. |

### A note on storage (read this once)

Uploads, page-preview images, and the ledger database all live under
`DATA_DIR`. On a plain container **that directory is ephemeral** — it's wiped
whenever the container is recreated (every redeploy, and on some free tiers
after an idle spin-down). That's fine for a demo where people try their own
invoices and don't need them to persist. If you want the ledger to survive
restarts, mount a **persistent volume** at `DATA_DIR` (noted per host below).

---

## Option 1 — Render (one-click Blueprint)

The repo ships a [`render.yaml`](../render.yaml) Blueprint.

1. Push this repo to GitHub (done, if you're reading this there).
2. In the [Render dashboard](https://dashboard.render.com/): **New → Blueprint**,
   select this repo. Render reads `render.yaml` and creates the web service.
3. When prompted, paste your `LLM_API_KEY`. Deploy.
4. Open the URL Render gives you and drag an invoice onto the page.

Notes:
- The **free** web service spins down after ~15 min idle and cold-starts on the
  next request (first hit takes a few seconds).
- Free instances have **no persistent disk**, so the ledger resets on each
  redeploy. To persist it, upgrade the instance and add a Disk mounted at
  `/app/data` in the Render dashboard.

## Option 2 — Hugging Face Spaces (free, stays warm)

Good if you want an always-available public demo at no cost.

1. Create a new **Space** → SDK: **Docker** → blank template.
2. Add these files to the Space repo: the whole `app/` folder, `requirements.txt`,
   and `Dockerfile`. (Easiest: push this repo's contents to the Space.)
3. In the Space's `README.md` front-matter, expose the port:
   ```yaml
   ---
   title: paperflow
   sdk: docker
   app_port: 8000
   ---
   ```
4. In **Settings → Variables and secrets**, add `LLM_API_KEY` as a **secret**.
5. The Space builds and serves the app. Spaces storage is ephemeral unless you
   attach persistent storage in Settings.

## Option 3 — Fly.io (persistent volume, global)

```bash
# One-time: install flyctl and log in (https://fly.io/docs/hands-on/install-flyctl/)
fly launch --dockerfile Dockerfile --no-deploy   # generates fly.toml; accept defaults
fly volumes create paperflow_data --size 1       # 1 GB persistent disk for the ledger
```

Then, in the generated `fly.toml`, point the app at the volume and internal port:

```toml
[http_service]
  internal_port = 8000

[[mounts]]
  source = "paperflow_data"
  destination = "/app/data"
```

Finally set the key and deploy:

```bash
fly secrets set LLM_API_KEY=sk-your-key
fly deploy
```

## Option 4 — Railway / any Docker host

Railway auto-detects the `Dockerfile`. Create a project from this repo, add
`LLM_API_KEY` under **Variables**, and deploy. Add a Volume mounted at
`/app/data` if you want persistence.

Any host that runs a container works the same way — the contract is: build the
`Dockerfile`, inject `LLM_API_KEY`, route HTTP to the container's `$PORT`.

---

## Run the container yourself (local Docker)

To confirm the exact image a host will run:

```bash
docker build -t paperflow .
docker run --rm -p 8000:8000 \
  -e LLM_API_KEY=sk-your-key \
  -v paperflow_data:/app/data \
  paperflow
# open http://127.0.0.1:8000
```

The `-v paperflow_data:/app/data` gives you a persistent named volume so the
ledger survives `docker run` restarts.

## Security / cost reality check

This app has **no authentication** (see the Non-goals in the README) — anyone
with the URL can upload documents and read the ledger. For a public demo that's
usually fine; if you're processing anything real, put it behind the host's
access controls or an auth proxy first. Cost tracks your LLM endpoint: on the
free GLM tier it's $0; on a paid endpoint it's roughly one extraction call per
document (see the README's Cost section).
