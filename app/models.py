"""Domain models: the research session and everything inside it.

These are the agent's state. LLM output schemas are separate and smaller (they live next to each
step), so the LLM never fills in IDs, statuses or timestamps — code does.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid4().hex[:12]


class DomainModel(BaseModel):
    """Base for all domain models: unknown fields are an error, not silently ignored."""

    model_config = ConfigDict(extra="forbid")


# --- Enums -------------------------------------------------------------------------------------


class Status(StrEnum):
    CREATED = "created"
    CLARIFYING = "clarifying"
    AWAITING_ANSWERS = "awaiting_answers"
    PLANNING = "planning"
    AWAITING_PLAN_APPROVAL = "awaiting_plan_approval"
    EXECUTING = "executing"
    GAP_CHECK = "gap_check"
    SYNTHESIZING = "synthesizing"
    DONE = "done"
    FAILED = "failed"


class Mode(StrEnum):
    AUTONOMOUS = "autonomous"  # runs start to finish without waiting for the user
    SUPERVISED = "supervised"  # waits for plan approval


class SubTaskType(StrEnum):
    SEARCH = "search"
    SUMMARIZE = "summarize"
    CROSS_CHECK = "cross_check"


class SubTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


class Origin(StrEnum):
    PLANNER = "planner"
    REPLAN = "replan"
    USER = "user"


class SearchMode(StrEnum):
    NEWS = "news"
    GENERAL = "general"


class SourceStatus(StrEnum):
    KEPT = "kept"
    EXCLUDED = "excluded"


class ExclusionStage(StrEnum):
    RULE = "rule"  # code filter: duplicate, outdated, too short, domain cap
    RELEVANCE = "relevance"  # LLM relevance judge
    USER = "user"  # human override


class Actor(StrEnum):
    AGENT = "agent"
    USER = "user"
    SYSTEM = "system"


# --- Clarification and planning ----------------------------------------------------------------


class SessionSettings(DomainModel):
    recency_days: int = Field(default=365, ge=1, le=3650)
    relevance_threshold: float = Field(default=0.6, ge=0.0, le=1.0)


class ClarifyingQuestion(DomainModel):
    id: str
    question: str
    why_it_matters: str
    suggested_options: list[str] = Field(default_factory=list)
    assumption_if_skipped: str
    origin: Literal["clarify", "gap_check"] = "clarify"
    answer: str | None = None
    skipped: bool = False

    @property
    def is_resolved(self) -> bool:
        return self.answer is not None or self.skipped


class ResearchQuestion(DomainModel):
    id: str  # "RQ1"
    text: str


class SubTask(DomainModel):
    id: str  # "t1"
    type: SubTaskType
    title: str
    query: str | None = None  # search tasks only
    search_mode: SearchMode = SearchMode.GENERAL
    focus: str | None = None  # cross_check tasks: what to compare
    research_question_ids: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    status: SubTaskStatus = SubTaskStatus.PENDING
    origin: Origin = Origin.PLANNER
    note: str | None = None  # outcome, e.g. "4 kept, 2 excluded"


class ResearchPlan(DomainModel):
    version: int = 1
    objective: str
    research_questions: list[ResearchQuestion]
    subtasks: list[SubTask]
    rationale: str

    def get_subtask(self, subtask_id: str) -> SubTask | None:
        return next((t for t in self.subtasks if t.id == subtask_id), None)


# --- Sources and analysis ----------------------------------------------------------------------


ExclusionRule = Literal["recency", "content", "domain_cap"]


class Exclusion(DomainModel):
    stage: ExclusionStage
    reason: str
    # Which code rule excluded it (stage=rule only). "recency" exclusions are undone when the
    # user widens the date window; the others are not.
    rule: ExclusionRule | None = None


class Source(DomainModel):
    id: str  # "S1"
    url: str
    title: str
    domain: str
    published_date: date | None = None  # None = date unknown (kept but flagged)
    snippet: str = ""
    content: str = ""
    found_by: list[str] = Field(default_factory=list)  # sub-task IDs
    status: SourceStatus = SourceStatus.KEPT
    relevance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    relevance_reason: str | None = None
    exclusion: Exclusion | None = None


class Quote(DomainModel):
    text: str
    context: str = ""


class SourceSummary(DomainModel):
    source_id: str
    summary: str
    key_takeaways: list[str]
    claims: list[str] = Field(default_factory=list)  # used by the cross-check step
    quotes: list[Quote] = Field(default_factory=list)  # verified word for word against content


class Contradiction(DomainModel):
    id: str
    topic: str
    claim_a: str
    source_a: str
    claim_b: str
    source_b: str
    explanation: str
    likely_cause: str = ""  # e.g. different dates, regions or methods


class CitedStatement(DomainModel):
    text: str
    source_ids: list[str]
    supported: bool = True  # set by the citation validator, never by the LLM


class ReportSection(DomainModel):
    heading: str
    statements: list[CitedStatement]


class Report(DomainModel):
    title: str
    executive_summary: str
    key_takeaways: list[CitedStatement]
    sections: list[ReportSection]
    contradictions: list[Contradiction] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    suggested_next_topics: list[str] = Field(default_factory=list)


# --- Transparency, budgets, memory -------------------------------------------------------------


class BudgetUsage(DomainModel):
    searches: int = 0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    replans: int = 0
    gap_questions_asked: int = 0


class ActionLogEntry(DomainModel):
    seq: int
    timestamp: datetime = Field(default_factory=utc_now)
    actor: Actor
    step: str  # e.g. "plan", "search", "user_override"
    action: str  # what happened, e.g. "excluded source"
    decision: str = ""  # the outcome, e.g. "S4 excluded"
    reason: str = ""  # why — shown to the user
    details: dict[str, Any] = Field(default_factory=dict)


class MemoryMatch(DomainModel):
    """A past session related to the current topic, shown as 'from past research'."""

    session_id: str
    topic: str
    summary: str
    key_findings: list[str]
    similarity: float
    created_at: datetime


class MemoryItem(DomainModel):
    id: str = Field(default_factory=new_id)
    user_id: str
    session_id: str
    topic: str
    summary: str
    key_findings: list[str]
    source_urls: list[str]
    suggested_topics: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime  # TTL: never recalled after this, and purged at startup


# --- The session -------------------------------------------------------------------------------


class ResearchSession(DomainModel):
    id: str = Field(default_factory=new_id)
    user_id: str
    topic: str
    mode: Mode = Mode.SUPERVISED
    status: Status = Status.CREATED
    paused: bool = False  # a flag, not a state: resume continues from the same status
    settings: SessionSettings = Field(default_factory=SessionSettings)
    questions: list[ClarifyingQuestion] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    plan: ResearchPlan | None = None
    sources: list[Source] = Field(default_factory=list)
    summaries: list[SourceSummary] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    report: Report | None = None
    related_memory: list[MemoryMatch] = Field(default_factory=list)
    budget: BudgetUsage = Field(default_factory=BudgetUsage)
    log: list[ActionLogEntry] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    # Called with each new log entry (the API streams entries live). Not part of the data:
    # private attributes are never serialized or compared.
    _log_listener: Callable[[ActionLogEntry], None] | None = PrivateAttr(default=None)

    def set_log_listener(self, listener: Callable[[ActionLogEntry], None] | None) -> None:
        self._log_listener = listener

    def get_source(self, source_id: str) -> Source | None:
        return next((s for s in self.sources if s.id == source_id), None)

    def kept_sources(self) -> list[Source]:
        return [s for s in self.sources if s.status == SourceStatus.KEPT]

    def pending_questions(self) -> list[ClarifyingQuestion]:
        return [q for q in self.questions if not q.is_resolved]

    def add_log(
        self,
        *,
        actor: Actor,
        step: str,
        action: str,
        decision: str = "",
        reason: str = "",
        details: dict[str, Any] | None = None,
    ) -> ActionLogEntry:
        entry = ActionLogEntry(
            seq=len(self.log) + 1,
            actor=actor,
            step=step,
            action=action,
            decision=decision,
            reason=reason,
            details=details or {},
        )
        self.log.append(entry)
        if self._log_listener is not None:
            self._log_listener(entry)
        return entry


# --- User commands (human oversight) -----------------------------------------------------------


class AnswerQuestions(DomainModel):
    type: Literal["answer_questions"] = "answer_questions"
    answers: dict[str, str | None]  # question ID -> answer, or None to skip


class ApprovePlan(DomainModel):
    type: Literal["approve_plan"] = "approve_plan"


class SubTaskEdit(DomainModel):
    id: str
    title: str | None = None
    query: str | None = None


class EditPlan(DomainModel):
    type: Literal["edit_plan"] = "edit_plan"
    edits: list[SubTaskEdit]


class SkipSubtask(DomainModel):
    type: Literal["skip_subtask"] = "skip_subtask"
    subtask_id: str


class AddSubtask(DomainModel):
    type: Literal["add_subtask"] = "add_subtask"
    title: str = ""
    query: str = Field(min_length=3, max_length=200)
    search_mode: SearchMode = SearchMode.GENERAL
    research_question_ids: list[str] = Field(default_factory=list)


class ExcludeSource(DomainModel):
    type: Literal["exclude_source"] = "exclude_source"
    source_id: str
    reason: str | None = None


class IncludeSource(DomainModel):
    type: Literal["include_source"] = "include_source"
    source_id: str


class SetRecency(DomainModel):
    type: Literal["set_recency"] = "set_recency"
    recency_days: int = Field(ge=1, le=3650)


class SetMode(DomainModel):
    type: Literal["set_mode"] = "set_mode"
    mode: Mode


class Pause(DomainModel):
    type: Literal["pause"] = "pause"


class Resume(DomainModel):
    type: Literal["resume"] = "resume"


UserCommand = Annotated[
    AnswerQuestions
    | ApprovePlan
    | EditPlan
    | SkipSubtask
    | AddSubtask
    | ExcludeSource
    | IncludeSource
    | SetRecency
    | SetMode
    | Pause
    | Resume,
    Field(discriminator="type"),
]
