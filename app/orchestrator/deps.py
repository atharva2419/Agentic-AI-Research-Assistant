"""Everything the orchestrator and its steps need from the outside world, in one object.

Tests build this with FakeLLM and FakeSearch; the CLI and API build it with the real clients.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from app.blueprint import Blueprint
from app.llm.base import LLMClient
from app.memory.service import MemoryService
from app.prompts import PromptLibrary
from app.search.base import SearchClient


@dataclass
class AgentDeps:
    llm: LLMClient
    search: SearchClient
    blueprint: Blueprint
    prompts: PromptLibrary
    model_override: str | None = None  # e.g. run every step on Haiku for a cheap smoke test
    today: Callable[[], date] = field(default=date.today)
    memory: MemoryService | None = None  # long-term memory; None = sessions don't remember
