# Agentic AI Personal Research Assistant

An AI research assistant that plans research on a topic, searches for recent and relevant sources,
filters and summarizes them, finds contradictions, adapts its plan, and writes a cited report — with a
live action log and human overrides at every step.

> Work in progress. Full setup, demo script and architecture overview coming soon.
> Design: [docs/design.md](docs/design.md).

## Quick start (development)

```bash
uv sync                         # create .venv and install dependencies
cp .env.example .env            # then add your API keys
uv run pytest                   # tests run without API keys
```
