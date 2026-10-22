# Agentic AI Personal Research Assistant

An AI research assistant that plans research on a topic, searches for recent and relevant sources,
filters and summarizes them, finds contradictions, adapts its plan, and writes a cited report — with a
live action log and human overrides at every step.

> Work in progress. Full setup, demo script and architecture overview coming soon.
> Design: [docs/design.md](docs/design.md).

## Quick start

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
uv sync                          # Python dependencies
cp .env.example .env             # add ANTHROPIC_API_KEY and TAVILY_API_KEY
cd ui && npm install && cd ..    # UI dependencies
```

**Web UI (development):** run the API and the UI dev server in two terminals.

```bash
uv run uvicorn app.api.main:app --reload --port 8000
cd ui && npm run dev             # open http://localhost:5173
```

**Web UI (single server):** `cd ui && npm run build`, then run only the uvicorn command and open
http://localhost:8000. API docs are at http://localhost:8000/docs.

**Offline demo mode (no keys, no cost):** set `OFFLINE_MODE=true` in `.env` (or the environment).
The agent then uses a built-in fake AI and fake search that work for any topic.

**Data:** sessions and long-term memory are stored in `data/research.db` (SQLite). The schema is
managed by Alembic migrations, applied automatically on startup (or by hand:
`uv run alembic upgrade head`). Finished reports are also written to `data/reports/`.

**Terminal:** `uv run python -m app.cli "impact of AI on journalism"` (add `--offline` for demo mode).

## Tests

```bash
uv run pytest                    # backend, runs without API keys
cd ui && npm test                # UI
```
