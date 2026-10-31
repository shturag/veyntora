"""Answer quality metrics with the Ragas definitions, computed through Veyntora's own
provider adapters (product owner, 2026-10-31): the judge model is a provider instance,
so data rules, masking and usage counting apply to it like to any other call.

- faithfulness: the share of the answer's statements the retrieved passages support;
- answer_relevance: mean cosine similarity between the question and questions written
  back from the answer (0 when the answer is noncommittal);
- context_recall: the share of the reference answer's sentences the passages support;
- context_precision: mean precision@k over the passages that help reach the reference;
- tool_accuracy (Veyntora): the expected tool calls, in order, among the agent's calls.

Each judge prompt asks for JSON; an answer that cannot be read scores None (left out of the
averages, and the case fails with the reason), never a made-up number.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from veyntora_providers.interfaces import ChatMessage, Usage

_JSON = re.compile(r"(\[.*\]|\{.*\})", re.S)


@dataclass
class Judge:
    """The judge model and the embedder for answer relevance."""

    llm: Any
    embedder: Any | None
    usage: Usage = field(default_factory=lambda: Usage(0, 0))

    async def ask(self, system: str, user: str, max_tokens: int = 800) -> Any:
        text: list[str] = []
        async for chunk in self.llm.chat(
            [ChatMessage("system", system), ChatMessage("user", user)], max_tokens=max_tokens
        ):
            text.append(chunk.delta)
            if chunk.usage is not None:
                self.usage = Usage(
                    self.usage.prompt_tokens + chunk.usage.prompt_tokens,
                    self.usage.completion_tokens + chunk.usage.completion_tokens,
                )
        found = _JSON.search("".join(text))
        if found is None:
            return None
        try:
            return json.loads(found.group(1))
        except ValueError:
            return None


def _context(passages: Sequence[str]) -> str:
    return "\n\n".join(f"[{n}] {p[:2500]}" for n, p in enumerate(passages, 1))


FAITHFULNESS = """Split the answer into short standalone statements. For each, decide whether
the context supports it. Reply with JSON only:
[{"statement": "...", "supported": true|false}]"""


async def faithfulness(
    judge: Judge, question: str, answer: str, passages: Sequence[str]
) -> float | None:
    if not answer.strip():
        return None
    out = await judge.ask(
        FAITHFULNESS, f"Question: {question}\n\nAnswer: {answer}\n\nContext:\n{_context(passages)}"
    )
    if not isinstance(out, list) or not out:
        return None
    verdicts = [bool(s.get("supported")) for s in out if isinstance(s, dict)]
    return sum(verdicts) / len(verdicts) if verdicts else None


RELEVANCE = """Write 3 questions that the answer below answers. Also say whether the answer is
noncommittal (evasive, "I don't know"). Reply with JSON only:
{"questions": ["...", "...", "..."], "noncommittal": true|false}"""


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


async def answer_relevance(judge: Judge, question: str, answer: str) -> float | None:
    if judge.embedder is None or not answer.strip():
        return None
    out = await judge.ask(RELEVANCE, f"Answer: {answer}")
    if not isinstance(out, dict):
        return None
    if out.get("noncommittal"):
        return 0.0
    generated = [str(q) for q in out.get("questions") or [] if str(q).strip()][:3]
    if not generated:
        return None
    vectors = (await judge.embedder.embed([question, *generated])).dense
    return sum(cosine(vectors[0], v) for v in vectors[1:]) / len(generated)


RECALL = """Split the reference answer into sentences. For each, decide whether the context
contains the information. Reply with JSON only: [{"sentence": "...", "in_context": true|false}]"""


async def context_recall(judge: Judge, reference: str, passages: Sequence[str]) -> float | None:
    if not reference.strip():
        return None
    if not passages:
        return 0.0
    out = await judge.ask(
        RECALL, f"Reference answer: {reference}\n\nContext:\n{_context(passages)}"
    )
    if not isinstance(out, list) or not out:
        return None
    verdicts = [bool(s.get("in_context")) for s in out if isinstance(s, dict)]
    return sum(verdicts) / len(verdicts) if verdicts else None


PRECISION = """For each numbered passage, decide whether it helps to arrive at the reference
answer to the question. Reply with JSON only: [{"n": 1, "useful": true|false}, ...]"""


async def context_precision(
    judge: Judge, question: str, reference: str, passages: Sequence[str]
) -> float | None:
    if not reference.strip():
        return None
    if not passages:
        return 0.0
    out = await judge.ask(
        PRECISION,
        f"Question: {question}\n\nReference answer: {reference}\n\nPassages:\n{_context(passages)}",
    )
    if not isinstance(out, list):
        return None
    useful = {int(v.get("n", 0)) for v in out if isinstance(v, dict) and v.get("useful")}
    flags = [n in useful for n in range(1, len(passages) + 1)]
    return average_precision(flags)


def average_precision(flags: Sequence[bool]) -> float:
    """Ragas context precision: mean of precision@k at each useful position."""
    hits, total = 0, 0.0
    for k, useful in enumerate(flags, 1):
        if useful:
            hits += 1
            total += hits / k
    return total / hits if hits else 0.0


def tool_accuracy(expected: Sequence[str], called: Sequence[str]) -> float | None:
    """The share of expected tools found in order among the calls (None: not an agent case)."""
    if not expected:
        return None
    at, found = 0, 0
    for want in expected:
        while at < len(called) and called[at] != want:
            at += 1
        if at < len(called):
            found += 1
            at += 1
    return found / len(expected)


def mean(values: Sequence[float | None]) -> float | None:
    real = [v for v in values if v is not None]
    return round(sum(real) / len(real), 4) if real else None
