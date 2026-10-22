"""Offline LLM: answers every pipeline step with plausible, valid output for any topic.

It reads what it needs (topic, source IDs, source text) from the prompt it receives, so its answers
pass the same validators as real ones: citations point at real source IDs and quotes are copied
from the source text. A short delay per call makes the live UI feel like a real run.
"""

import asyncio
import re

from pydantic import BaseModel

from app.llm.base import LLMRequest, LLMResponse
from app.models import SearchMode, SubTaskType
from app.orchestrator.steps.clarify import ClarifyOutput
from app.orchestrator.steps.cross_check import ContradictionOutput, CrossCheckOutput
from app.orchestrator.steps.gap_check import GapCheckOutput
from app.orchestrator.steps.plan import PlannedQuestion, PlannedSubTask, PlanOutput
from app.orchestrator.steps.questions import QuestionOutput
from app.orchestrator.steps.search import RelevanceJudgment, RelevanceOutput
from app.orchestrator.steps.summarize import QuoteOutput, SummaryOutput
from app.orchestrator.steps.synthesize import CitedClaim, SectionOutput, SynthesisOutput

SOURCE_TAG = re.compile(r'<source id="(S\d+)" title="([^"]*)"[^>]*>\n(.*?)\n</source>', re.DOTALL)
TOPIC = re.compile(r"^Topic: (.+)$", re.MULTILINE)


def _topic(request: LLMRequest) -> str:
    match = TOPIC.search(request.messages[0].content)
    return match.group(1).strip() if match else "the topic"


def _sources(request: LLMRequest) -> list[tuple[str, str, str]]:
    """(id, title, body) for each <source> in the prompt."""
    return SOURCE_TAG.findall(request.messages[0].content)


def _first_sentence(text: str) -> str:
    sentence = text.strip().split(". ")[0]
    return sentence if sentence.endswith(".") else sentence + "."


class OfflineLLM:
    def __init__(self, delay_s: float = 0.6) -> None:
        self._delay_s = delay_s

    async def complete(self, request: LLMRequest) -> LLMResponse:
        await asyncio.sleep(self._delay_s)
        output = self._answer(request)
        text = output.model_dump_json()
        return LLMResponse(
            text=text,
            model=request.model,
            input_tokens=sum(len(m.content) for m in request.messages) // 4,
            output_tokens=len(text) // 4,
            stop_reason="end_turn",
        )

    def _answer(self, request: LLMRequest) -> BaseModel:
        handlers = {
            "clarify": self._clarify,
            "plan": self._plan,
            "relevance": self._relevance,
            "summarize": self._summarize,
            "cross_check": self._cross_check,
            "gap_check": self._gap_check,
            "synthesize": self._synthesize,
        }
        return handlers[request.step](request)

    def _clarify(self, request: LLMRequest) -> ClarifyOutput:
        return ClarifyOutput(
            is_ambiguous=True,
            reasoning="The topic could be researched for different regions; the answer changes "
            "which sources matter.",
            questions=[
                QuestionOutput(
                    question="Which region should the research focus on?",
                    why_it_matters="Evidence and regulation differ a lot between regions.",
                    suggested_options=["United States", "European Union", "Global"],
                    assumption_if_skipped="Global coverage, weighted to English-language sources",
                )
            ],
        )

    def _plan(self, request: LLMRequest) -> PlanOutput:
        topic = _topic(request)

        def task(
            task_id: str,
            kind: SubTaskType,
            title: str,
            query: str | None = None,
            mode: SearchMode = SearchMode.GENERAL,
            rqs: list[str] | None = None,
            deps: list[str] | None = None,
            focus: str | None = None,
        ) -> PlannedSubTask:
            return PlannedSubTask(
                id=task_id,
                type=kind,
                title=title,
                query=query,
                search_mode=mode,
                focus=focus,
                research_question_ids=rqs or [],
                depends_on=deps or [],
            )

        return PlanOutput(
            objective=f"Give an evidence-based overview of {topic}.",
            research_questions=[
                PlannedQuestion(id="RQ1", text=f"What is the current state of {topic}?"),
                PlannedQuestion(
                    id="RQ2",
                    text=f"What impacts of {topic} are reported, and where do sources disagree?",
                ),
            ],
            subtasks=[
                task(
                    "t1",
                    SubTaskType.SEARCH,
                    "Recent developments",
                    f"{topic} latest developments",
                    SearchMode.NEWS,
                    ["RQ1"],
                ),
                task(
                    "t2",
                    SubTaskType.SEARCH,
                    "Studies and data",
                    f"{topic} study data",
                    SearchMode.GENERAL,
                    ["RQ2"],
                ),
                task("t3", SubTaskType.SUMMARIZE, "Summarize sources", deps=["t1", "t2"]),
                task(
                    "t4",
                    SubTaskType.CROSS_CHECK,
                    "Compare the reported figures",
                    deps=["t3"],
                    focus="Do sources agree on how widespread the change is?",
                ),
            ],
            rationale="Start with recent news for the current picture, then studies for "
            "measured impact, and cross-check the figures because surveys often disagree.",
            recency_days=None,
            recency_reason="",
        )

    def _relevance(self, request: LLMRequest) -> RelevanceOutput:
        judgments = []
        for source_id, title, _ in _sources(request):
            if "listicle" in title.lower():
                judgments.append(
                    RelevanceJudgment(
                        source_id=source_id,
                        score=0.2,
                        reason="Clickbait list with no substantive information.",
                    )
                )
            else:
                judgments.append(
                    RelevanceJudgment(
                        source_id=source_id,
                        score=0.85,
                        reason="Directly addresses the research questions with survey data.",
                    )
                )
        return RelevanceOutput(judgments=judgments)

    def _summarize(self, request: LLMRequest) -> SummaryOutput:
        _, title, body = _sources(request)[0]
        share = re.search(r"(\d+)% of organisations", body)
        figure = f"{share.group(1)}%" if share else "a share"
        return SummaryOutput(
            summary=f"{title}. The source reports that {figure} of organisations surveyed changed "
            "their approach in the past year, with large differences by size and budget.",
            key_takeaways=[
                f"{figure} of surveyed organisations report changes in the past year.",
                "Smaller organisations report more difficulty.",
                "Critics say long-term effects are still unclear.",
            ],
            claims=[f"{figure} of organisations surveyed changed their approach in the past year."],
            quotes=[QuoteOutput(text=_first_sentence(body), context="Opening finding")],
        )

    def _cross_check(self, request: LLMRequest) -> CrossCheckOutput:
        sources = _sources(request)
        if len(sources) < 2:
            return CrossCheckOutput(contradictions=[])
        (a, _, body_a), (b, _, body_b) = sources[0], sources[1]
        share_a = re.search(r"(\d+)%", body_a)
        share_b = re.search(r"(\d+)%", body_b)
        if not share_a or not share_b or share_a.group(1) == share_b.group(1):
            return CrossCheckOutput(contradictions=[])
        return CrossCheckOutput(
            contradictions=[
                ContradictionOutput(
                    topic="How widespread the change is",
                    claim_a=f"{share_a.group(1)}% of organisations changed their approach",
                    source_a=a,
                    claim_b=f"{share_b.group(1)}% of organisations changed their approach",
                    source_b=b,
                    explanation="The sources report very different shares for the same measure.",
                    likely_cause="Different samples and survey methods.",
                )
            ]
        )

    def _gap_check(self, request: LLMRequest) -> GapCheckOutput:
        return GapCheckOutput(
            verdict="sufficient",
            reasoning="Both research questions have at least two summarized, recent sources.",
            gaps=[],
            new_searches=[],
            question=None,
        )

    def _synthesize(self, request: LLMRequest) -> SynthesisOutput:
        topic = _topic(request)
        ids = [source_id for source_id, _, _ in _sources(request)]
        first, rest = ids[:1], ids[1:] or ids[:1]
        return SynthesisOutput(
            title=f"{topic[:1].upper()}{topic[1:]}: what the recent evidence shows",
            executive_summary=(
                f"Recent sources agree that {topic} is changing how organisations work, but they "
                "disagree sharply on how widespread the change is. Smaller organisations face "
                "more difficulty, and long-term effects remain unclear. (Offline demo data.)"
            ),
            key_takeaways=[
                CitedClaim(
                    text="Surveys report substantial change in the past year.", source_ids=first
                ),
                CitedClaim(
                    text="Estimates of how widespread the change is differ widely.",
                    source_ids=ids[:2],
                ),
                CitedClaim(text="Smaller organisations report more difficulty.", source_ids=rest),
            ],
            sections=[
                SectionOutput(
                    heading="Current state",
                    statements=[
                        CitedClaim(
                            text="Most recent coverage describes active change.", source_ids=first
                        ),
                    ],
                ),
                SectionOutput(
                    heading="Impact and disagreements",
                    statements=[
                        CitedClaim(
                            text="Sources report figures between 35% and 62%.", source_ids=ids[:2]
                        ),
                    ],
                ),
            ],
            open_questions=["What explains the gap between survey estimates?"],
            limitations=["Offline demo mode: sources and findings are generated, not real."],
            suggested_next_topics=[f"Regulation of {topic}", f"{topic} in small organisations"],
        )
