"""Guardrails around a Fast RAG run: personal data, prompt injection, topics, promises.

- Personal data is found by local rules (e-mail, IBAN, phone, card numbers) plus the
  pipeline's PII provider when one is set. It is masked with stable placeholders before text
  goes to an external model and put back in the answer, or the question is blocked.
- Prompt injection: local patterns always; the input safety check (Llama Guard) as well when
  configured.
- Blocked topics need the input safety check; "no promises" needs the output safety check
  (publishing refuses otherwise, see PipelineSpec.publish_problems).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from veyntora_providers.interfaces import Verdict
from veyntora_spec.pipeline import InjectionAction, PiiAction, PipelineSpec, TopicAction

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,3})?\b")),
    ("CreditCard", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("Phone", re.compile(r"(?<![\w+])\+?\d[\d ()/-]{7,}\d\b")),
)
_INJECTION = re.compile(
    r"ignore (?:all |any |the )?(?:previous|prior|above|earlier) (?:instructions|rules|prompts?)"
    r"|disregard (?:all |the )?(?:previous|prior|above) "
    r"|(?:reveal|show|print|repeat) (?:me )?(?:your|the) (?:system |hidden )?"
    r"(?:prompt|instructions)"
    r"|ignoriere (?:alle |die )?(?:vorherigen|bisherigen|obigen) (?:anweisungen|regeln)"
    r"|(?:zeig|gib) (?:mir )?(?:deine|die) (?:system)?(?:anweisungen|prompt)",
    re.IGNORECASE,
)


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


@dataclass(frozen=True, slots=True)
class Span:
    start: int
    end: int
    category: str


def rule_spans(text: str) -> list[Span]:
    spans: list[Span] = []
    for category, pattern in _RULES:
        for m in pattern.finditer(text):
            if category == "CreditCard" and not _luhn(re.sub(r"\D", "", m.group())):
                continue
            spans.append(Span(m.start(), m.end(), category))
    return spans


def _merge(spans: Sequence[Span]) -> list[Span]:
    out: list[Span] = []
    for s in sorted(spans, key=lambda x: (x.start, -x.end)):
        if out and s.start < out[-1].end:
            continue  # overlapping detections: keep the first, longest one
        out.append(s)
    return out


@dataclass
class Masker:
    """Replaces personal data with stable placeholders and puts it back afterwards."""

    by_value: dict[str, str] = field(default_factory=dict)
    by_token: dict[str, str] = field(default_factory=dict)

    def mask(self, text: str, spans: Sequence[Span]) -> str:
        out = text
        for s in sorted(_merge(spans), key=lambda x: -x.start):
            value = text[s.start : s.end]
            token = self.by_value.get(value)
            if token is None:
                token = f"[{s.category.upper()}_{len(self.by_value) + 1}]"
                self.by_value[value] = token
                self.by_token[token] = value
            out = out[: s.start] + token + out[s.end :]
        return out

    def unmask(self, text: str) -> str:
        for token, value in self.by_token.items():
            text = text.replace(token, value)
        return text

    @property
    def count(self) -> int:
        return len(self.by_value)


class RunRefusedError(Exception):
    """The run cannot go on; the message is shown to the user as is."""


async def find_pii(pii: Any | None, texts: Sequence[str], language: str) -> list[list[Span]]:
    """Rule spans plus the PII provider's entities (when configured), per text. When the
    provider fails nothing is sent on unmasked: the run is refused with the reason."""
    found = [rule_spans(t) for t in texts]
    if pii is not None:
        try:
            entities = await pii.detect(list(texts), language)
        except Exception as exc:
            raise RunRefusedError(
                "The personal-data check is not available right now, so nothing was sent to "
                "the model. Try again later; if it keeps happening, tell your admin."
            ) from exc
        for i, ents in enumerate(entities):
            found[i] += [Span(e.offset, e.offset + e.length, e.category) for e in ents]
    return found


@dataclass(frozen=True, slots=True)
class GuardOutcome:
    action: Literal["allow", "block", "handoff"]
    warning: str | None = None
    reason: str | None = None


ALLOW = GuardOutcome("allow")


def _topic_hit(verdict: Verdict) -> bool:
    return any(str(c).startswith("Blocked topic") for c in verdict.details.get("categories", []))


def _injection_hit(verdict: Verdict) -> bool:
    return any(str(c).startswith("Prompt injection") for c in verdict.details.get("categories", []))


async def check_input(
    spec: PipelineSpec, question: str, *, pii_found: bool, guard: Any | None
) -> GuardOutcome:
    g = spec.guardrails
    if g.pii is PiiAction.BLOCK and pii_found:
        return GuardOutcome("block", reason="personal data in the question")
    warning = None
    if _INJECTION.search(question):
        if g.injection is InjectionAction.BLOCK:
            return GuardOutcome("block", reason="prompt injection (rules)")
        warning = "The question looks like an attempt to change the assistant's instructions."
    if guard is not None:
        verdict = await guard.check(
            "input",
            {"question": question, "blocked_topics": g.blocked_topics, "check_injection": True},
        )
        if not verdict.allowed:
            categories = ", ".join(map(str, verdict.details.get("categories", [])))
            if (
                _injection_hit(verdict)
                and g.injection is InjectionAction.WARN
                and not _topic_hit(verdict)
                and len(verdict.details.get("categories", [])) == 1
            ):
                warning = (
                    "The question looks like an attempt to change the assistant's instructions."
                )
            elif _topic_hit(verdict) and g.blocked_topic_action is TopicAction.HANDOFF:
                return GuardOutcome("handoff", reason=f"blocked topic: {categories}")
            else:
                return GuardOutcome("block", reason=f"input check: {categories}")
    return GuardOutcome("allow", warning=warning)


async def check_output(
    spec: PipelineSpec, question: str, answer: str, *, guard: Any | None
) -> GuardOutcome:
    if guard is None:
        return ALLOW
    verdict = await guard.check(
        "output",
        {"question": question, "answer": answer, "no_promises": spec.guardrails.no_promises},
    )
    if verdict.allowed:
        return ALLOW
    categories = ", ".join(map(str, verdict.details.get("categories", [])))
    return GuardOutcome("block", reason=f"output check: {categories}")


def guard_instances(spec: PipelineSpec) -> tuple[UUID | None, UUID | None, UUID | None]:
    g = spec.guardrails
    return g.input_guardrail_instance_id, g.output_guardrail_instance_id, g.pii_instance_id
