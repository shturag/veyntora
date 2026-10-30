from pathlib import Path
from uuid import uuid4

import yaml
from veyntora_api.rag.pipeline import Answer, Source
from veyntora_workers.evaluation import Result, score, summarize

EVALS = Path(__file__).resolve().parents[3] / "evals" / "phase1"


def _answer(outcome: str, text: str = "", doc: str | None = None) -> Answer:
    cited = []
    if doc:
        cited = [(1, Source("c1", doc, "T", "", "quote", None, 0.9))]
    return Answer(outcome, text, cited=cited)  # type: ignore[arg-type]


def test_the_set_has_20_questions_and_its_documents() -> None:
    cases = yaml.safe_load((EVALS / "questions.yaml").read_text())
    assert len(cases) == 20
    names = {p.name for p in (EVALS / "corpus").glob("*.md")}
    assert {c["doc"] for c in cases if "doc" in c} <= names


def test_scoring() -> None:
    doc = str(uuid4())
    names = {doc: "refund-policy.md"}
    case = {"q": "?", "doc": "refund-policy.md", "facts": [["30 days", "30 Tage"]]}
    assert score(case, _answer("answered", "Within 30 days [1].", doc), names)[0]
    assert not score(case, _answer("answered", "Within 14 days [1].", doc), names)[0]
    assert not score(case, _answer("answered", "Within 30 days [1].", str(uuid4())), names)[0]
    assert not score(case, _answer("no_answer", "I couldn't find this."), names)[0]
    silent = {"q": "?", "expect": "no_answer"}
    assert score(silent, _answer("no_answer"), names)[0]
    assert score(silent, _answer("blocked"), names)[0]
    assert not score(silent, _answer("answered", "Guess [1].", doc), names)[0]


def test_summary_counts_and_p95() -> None:
    results = [
        Result("q", "answer", "answered", True, "", ms) for ms in (900, 1100, 1300, 1500, 2600)
    ] + [Result("x", "no_answer", "no_answer", True, "", 300, hr_chunks_seen=0)]
    s = summarize(results)
    assert s["answerable_passed"] == "5/5" and s["no_answer_passed"] == "1/1"
    assert s["p95_latency_ms"] == 2600 and not s["p95_within_target"]
