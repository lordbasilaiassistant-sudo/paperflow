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

## Option 1 — Hugging Face Spaces (free, no card, stays warm)

The best default: nothing to pay, nothing to install, and the Space doesn't spin
down between visitors the way a free container tier usually does.

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

## Option 2 — Cloudflare Containers (what we run on)

If you already pay for **Workers Paid** ($5/mo), Containers is included in that
plan rather than billed on top — so this costs nothing extra on an account you
already have. It runs the same `Dockerfile`.

```bash
npm i -g wrangler && wrangler login
wrangler secret put LLM_API_KEY     # paste when prompted; never commit it
wrangler deploy
```

`wrangler.toml` needs the container and a Durable Object to route to it:

```toml
name = "paperflow"
main = "src/index.ts"
compatibility_date = "2026-01-01"

[[containers]]
class_name = "PaperflowContainer"
image = "./Dockerfile"
max_instances = 1

[[durable_objects.bindings]]
name = "CONTAINER"
class_name = "PaperflowContainer"
```

Two things to know before you pick this:
- **Billing is per running second**, and it starts when a request wakes the
  container and stops when it sleeps. Bursty demo traffic fits the included
  allowance comfortably; a container you deliberately keep always-on does not.
- The container filesystem is ephemeral. For a ledger that survives restarts,
  put the SQLite file on a **Durable Object** or **R2** rather than `DATA_DIR`.

## Option 3 — any other Docker host

The contract is the same everywhere: build the `Dockerfile`, inject
`LLM_API_KEY`, route HTTP to the container's `$PORT`, and mount a volume at
`/app/data` if you want the ledger to persist. Anything that runs a container
works — pick whichever one you already have an account with.

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
