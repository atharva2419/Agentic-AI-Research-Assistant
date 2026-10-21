"""Shared builders for tests: deps wired with fakes, fixture search results, scripted LLM output."""

import re
from collections.abc import Callable
from datetime import date

from app.blueprint import load_blueprint
from app.config import PROJECT_ROOT
from app.llm.base import LLMClient, LLMRequest
from app.models import Mode, ResearchSession, SearchMode, SubTaskType
from app.orchestrator.deps import AgentDeps
from app.orchestrator.steps.clarify import ClarifyOutput
from app.orchestrator.steps.cross_check import CrossCheckOutput
from app.orchestrator.steps.gap_check import GapCheckOutput
from app.orchestrator.steps.plan import PlannedQuestion, PlannedSubTask, PlanOutput
from app.orchestrator.steps.questions import QuestionOutput
from app.orchestrator.steps.search import RelevanceJudgment, RelevanceOutput
from app.orchestrator.steps.summarize import QuoteOutput, SummaryOutput
from app.orchestrator.steps.synthesize import CitedClaim, SectionOutput, SynthesisOutput
from app.prompts import PromptLibrary
from app.search.base import SearchClient, SearchResult

TODAY = date(2026, 10, 20)
BLUEPRINT = load_blueprint(PROJECT_ROOT / "blueprints" / "research.yaml")
LONG_TEXT = "Newsrooms are adopting AI tools for transcription and research. " * 10


def make_deps(llm: LLMClient, search: SearchClient) -> AgentDeps:
    return AgentDeps(
        llm=llm,
        search=search,
        blueprint=BLUEPRINT,
        prompts=PromptLibrary(PROJECT_ROOT / "prompts"),
        today=lambda: TODAY,
    )


def make_session(mode: Mode = Mode.AUTONOMOUS) -> ResearchSession:
    return ResearchSession(user_id="u1", topic="AI in journalism", mode=mode)


def result(
    url: str,
    published: date | None = date(2026, 6, 1),
    content: str = LONG_TEXT,
    title: str = "",
) -> SearchResult:
    return SearchResult(
        url=url,
        title=title or url,
        snippet=content[:120],
        content=content,
        published_date=published,
    )


def search_task(
    task_id: str, query: str, rqs: list[str], mode: SearchMode = SearchMode.NEWS
) -> PlannedSubTask:
    return PlannedSubTask(
        id=task_id,
        type=SubTaskType.SEARCH,
        title=f"Search: {query}",
        query=query,
        search_mode=mode,
        focus=None,
        research_question_ids=rqs,
        depends_on=[],
    )


def summarize_task(task_id: str, depends_on: list[str]) -> PlannedSubTask:
    return PlannedSubTask(
        id=task_id,
        type=SubTaskType.SUMMARIZE,
        title="Summarize sources",
        query=None,
        search_mode=SearchMode.GENERAL,
        focus=None,
        research_question_ids=[],
        depends_on=depends_on,
    )


def cross_check_task(task_id: str, depends_on: list[str]) -> PlannedSubTask:
    return PlannedSubTask(
        id=task_id,
        type=SubTaskType.CROSS_CHECK,
        title="Compare claims",
        query=None,
        search_mode=SearchMode.GENERAL,
        focus="Do sources agree on job impact?",
        research_question_ids=[],
        depends_on=depends_on,
    )


def simple_plan() -> PlanOutput:
    """Two searches -> one summarize -> one cross-check."""
    return PlanOutput(
        objective="Understand how AI is changing journalism",
        research_questions=[
            PlannedQuestion(id="RQ1", text="How are newsrooms adopting AI?"),
            PlannedQuestion(id="RQ2", text="What is the impact on jobs?"),
        ],
        subtasks=[
            search_task("t1", "AI newsroom adoption", ["RQ1"]),
            search_task("t2", "AI journalism jobs", ["RQ2"]),
            summarize_task("t3", ["t1", "t2"]),
            cross_check_task("t4", ["t3"]),
        ],
        rationale="Adoption first, then impact; cross-check the job numbers.",
    )


SOURCE_ID = re.compile(r'<source id="(S\d+)"')


def source_ids_in(request: LLMRequest) -> list[str]:
    return SOURCE_ID.findall(request.messages[0].content)


def judge_all(
    score: float = 0.9, low: set[str] | None = None
) -> Callable[[LLMRequest], RelevanceOutput]:
    """A relevance response that scores every source in the prompt (low ones get 0.1)."""

    def respond(request: LLMRequest) -> RelevanceOutput:
        return RelevanceOutput(
            judgments=[
                RelevanceJudgment(
                    source_id=sid,
                    score=0.1 if low and sid in low else score,
                    reason=f"reason for {sid}",
                )
                for sid in source_ids_in(request)
            ]
        )

    return respond


def summary_for_prompt(request: LLMRequest) -> SummaryOutput:
    sid = source_ids_in(request)[0]
    return SummaryOutput(
        summary=f"Summary of {sid}.",
        key_takeaways=[f"Takeaway from {sid}"],
        claims=[f"Claim from {sid}"],
        quotes=[
            QuoteOutput(text="Newsrooms are adopting AI tools", context="opening line"),
            QuoteOutput(text="This sentence is not in the source", context="made up"),
        ],
    )


def synthesis_citing(source_ids: list[str]) -> SynthesisOutput:
    return SynthesisOutput(
        title="AI in journalism",
        executive_summary="AI is spreading through newsrooms.",
        key_takeaways=[CitedClaim(text="Adoption is growing.", source_ids=source_ids)],
        sections=[
            SectionOutput(
                heading="Adoption",
                statements=[CitedClaim(text="Most newsrooms use AI.", source_ids=source_ids[:1])],
            )
        ],
        open_questions=["Long-term job effects"],
        limitations=["Few sources"],
        suggested_next_topics=["AI and local news"],
    )


NO_CONTRADICTIONS = CrossCheckOutput(contradictions=[])
CLEAR_TOPIC = ClarifyOutput(is_ambiguous=False, reasoning="Specific enough.", questions=[])
SUFFICIENT = GapCheckOutput(
    verdict="sufficient",
    reasoning="Both questions covered.",
    gaps=[],
    new_searches=[],
    question=None,
)


def question(text: str = "Which region?", assume: str = "Global coverage") -> QuestionOutput:
    return QuestionOutput(
        question=text,
        why_it_matters="Changes which sources matter.",
        suggested_options=["US", "EU", "Global"],
        assumption_if_skipped=assume,
    )
