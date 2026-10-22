"""Command-line driver: run a research session in the terminal.

    uv run python -m app.cli "impact of AI on journalism"
    uv run python -m app.cli "EV battery recycling" --mode autonomous --recency-days 180

Needs ANTHROPIC_API_KEY and TAVILY_API_KEY in .env (or --offline for the free demo mode). Set
LLM_MODEL_OVERRIDE=claude-haiku-5-5 for a cheap smoke run. The session JSON and the report are
saved under data/.
"""

import argparse
import asyncio
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Confirm, Prompt
from rich.table import Table

from app.config import get_settings
from app.exports import export_session
from app.models import (
    ActionLogEntry,
    Actor,
    AnswerQuestions,
    ApprovePlan,
    Mode,
    ResearchSession,
    SessionSettings,
    Status,
)
from app.orchestrator.orchestrator import Orchestrator
from app.report_render import report_to_markdown
from app.wiring import MissingKeys, build_wiring

console = Console()
ACTOR_STYLE = {Actor.AGENT: "cyan", Actor.USER: "magenta", Actor.SYSTEM: "dim"}


class LogPrinter:
    """Prints action-log entries that appeared since the last call."""

    def __init__(self) -> None:
        self.printed = 0

    def __call__(self, session: ResearchSession) -> None:
        for entry in session.log[self.printed :]:
            print_entry(entry)
        self.printed = len(session.log)


def print_entry(entry: ActionLogEntry) -> None:
    style = ACTOR_STYLE[entry.actor]
    line = f"[{style}]{entry.timestamp:%H:%M:%S} {entry.actor:<6} {entry.step:<11}[/{style}] "
    line += entry.action
    if entry.decision:
        line += f" [bold]→ {entry.decision}[/bold]"
    console.print(line, highlight=False)
    if entry.reason and entry.step not in {"state"}:
        console.print(f"{'':>27}[dim]{entry.reason[:300]}[/dim]", highlight=False)


def print_plan(session: ResearchSession) -> None:
    assert session.plan is not None
    plan = session.plan
    console.rule(f"Research plan v{plan.version}")
    console.print(f"[bold]Objective:[/bold] {plan.objective}")
    for q in plan.research_questions:
        console.print(f"  {q.id}: {q.text}")
    table = Table("id", "type", "title / query", "depends on")
    for t in plan.subtasks:
        detail = f"{t.title}\n[dim]{t.query or t.focus or ''}[/dim]"
        table.add_row(t.id, t.type.value, detail, ", ".join(t.depends_on))
    console.print(table)
    console.print(f"[dim]Why: {plan.rationale}[/dim]")


def ask_questions(session: ResearchSession) -> AnswerQuestions:
    console.rule("The agent has questions (press Enter to skip one)")
    answers: dict[str, str | None] = {}
    for q in session.pending_questions():
        console.print(f"\n[bold]{q.id}. {q.question}[/bold]")
        console.print(f"[dim]Why: {q.why_it_matters}[/dim]")
        for i, option in enumerate(q.suggested_options, start=1):
            console.print(f"  {i}. {option}")
        console.print(f"[dim]If skipped: {q.assumption_if_skipped}[/dim]")
        reply = Prompt.ask("Your answer (number, text, or Enter to skip)", default="").strip()
        if reply.isdigit() and 1 <= int(reply) <= len(q.suggested_options):
            reply = q.suggested_options[int(reply) - 1]
        answers[q.id] = reply or None
    return AnswerQuestions(answers=answers)


def save_outputs(session: ResearchSession) -> None:
    session_path, report_path = export_session(session, get_settings().data_dir)
    console.print(f"[dim]Saved {session_path} and {report_path}[/dim]")


async def run(topic: str, mode: Mode, recency_days: int, offline: bool = False) -> None:
    settings = get_settings()
    try:
        wiring = build_wiring(settings, offline=offline or None)
    except MissingKeys as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    deps = wiring.deps
    if wiring.offline:
        console.print("[yellow]Offline demo mode: generated sources and answers, no cost.[/yellow]")
    orchestrator = Orchestrator(deps)
    session = ResearchSession(
        user_id="cli",
        topic=topic,
        mode=mode,
        settings=SessionSettings(
            recency_days=recency_days,
            relevance_threshold=deps.blueprint.filtering.relevance_threshold,
        ),
    )
    if settings.llm_model_override:
        console.print(f"[yellow]All steps use {settings.llm_model_override} (override).[/yellow]")
    printer = LogPrinter()
    try:
        while True:
            await orchestrator.run_until_blocked(session, on_step=printer)
            if session.status == Status.AWAITING_PLAN_APPROVAL:
                print_plan(session)
                if not Confirm.ask("Approve this plan?", default=True):
                    console.print("Stopped. (Plan editing arrives with the web UI.)")
                    break
                await orchestrator.handle_command(session, ApprovePlan())
                printer(session)
            elif session.status == Status.AWAITING_ANSWERS:
                await orchestrator.handle_command(session, ask_questions(session))
                printer(session)
            else:
                break
    finally:
        await wiring.close()
        save_outputs(session)

    if session.status == Status.DONE:
        console.rule("Report")
        console.print(Markdown(report_to_markdown(session)))
    elif session.status == Status.FAILED:
        console.print(f"[red]Session failed: {session.error}[/red]")
    b = session.budget
    console.print(
        f"[dim]{b.searches} searches, {b.llm_calls} LLM calls, "
        f"{b.input_tokens:,} in / {b.output_tokens:,} out tokens, ~${b.cost_usd:.3f}[/dim]"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an AI research session in the terminal.")
    parser.add_argument("topic", help="what to research")
    parser.add_argument("--mode", choices=[m.value for m in Mode], default=Mode.SUPERVISED.value)
    parser.add_argument("--recency-days", type=int, default=365)
    parser.add_argument("--offline", action="store_true", help="free demo mode, no API keys")
    args = parser.parse_args()
    asyncio.run(run(args.topic, Mode(args.mode), args.recency_days, args.offline))


if __name__ == "__main__":
    main()
