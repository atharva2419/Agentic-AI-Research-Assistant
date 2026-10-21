"""Build the agent's dependencies from settings: real clients, or the offline demo pair.

Shared by the CLI and the API so both run the exact same agent.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.blueprint import load_blueprint
from app.config import Settings
from app.demo.offline_llm import OfflineLLM
from app.demo.offline_search import OfflineSearch
from app.llm.anthropic_client import AnthropicLLMClient
from app.orchestrator.deps import AgentDeps
from app.prompts import PromptLibrary
from app.search.tavily_client import TavilySearchClient


class MissingKeys(Exception):
    pass


async def _nothing_to_close() -> None:
    return None


@dataclass
class Wiring:
    deps: AgentDeps
    offline: bool
    close: Callable[[], Awaitable[None]]  # release HTTP connections on shutdown


def build_wiring(settings: Settings, offline: bool | None = None) -> Wiring:
    offline = settings.offline_mode if offline is None else offline
    blueprint = load_blueprint(settings.blueprint_path)
    prompts = PromptLibrary(settings.prompts_dir)

    if offline:
        deps = AgentDeps(
            llm=OfflineLLM(), search=OfflineSearch(), blueprint=blueprint, prompts=prompts
        )
        return Wiring(deps=deps, offline=True, close=_nothing_to_close)

    if settings.anthropic_api_key is None or settings.tavily_api_key is None:
        raise MissingKeys(
            "Set ANTHROPIC_API_KEY and TAVILY_API_KEY in .env, or set OFFLINE_MODE=true."
        )
    search = TavilySearchClient(
        api_key=settings.tavily_api_key.get_secret_value(),
        timeout_s=blueprint.limits.search_timeout_s,
        depth=blueprint.search.depth,
    )
    deps = AgentDeps(
        llm=AnthropicLLMClient(
            api_key=settings.anthropic_api_key.get_secret_value(),
            timeout_s=blueprint.limits.llm_timeout_s,
        ),
        search=search,
        blueprint=blueprint,
        prompts=prompts,
        model_override=settings.llm_model_override,
    )
    return Wiring(deps=deps, offline=False, close=search.aclose)
