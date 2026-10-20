from app.models import CitedStatement, Quote
from app.orchestrator.citations import citation_problems, mark_supported, verify_quotes


def test_citation_problems_catches_unknown_and_missing() -> None:
    problems = citation_problems(
        [("Fine.", ["S1"]), ("No cite.", []), ("Made up.", ["S1", "S99"])],
        allowed_ids={"S1", "S2"},
    )
    assert len(problems) == 2
    assert "no citation" in problems[0]
    assert "S99" in problems[1]


def test_mark_supported() -> None:
    allowed = {"S1"}
    good = mark_supported(CitedStatement(text="a", source_ids=["S1"]), allowed)
    partly = mark_supported(CitedStatement(text="b", source_ids=["S1", "S9"]), allowed)
    none = mark_supported(CitedStatement(text="c", source_ids=[]), allowed)
    assert good.supported
    assert not partly.supported and partly.source_ids == ["S1"]
    assert not none.supported


def test_verify_quotes_tolerates_spacing_and_curly_quotes() -> None:
    content = "The editor said:   “AI will not replace\nreporters.” Then left."
    found, missing = verify_quotes(
        [Quote(text='"AI will not replace reporters."'), Quote(text="AI will replace everyone")],
        content,
    )
    assert [q.text for q in found] == ['"AI will not replace reporters."']
    assert [q.text for q in missing] == ["AI will replace everyone"]
