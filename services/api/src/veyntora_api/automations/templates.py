"""Starting points on the New automation page. Each one is a draft spec: what the
template cannot know (the tool, the channel, the data source) is left for the admin and
listed as a problem until it is chosen. Nothing runs until the automation is activated."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from veyntora_spec.automation import (
    AgentStep,
    ApprovalStep,
    ApproverSees,
    AutomationSpec,
    Autonomy,
    EventTrigger,
    FileTrigger,
    Holidays,
    NotifyChannel,
    NotifyStep,
    Operator,
    Repeat,
    Rule,
    Safety,
    ScheduleTrigger,
    WatcherTrigger,
)


@dataclass(frozen=True, slots=True)
class Template:
    id: str
    trigger: str
    name: str
    description: str


TEMPLATES = (
    Template(
        "triage",
        "event",
        "Triage new tickets",
        "Classify, find similar cases, draft a reply as an internal note.",
    ),
    Template(
        "weekly_report",
        "schedule",
        "Weekly report",
        "Query data, summarise trends with sources, post to Teams or email.",
    ),
    Template(
        "extract",
        "file",
        "Extract from new documents",
        "Pull fields from invoices or contracts into a table, with a review queue.",
    ),
    Template(
        "deadline_watcher",
        "watcher",
        "Deadline watcher",
        "Alert owners before contracts, certificates or licences expire.",
    ),
    Template(
        "meeting_brief",
        "event",
        "Meeting brief",
        "Before a customer meeting, gather tickets and contract terms into a brief.",
    ),
    Template("blank", "schedule", "Start from scratch", "Choose a trigger and add steps yourself."),
)
TEMPLATE_IDS = frozenset(t.id for t in TEMPLATES)


def _approval(editable: str | None = None) -> ApprovalStep:
    return ApprovalStep(
        id="step2",
        name="Human approval",
        shows=[ApproverSees.REASONING, ApproverSees.DRAFT],
        editable=editable,
    )


def spec_for(template: str, chatbot_id: UUID | None) -> AutomationSpec:
    """The draft spec of a template (`chatbot_id` is the agent steps' pipeline)."""
    if template == "triage":
        return AutomationSpec(
            trigger=EventTrigger(app="Jira", event="ticket.created"),
            steps=[
                AgentStep(
                    id="step1",
                    name="Classify, find similar tickets, draft a reply",
                    chatbot_id=chatbot_id,
                    task=(
                        'Ticket {event.key}: "{event.summary}".\n'
                        "1. Classify it as refund, delivery, account or other.\n"
                        "2. Find up to 3 similar resolved tickets.\n"
                        "3. Check the relevant policy and draft an internal note for the "
                        "support agent with sources.\nDo not contact the customer."
                    ),
                    outputs=["category", "draft_note", "confidence"],
                ),
                _approval(editable="step1.draft_note"),
                NotifyStep(
                    id="step3",
                    name="Tell the assigned agent",
                    channel=NotifyChannel.TEAMS_CHAT,
                    message=(
                        "{event.key} was triaged as {step1.category}. "
                        "Draft note:\n{step1.draft_note}"
                    ),
                ),
            ],
        )
    if template == "weekly_report":
        return AutomationSpec(
            trigger=ScheduleTrigger(
                repeat=Repeat.WEEKLY,
                time="07:45",
                days=["mon"],
                skip_holidays=Holidays(country="DE", subdivision="BW"),
            ),
            steps=[
                AgentStep(
                    id="step1",
                    name="Summarise the week",
                    chatbot_id=chatbot_id,
                    task=(
                        "Write this week's report for the team leads: the main trends and "
                        "open issues, each with its source. Keep it under 200 words."
                    ),
                ),
                _approval(editable="step1.answer"),
                NotifyStep(
                    id="step3",
                    name="Post to Teams",
                    channel=NotifyChannel.TEAMS_CHANNEL,
                    message="Weekly report\n\n{step1.answer}",
                ),
            ],
            safety=Safety(autonomy=Autonomy.APPROVE),
        )
    if template == "extract":
        return AutomationSpec(
            trigger=FileTrigger(file_types=["pdf", "docx"]),
            steps=[
                AgentStep(
                    id="step1",
                    name="Extract the fields",
                    chatbot_id=chatbot_id,
                    task=(
                        'From the new document "{event.title}", extract the parties, the '
                        "start and end dates and any unusual clauses, with sources."
                    ),
                    outputs=["parties", "start_date", "end_date", "risky_clauses"],
                ),
                _approval(),
            ],
            safety=Safety(autonomy=Autonomy.SUGGEST),
        )
    if template == "deadline_watcher":
        return AutomationSpec(
            trigger=WatcherTrigger(
                fire_when=[Rule(field="event.end_date", op=Operator.WITHIN_DAYS, value="60")],
                once_per="id",
            ),
            steps=[
                NotifyStep(
                    id="step1",
                    name="Alert the owner",
                    channel=NotifyChannel.EMAIL,
                    message="{event.name} ends on {event.end_date}. Please review it in time.",
                )
            ],
            safety=Safety(autonomy=Autonomy.REPORT),
        )
    if template == "meeting_brief":
        return AutomationSpec(
            trigger=EventTrigger(app="Calendar", event="meeting.upcoming"),
            steps=[
                AgentStep(
                    id="step1",
                    name="Prepare the brief",
                    chatbot_id=chatbot_id,
                    task=(
                        "The meeting with {event.customer} starts at {event.start}. Gather "
                        "their open tickets and the contract terms that matter, as a short "
                        "brief with sources."
                    ),
                ),
                NotifyStep(
                    id="step2",
                    name="Send the brief",
                    channel=NotifyChannel.TEAMS_CHAT,
                    message="Brief for {event.customer}\n\n{step1.answer}",
                ),
            ],
            safety=Safety(autonomy=Autonomy.REPORT),
        )
    return AutomationSpec()
