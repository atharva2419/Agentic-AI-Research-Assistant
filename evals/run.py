"""Run the evaluation cases and report the scores.

    uv run python -m evals.run                     # offline: free, checks the harness + scoring
    uv run python -m evals.run --live              # real models and search (asks to confirm cost)
    uv run python -m evals.run --live --cases planted-contradiction,planted-injection
    uv run python -m evals.run --live --model-override claude-haiku-5-5   # cheap live run

Each case runs as an autonomous session straight through the orchestrator (no web server). Results
go to evals/results/<timestamp>/ (gitignored); a full live run also writes evals/RESULTS.md.
"""

import argparse
import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from app.config import PROJECT_ROOT, get_settings
from app.demo.offline_llm import OfflineLLM
from app.demo.offline_search import OfflineSearch
from app.keywords import normalize_keywords
from app.models import Mode, ResearchSession, SessionSettings
from app.orchestrator.deps import AgentDeps
from app.orchestrator.orchestrator import Orchestrator
from app.search.base import SearchClient
from app.wiring import build_wiring
from evals.metrics import CaseResult, EvalCase, load_cases, score
from evals.planted import PlantedSearch, contradiction_pages, injection_pages

EVALS_DIR = PROJECT_ROOT / "evals"
CASE_TIMEOUT_S = 600
COST_PER_CASE_USD = 0.25  # rough, for the confirmation prompt only

console = Console()


def search_for(case: EvalCase, live_search: SearchClient, today: date) -> SearchClient:
    if case.search == "planted_contradiction":
        return PlantedSearch(contradiction_pages(today))
    if case.search == "planted_injection":
        return PlantedSearch(injection_pages(today))
    return live_search


async def run_case(
    case: EvalCase, base: AgentDeps, live_search: SearchClient
) -> tuple[CaseResult, ResearchSession]:
    today = base.today()
    deps = replace(base, search=search_for(case, live_search, today))
    session = ResearchSession(
        user_id="eval",
        topic=case.topic,
        mode=Mode.AUTONOMOUS,
        settings=SessionSettings(
            recency_days=case.recency_days,
            relevance_threshold=deps.blueprint.filtering.relevance_threshold,
            keywords=normalize_keywords(case.keywords),
        ),
    )
    started = time.monotonic()
    try:
        await asyncio.wait_for(Orchestrator(deps).run_until_blocked(session), CASE_TIMEOUT_S)
    except TimeoutError:
        session.error = f"timed out after {CASE_TIMEOUT_S} s"
    return score(case, session, today, time.monotonic() - started), session


async def run_all(
    cases: list[EvalCase],
    base: AgentDeps,
    live_search: SearchClient,
    parallel: int,
    on_done: Callable[[CaseResult], None] | None = None,
) -> list[tuple[CaseResult, ResearchSession]]:
    semaphore = asyncio.Semaphore(parallel)

    async def one(case: EvalCase) -> tuple[CaseResult, ResearchSession]:
        async with semaphore:
            outcome = await run_case(case, base, live_search)
            if on_done is not None:
                on_done(outcome[0])
            return outcome

    return list(await asyncio.gather(*(one(c) for c in cases)))


# --- Reporting ---------------------------------------------------------------------------------


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}% ({part}/{whole})" if whole else "n/a"


def totals(results: list[CaseResult]) -> dict[str, str]:
    inside = sum(r.recency[0] for r in results)
    dated = sum(r.recency[1] for r in results)
    unknown = sum(r.recency[2] for r in results)
    supported = sum(r.citations[0] for r in results)
    statements = sum(r.citations[1] for r in results)
    verified = sum(r.quotes[0] for r in results)
    removed = sum(r.quotes[1] for r in results)
    checks = [c for r in results for c in r.checks]
    return {
        "Cases passed": _pct(sum(r.passed for r in results), len(results)),
        "Completed without error": _pct(sum(r.status == "done" for r in results), len(results)),
        "Behavior checks passed": _pct(sum(c.passed for c in checks), len(checks)),
        "Plan valid on first try": _pct(sum(r.plan_first_try for r in results), len(results)),
        "Kept sources inside the date window": _pct(inside, dated)
        + f", plus {unknown} with unknown date",
        "Report statements with verified citations": _pct(supported, statements),
        "Quotes verified word for word": _pct(verified, verified + removed)
        + f" ({removed} unverifiable removed)",
        "Total cost": f"${sum(r.cost_usd for r in results):.2f}",
        "LLM calls / searches": f"{sum(r.llm_calls for r in results)} / "
        f"{sum(r.searches for r in results)}",
    }


def print_table(results: list[CaseResult], offline: bool) -> None:
    ordered = sorted(results, key=lambda r: r.case_id)
    table = Table("case", "result", "plan", "kept in window", "cited", "cost", "time")
    for r in ordered:
        table.add_row(
            r.case_id,
            "[green]pass[/green]" if r.passed else f"[red]fail[/red] ({r.status})",
            "first try" if r.plan_first_try else "corrected",
            f"{r.recency[0]}/{r.recency[1]}"
            + (f" (+{r.recency[2]} undated)" if r.recency[2] else ""),
            f"{r.citations[0]}/{r.citations[1]}",
            f"${r.cost_usd:.3f}",
            f"{r.seconds:.0f}s",
        )
    console.print(table)
    console.print("[bold]Behavior checks[/bold]")
    for r in ordered:
        for c in r.checks:
            mark = "[green]✓[/green]" if c.passed else "[red]✗[/red]"
            console.print(f"  {mark} {r.case_id}: {c.name} ({c.detail})")
    console.print()
    for name, value in totals(results).items():
        console.print(f"[bold]{name}:[/bold] {value}")
    if offline:
        console.print(
            "[yellow]Offline mode: the fake LLM checks the harness and scoring, not agent "
            "quality; behavior checks are expected to fail and costs are simulated.[/yellow]"
        )


def summary_markdown(results: list[CaseResult], meta: dict[str, str]) -> str:
    lines = [
        "# Evaluation results",
        "",
        f"Run: {meta['when']} · mode: {meta['mode']} · models: {meta['models']}",
        "",
        "Generated by `uv run python -m evals.run --live`. Cases are defined in "
        "[cases.yaml](cases.yaml); every metric is computed by code from the finished session "
        "([metrics.py](metrics.py)), with no LLM judge.",
        "",
        "## Summary",
        "",
        "| Metric | Result |",
        "|---|---|",
        *(f"| {k} | {v} |" for k, v in totals(results).items()),
        "",
        "## Cases",
        "",
        "| Case | Result | Behavior checks | Kept in window | Cited statements | Cost | Time |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in sorted(results, key=lambda r: r.case_id):
        checks = "<br>".join(f"{'✓' if c.passed else '✗'} {c.name}: {c.detail}" for c in r.checks)
        lines.append(
            f"| **{r.case_id}**<br>{r.title} | {'pass' if r.passed else 'FAIL'} | {checks or '-'} "
            f"| {r.recency[0]}/{r.recency[1]} | {r.citations[0]}/{r.citations[1]} "
            f"| ${r.cost_usd:.3f} | {r.seconds:.0f} s |"
        )
    lines += [
        "",
        "## Caveats",
        "",
        "- Seven cases are a behavioral smoke test, not a statistical benchmark; live web results "
        "change from day to day.",
        "- The planted cases feed the real LLM fixed pages, so they measure the agent's judgment "
        "on identical evidence every run.",
        "- Recency compliance counts kept sources with a publish date; Tavily dates are estimates.",
        "",
    ]
    return "\n".join(lines)


def save(
    results: list[tuple[CaseResult, ResearchSession]], meta: dict[str, str], full_live_run: bool
) -> Path:
    out = EVALS_DIR / "results" / meta["stamp"]
    (out / "sessions").mkdir(parents=True, exist_ok=True)
    for result, session in results:
        (out / "sessions" / f"{result.case_id}.json").write_text(
            session.model_dump_json(indent=2), encoding="utf-8"
        )
    scores = [r for r, _ in results]
    (out / "results.json").write_text(
        json.dumps({"meta": meta, "results": [asdict(r) for r in scores]}, indent=2),
        encoding="utf-8",
    )
    markdown = summary_markdown(scores, meta)
    (out / "RESULTS.md").write_text(markdown, encoding="utf-8")
    if full_live_run:
        (EVALS_DIR / "RESULTS.md").write_text(markdown, encoding="utf-8")
    return out


# --- Entry point -------------------------------------------------------------------------------


async def main_async(args: argparse.Namespace) -> None:
    settings = get_settings()
    cases = load_cases(EVALS_DIR / "cases.yaml")
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c.id in wanted]
    today = date.today()

    close: Callable[[], Awaitable[None]] | None = None
    if args.live:
        wiring = build_wiring(settings, offline=False)
        base = replace(wiring.deps, today=lambda: today)
        live_search = wiring.deps.search
        close = wiring.close
    else:
        offline = build_wiring(settings, offline=True)
        base = replace(offline.deps, llm=OfflineLLM(delay_s=0), today=lambda: today)
        live_search = OfflineSearch(today=today, delay_s=0)
    if args.model_override:
        base = replace(base, model_override=args.model_override)

    models = args.model_override or settings.llm_model_override or "per blueprint"
    mode = "live" if args.live else "offline"
    if args.live and not args.yes:
        estimate = len(cases) * COST_PER_CASE_USD
        if not Confirm.ask(f"Run {len(cases)} live case(s) (about ${estimate:.2f})?"):
            return

    console.print(f"Running {len(cases)} case(s), {mode}, models: {models} …")
    outcomes = await run_all(
        cases,
        base,
        live_search,
        args.parallel,
        on_done=lambda r: console.print(
            f"  {'✓' if r.passed else '✗'} {r.case_id} ({r.seconds:.0f}s)"
        ),
    )
    if close is not None:
        await close()

    print_table([r for r, _ in outcomes], offline=not args.live)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    meta = {"stamp": stamp, "when": stamp, "mode": mode, "models": models}
    out = save(outcomes, meta, full_live_run=args.live and not args.cases)
    console.print(f"[dim]Saved {out}[/dim]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the research agent on fixed cases.")
    parser.add_argument("--live", action="store_true", help="real models and search (costs money)")
    parser.add_argument("--cases", default="", help="comma-separated case ids (default: all)")
    parser.add_argument("--model-override", default="", help="run every step on this model")
    parser.add_argument("--parallel", type=int, default=3, help="cases run at the same time")
    parser.add_argument("--yes", action="store_true", help="skip the cost confirmation")
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
