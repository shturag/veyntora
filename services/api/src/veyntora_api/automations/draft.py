"""A draft automation from a description (New automation → "Create draft").

The chatbot's own model reads the admin's description and proposes a trigger and steps
as JSON; the result is validated as an AutomationSpec. It is only a draft: nothing runs
until it is reviewed and activated, and every check of the builder applies. Tools can
only be ones the chatbot already uses; anything the model invents is dropped.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from veyntora_spec.automation import AutomationSpec

PROMPT = """You turn a description of a business automation into a JSON draft.
Answer with one JSON object and nothing else:
{{"name": "...", "trigger": TRIGGER, "steps": [STEP, ...],
  "autonomy": "suggest"|"approve"|"report"}}

TRIGGER is one of:
{{"type": "schedule", "repeat": "daily"|"weekly"|"monthly"|"hours", "time": "HH:MM",
  "days": ["mon", ...], "day_of_month": 1-28, "every_hours": 1-24}}
{{"type": "event", "app": "...", "event": "name.of.event"}}
{{"type": "file", "folder": "...", "file_types": ["pdf", ...]}}
{{"type": "watcher", "tool": "TOOL NAME", "every": "hour"|"day", "time": "HH:MM",
  "fire_when": [{{"field": "event.<field>", "op": "within_days"|"equals"|"gt"|"lt",
  "value": "..."}}], "once_per": "<field>"}}

STEP is one of (ids are "step1", "step2", ... in order):
{{"id": "stepN", "type": "agent", "name": "...", "task": "...", "tools": ["TOOL NAME"],
  "outputs": ["field"]}}
{{"id": "stepN", "type": "condition", "name": "...",
  "rules": [{{"field": "stepN.<field>"|"event.<field>", "op": "equals"|"gt"|"lt"|"contains",
  "value": "..."}}], "yes": "stepN"|"end", "no": "stepN"|"end"}}
{{"id": "stepN", "type": "approval", "name": "..."}}
{{"id": "stepN", "type": "tool", "name": "...", "tool": "TOOL NAME",
  "arguments": {{"name": "{{stepN.<field>}}"}}}}
{{"id": "stepN", "type": "notify", "name": "...",
  "channel": "teams_channel"|"teams_chat"|"email", "message": "... {{stepN.answer}} ..."}}

Use only these tools: {tools}.
Put an approval step before any step that changes data or sends a message to people.
Later steps may use earlier results as {{stepN.answer}}, {{stepN.<output>}}, {{event.<field>}}."""

_JSON = re.compile(r"\{.*\}", re.S)
_TRIGGER_KEYS = {
    "schedule": {"type", "repeat", "time", "days", "day_of_month", "every_hours"},
    "event": {"type", "app", "event"},
    "file": {"type", "folder", "file_types"},
    "watcher": {"type", "every", "time", "fire_when", "once_per"},
}
_STEP_KEYS = {
    "agent": {"id", "type", "name", "task", "outputs"},
    "condition": {"id", "type", "name", "rules", "join", "yes", "no"},
    "approval": {"id", "type", "name"},
    "tool": {"id", "type", "name", "arguments"},
    "notify": {"id", "type", "name", "channel", "message"},
}


class DraftError(ValueError):
    pass


def prompt(tools: dict[str, UUID]) -> str:
    return PROMPT.format(tools=", ".join(sorted(tools)) or "(none)")


def _trigger(raw: Any, tools: dict[str, UUID]) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("type") not in _TRIGGER_KEYS:
        return {"type": "schedule"}
    out = {k: v for k, v in raw.items() if k in _TRIGGER_KEYS[raw["type"]]}
    if raw["type"] == "watcher":
        out["tool_id"] = str(tools[raw["tool"]]) if raw.get("tool") in tools else None
        out.setdefault("fire_when", [{"field": "event.id", "op": "equals", "value": ""}])
    return out


def _step(raw: Any, chatbot_id: UUID, tools: dict[str, UUID]) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or raw.get("type") not in _STEP_KEYS:
        return None
    kind = raw["type"]
    out = {k: v for k, v in raw.items() if k in _STEP_KEYS[kind]}
    if kind == "agent":
        out["chatbot_id"] = str(chatbot_id)
        out["tool_ids"] = [str(tools[n]) for n in raw.get("tools") or [] if n in tools]
    if kind == "tool":
        out["tool_id"] = str(tools[raw["tool"]]) if raw.get("tool") in tools else None
        out["arguments"] = {str(k): str(v) for k, v in (raw.get("arguments") or {}).items()}
    return out


def parse(text: str, chatbot_id: UUID, tools: dict[str, UUID]) -> tuple[str, AutomationSpec]:
    """The draft's name and spec from the model's answer."""
    found = _JSON.search(text or "")
    if found is None:
        raise DraftError("The model did not return a draft. Try a clearer description.")
    try:
        raw = json.loads(found.group(0))
    except ValueError as exc:
        raise DraftError("The model's draft was not valid. Try again or use a template.") from exc
    if not isinstance(raw, dict):
        raise DraftError("The model's draft was not valid. Try again or use a template.")
    steps = [s for s in (_step(r, chatbot_id, tools) for r in raw.get("steps") or []) if s]
    ids = [s.get("id") for s in steps]
    usable = all(isinstance(i, str) and re.fullmatch(r"step\d+", i) for i in ids)
    if not usable or len(set(ids)) != len(ids):
        for n, step in enumerate(steps, 1):
            step["id"] = f"step{n}"
    autonomy = (
        raw.get("autonomy")
        if raw.get("autonomy") in {"suggest", "approve", "report"}
        else "approve"
    )
    try:
        spec = AutomationSpec.model_validate(
            {
                "trigger": _trigger(raw.get("trigger"), tools),
                "steps": steps[:30],
                "safety": {"autonomy": autonomy},
            }
        )
    except ValidationError as exc:
        raise DraftError(
            "The draft did not fit what automations can do. "
            "Try a simpler description or a template."
        ) from exc
    name = str(raw.get("name") or "New automation").strip()[:255] or "New automation"
    return name, spec
