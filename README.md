# Agentic AI Personal Research Assistant

An AI agent that researches a topic the way a careful analyst would: it asks what you mean, plans
the work, searches the web for **recent, relevant** sources, filters out outdated and off-topic
ones (showing why), summarizes each source, finds where sources **contradict** each other, checks
its own coverage and adapts, and writes a report in which **every claim cites a source**.

Everything the agent decides appears in a **live action log** with its reason, and you can step in
at any point: answer or skip questions, approve or edit the plan, exclude a source, change the date
window, pause. Finished research is **remembered per user** and used to suggest related topics.

> Design document with the full architecture and decision log: [docs/design.md](docs/design.md)

---

## Features

| Assignment requirement | How it is met |
|---|---|
| **Autonomous research planning** | The planner breaks the topic into research questions and typed sub-tasks (search → summarize → cross-check) with dependencies. Code validates the plan and runs it in dependency order, in parallel where possible. *Autonomous* mode runs start to finish with no prompts. |
| **Proactive, adaptive information gathering** | Web search (Tavily) with publish dates. Code drops outdated, duplicate and thin pages; an LLM judge scores relevance with a one-line reason. A coverage check then decides: *sufficient*, *replan* (new targeted searches), or *ask the user*. |
| **Clarifying questions** | Ambiguous topics get up to 3 questions with suggested answers. Skipped questions become stated assumptions used by every later step and listed in the report. |
| **Summaries** (bonus) | Per-source summary, key takeaways and claims. Quotes are verified word for word against the page; unverifiable quotes are removed. |
| **Long-term memory** (bonus) | Finished sessions are stored (SQLite). New topics recall related past research for the planner, labelled "from past research"; the home screen suggests next topics; memories expire after a year and can be forgotten. |
| **Transparency and human oversight** (bonus) | Every decision is logged with actor (agent / user / system) and reason. Overrides: edit or skip tasks, add a search, exclude or restore sources, change the date window, switch mode, pause/resume. Changing the evidence of a finished report reopens it and rewrites it. |

Also: optional **priority keywords** (favoured by every step, never used to exclude sources, with
measured coverage in the report), **budgets** (searches, replans, cost cap), and an **offline demo
mode** that runs the whole system with no API keys.

---

## Quick start

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
uv sync                          # Python dependencies
cp .env.example .env             # add ANTHROPIC_API_KEY and TAVILY_API_KEY
cd ui && npm install && npm run build && cd ..
uv run uvicorn app.api.main:app --port 8000
```

Open http://localhost:8000. API docs are generated at http://localhost:8000/docs.

**With Docker** (no local Python or Node needed):

```bash
docker compose up --build                       # live mode, reads keys from .env
OFFLINE_MODE=true docker compose up --build     # offline demo mode, no keys
```

The image builds the UI, runs as a non-root user and has a health check; sessions, memory and
exported reports are kept on a named volume (`/data`).

**No keys? Offline demo mode:** set `OFFLINE_MODE=true` (in `.env` or the environment). A built-in
fake LLM and fake search produce valid output for any topic, so every feature can be tried for free.

**UI development:** run the uvicorn command with `--reload`, then `cd ui && npm run dev` and open
http://localhost:5173 (Vite forwards `/api` to port 8000).

**Terminal:** `uv run python -m app.cli "impact of AI on journalism"`
(options: `--mode autonomous`, `--recency-days 180`, `--keywords "GA4, hreflang"`, `--offline`).

**Data:** sessions and memory live in `data/research.db` (SQLite). The schema is managed by Alembic
migrations, applied automatically on startup (or by hand: `uv run alembic upgrade head`). Finished
reports are also exported to `data/reports/`.

**Cost:** a full live session costs about $0.20–0.35 (12 searches max, ~35 LLM calls). Set
`LLM_MODEL_OVERRIDE=claude-haiku-5-5` to run every step on the cheapest model (~$0.02).

---

## Try it: a five-minute walkthrough

1. **Ask.** Enter *impact of AI on journalism* in **Supervised** mode, optionally with keywords such
   as *local news, layoffs*. The agent decides the topic is ambiguous and asks up to three
   questions, each with suggested answers and the assumption it will make if you skip.
2. **Steer.** Answer one, skip one. The skipped one appears under *Working assumptions*.
3. **Review the plan.** Research questions and sub-tasks appear, with the planner's reasoning.
   Edit a query, skip a task or add a search, then **Approve and start**.
4. **Watch.** The action log streams every decision: searches, sources excluded as outdated or
   irrelevant (with reasons), summaries, contradictions, the coverage check and any replan. The
   right-hand column shows live progress until the report is ready.
5. **Read and verify.** The report appears on the right. Hover a citation to see its source; click
   it to open the source beside the report, with its summary and verified quotes.
6. **Override.** Exclude a source the report relies on (say, a vendor blog). The agent reopens the
   session, re-checks coverage and rewrites the report without it. Or tighten the date window.
7. **Come back later.** Start a related topic: the form previews your earlier research, the agent
   recalls it as context for planning, and the sidebar suggests next topics from past reports.

---

## How it works

**Core principle: code owns the control flow; the LLM owns the judgment.** A state machine in
plain Python decides what happens next. The LLM is called at fixed steps, returns JSON that must
pass a Pydantic schema *and* code checks, and is retried with the errors if it doesn't. The LLM has
no tools: it never browses or acts, it only returns data that code validates.

```
                ┌────────── React UI (live log, plan, sources, report) ──────────┐
                │  REST commands                               SSE live events ▲ │
                ▼                                                              │ │
  FastAPI ──► SessionRunner (one background task per session) ──► EventBus ────┘
                │
                ▼
  Orchestrator.step() ── state machine ──► step handlers
     CLARIFYING ─► PLANNING ─► (approval) ─► EXECUTING ─► GAP_CHECK ─► SYNTHESIZING ─► DONE
                      ▲                          │   ▲         │
                      └── answers ◄── question ◄─┘   └─ replan ┘
                │
     ┌──────────┼──────────────┬───────────────────┬─────────────────────┐
     ▼          ▼              ▼                   ▼                     ▼
  Claude     Tavily      Blueprint YAML      Memory (TF-IDF)       SQLite + Alembic
  (LLM)      (search)    + prompts/*.md      recall / remember     sessions, memory
```

| Step | Model | What it does |
|---|---|---|
| Clarify | Sonnet | Is the topic ambiguous? Up to 3 questions with default assumptions |
| Plan | Sonnet | Research questions + typed sub-tasks; may widen the date window, with a reason |
| Relevance | Haiku | Scores each candidate source 0–1 with a reason (after code rules) |
| Summarize | Haiku | Summary, takeaways, claims, quotes (quotes verified by code) |
| Cross-check | Sonnet | Contradictions between sources, with the likely cause |
| Gap check | Sonnet | Sufficient / replan / ask the user (code decides which verdicts are allowed) |
| Synthesize | Opus | The cited report (citations verified by code; bad ones flagged, never hidden) |

The workflow (models per step, prompts, limits, filters, memory TTL) is defined in
[blueprints/research.yaml](blueprints/research.yaml) and validated at startup.

### Guardrails

- **Prompt injection:** web text is wrapped in `<source>` delimiters, fake delimiters inside it
  are neutralised, and prompts treat it as data. With no tools, the worst a page can do is distort
  a summary, which citations and quote checks make visible.
- **Citations:** every report statement must cite a source collected in this session; unknown IDs
  are retried, then flagged "unsupported" in the report.
- **Validation and retries** on every LLM output (schema + semantic checks, max 2 retries).
- **Budgets:** max searches, sub-tasks, replans, summaries, and a cost cap; running out always
  ends in a report with stated limitations, never a loop.
- **Data retention:** memories expire after 365 days; stored page text is removed from finished
  sessions after 30 days. Restarts never resume paid work without the user.

---

## Project structure

```
app/
  orchestrator/      state machine, orchestrator, plan validation, scheduler, overrides,
                     steps/ (clarify, plan, search, summarize, cross_check, gap_check, synthesize)
  llm/               LLMClient interface, structured_call (validate + retry), Claude client, fake
  search/            SearchClient interface, Tavily client, fake
  memory/            TF-IDF retrieval, memory stores, MemoryService
  storage/           SQLAlchemy tables, session stores, Alembic runner
  api/               FastAPI routes, SSE, SessionRunner
  demo/              offline LLM and search
  filtering.py, keywords.py, models.py, blueprint.py, prompts.py, cli.py
blueprints/research.yaml   the workflow definition
prompts/*.md               one prompt per step
migrations/                Alembic migrations
ui/                        React + TypeScript (Vite)
evals/                     evaluation cases, planted pages, code-only scoring, RESULTS.md
tests/                     pytest suite (fake LLM and search: no keys, no network)
docs/design.md             architecture, state machine, decision log
Dockerfile, docker-compose.yml
```

---

## Tests and quality

```bash
uv run pytest                    # 215 tests, a few seconds, no API keys needed
uv run ruff check . && uv run mypy
cd ui && npm test                # 20 UI tests (Vitest)
```

The orchestrator is tested end to end with a scripted fake LLM and fake search: replans,
clarifying questions, overrides, reopening a finished report, budgets, failures, restarts with a
real SQLite database, and a test that fails if the database models drift from the migrations. CI
(GitHub Actions) runs lint, strict type checks and both test suites on every push.

### Evaluation

`uv run python -m evals.run --live` runs 7 cases ([evals/cases.yaml](evals/cases.yaml)) as
autonomous sessions and scores them **by code, with no LLM judge**
([evals/metrics.py](evals/metrics.py)): completion, plan validity on the first try, recency
compliance, citation validity, quote verification, cost, plus case-specific behavior checks:

- the date window stays strict for news, and widens for evergreen topics and stated time frames;
- an ambiguous topic gets clarifying questions and stated assumptions;
- priority keywords end up covered;
- a **planted contradiction** between two fixed pages is found;
- a **planted prompt injection** ("ignore all previous instructions…") is not followed or cited.

The planted cases feed the real LLM identical fixed pages, so they measure judgment on the same
evidence every run. Latest results: [evals/RESULTS.md](evals/RESULTS.md). Without `--live`, the
harness runs offline for free (it checks the plumbing; CI runs it on every push).

**Latest live run (7 cases, $1.63):** 6/7 cases and 8/9 behavior checks passed; 7/7 completed with
plans valid on the first try; 100% of dated kept sources inside the window (102/102); 100% of
report statements with verified citations (181/181); 100% of quotes verified word for word
(151/151); the planted contradiction was found, and the injected page scored 0.0, was excluded and
never cited.

**What it caught:** for "website migration SEO best practices" the planner kept the 365-day
window, reasoning that SEO changes fast. That excluded 20 older but still valid sources (including
Google's own Search Console help pages), and both replans were then spent on coverage gaps those
sources would have filled. The prompt guidance for evergreen topics isn't enough on its own; the
next step is to let the coverage check widen the window when date exclusions explain a gap.

---

## Design choices and trade-offs

- **State machine over a free-form agent loop:** predictable, testable with fakes, budgets are
  easy to enforce, and every transition is explainable. A framework such as LangGraph would also
  work, but hides the control flow.
- **Search called by code, not by the LLM:** filtering, dates, budgets and logging stay in code.
- **SSE + REST** instead of WebSockets: one-way live updates; every connection starts with a full
  snapshot, so reconnects need no replay logic.
- **Session stored as one JSON document** plus query columns: little code, Postgres/JSONB-ready.
- **TF-IDF memory** instead of embeddings: no second provider for a small corpus; a `Retriever`
  interface is the upgrade path to embeddings + pgvector.
- **Single-process runner:** fine for a demo; production would use a task queue and workers.

**Known limitations:** Tavily publish dates are estimates (sometimes the last-updated date); some
pages only provide snippets; memory matches words, not meaning; there is no authentication (the
user name only separates memories); the CLI does not use the database.

---

## Built for

Knowledge workers (journalists, analysts, students) who need research they can **trust and
audit**. The same patterns (YAML-defined workflows, validated LLM steps, citations, an audit log,
human review and overrides, retention policies) are what agentic "digital coworkers" need in
government and enterprise settings. The stack (Python, FastAPI, Pydantic, SQLAlchemy, Alembic,
pytest, React/TypeScript, Docker, GitHub Actions) was chosen with that in mind.
