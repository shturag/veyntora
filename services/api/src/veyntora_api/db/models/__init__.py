"""Import every model so Base.metadata is complete for Alembic and tests."""

from veyntora_api.db.models.automations import Approval, Automation, Run
from veyntora_api.db.models.channels import AppKey, Channel
from veyntora_api.db.models.chatbots import Chatbot, PipelineVersion
from veyntora_api.db.models.conversations import (
    Citation,
    Conversation,
    Feedback,
    Handoff,
    Message,
    SavedAnswer,
    SavedAnswerShare,
)
from veyntora_api.db.models.governance import (
    AuditEvent,
    GdprRequest,
    GovernanceRule,
    LegalHold,
    OutboxEvent,
)
from veyntora_api.db.models.identity import (
    AccessReview,
    AccessReviewItem,
    Group,
    Membership,
    User,
)
from veyntora_api.db.models.knowledge import (
    DataSource,
    Document,
    IngestJob,
    KnowledgeIssue,
    SourceAttachment,
)
from veyntora_api.db.models.platform import PlatformSettings, StatusNotice
from veyntora_api.db.models.providers import ByokKey, ProviderInstance, ProviderInstanceChatbot
from veyntora_api.db.models.quality import Budget, EvalCase, EvalRun, EvalSet, UsageRecord
from veyntora_api.db.models.tools import McpServer, Tool, ToolPolicy

__all__ = [
    "AccessReview",
    "AccessReviewItem",
    "AppKey",
    "Approval",
    "AuditEvent",
    "Automation",
    "Budget",
    "ByokKey",
    "Channel",
    "Chatbot",
    "Citation",
    "Conversation",
    "DataSource",
    "Document",
    "EvalCase",
    "EvalRun",
    "EvalSet",
    "Feedback",
    "GdprRequest",
    "GovernanceRule",
    "Group",
    "Handoff",
    "IngestJob",
    "KnowledgeIssue",
    "LegalHold",
    "McpServer",
    "Membership",
    "Message",
    "OutboxEvent",
    "PipelineVersion",
    "PlatformSettings",
    "ProviderInstance",
    "ProviderInstanceChatbot",
    "Run",
    "SavedAnswer",
    "SavedAnswerShare",
    "SourceAttachment",
    "StatusNotice",
    "Tool",
    "ToolPolicy",
    "UsageRecord",
    "User",
]
