import pytest

from app.config import PROJECT_ROOT
from app.prompts import PromptError, PromptLibrary, parse_prompt
from tests.helpers import BLUEPRINT

TEMPLATE = """# Title
## system
You judge {{thing}}.
## user
Here is {{thing}} with JSON like {"a": 1}.
"""

# The values each step passes to its prompt. Keeps prompt files and code in sync.
EXPECTED_PLACEHOLDERS = {
    "plan.md": {"context", "allowed_types", "max_subtasks", "max_searches"},
    "relevance.md": {"context", "research_questions", "search_purpose", "sources"},
    "summarize.md": {"context", "research_questions", "source"},
    "cross_check.md": {"context", "focus", "summaries"},
    "synthesize.md": {"context", "research_questions", "summaries", "contradictions"},
}


def test_render_fills_placeholders_and_leaves_json_alone() -> None:
    rendered = parse_prompt("t", TEMPLATE).render(thing="sources")
    assert rendered.system == "You judge sources."
    assert '{"a": 1}' in rendered.user


def test_missing_value_fails() -> None:
    with pytest.raises(PromptError, match="missing values"):
        parse_prompt("t", TEMPLATE).render()


def test_unused_value_fails() -> None:
    with pytest.raises(PromptError, match="unused values"):
        parse_prompt("t", TEMPLATE).render(thing="x", extra="y")


def test_sections_are_required() -> None:
    with pytest.raises(PromptError):
        parse_prompt("t", "## system\nonly a system part")


@pytest.mark.parametrize(("filename", "expected"), EXPECTED_PLACEHOLDERS.items())
def test_real_prompt_files_match_the_code(filename: str, expected: set[str]) -> None:
    template = PromptLibrary(PROJECT_ROOT / "prompts").get(filename)
    assert template.placeholders == expected
    assert template.system and template.user


def test_blueprint_points_at_these_prompts() -> None:
    for step in ("plan", "relevance", "summarize", "cross_check", "synthesize"):
        assert BLUEPRINT.steps[step].prompt in EXPECTED_PLACEHOLDERS


def test_missing_file() -> None:
    with pytest.raises(PromptError, match="not found"):
        PromptLibrary(PROJECT_ROOT / "prompts").get("nope.md")
