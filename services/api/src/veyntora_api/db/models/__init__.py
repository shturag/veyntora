"""Import every model so Base.metadata is complete for Alembic and tests."""

from veyntora_api.db.models.automations import (
    Approval,
    Automation,
    AutomationSeen,
    AutomationVersion,
    Run,
)
from veyntora_api.db.models.channels import (
    AppKey,
    Channel,
    ChannelDestination,
    ChannelIdentity,
    ChannelThread,
)
from veyntora_api.db.models.chatbots import Chatbot, PipelineVersion
from veyntora_api.db.models.conversations import (
    Citation,
    Conversation,
    ConversationShare,
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
    DocumentIndex,
    IngestJob,
    KnowledgeIssue,
    KnowledgeScan,
    SourceAttachment,
)
from veyntora_api.db.models.notifications import Delivery, Notification
from veyntora_api.db.models.platform import PlatformSettings, StatusNotice
from veyntora_api.db.models.providers import ByokKey, ProviderInstance, ProviderInstanceChatbot
from veyntora_api.db.models.quality import Budget, EvalCase, EvalRun, EvalSet, UsageRecord
from veyntora_api.db.models.tools import McpServer, Tool, ToolCall, ToolPolicy

__all__ = [
    "AccessReview",
    "AccessReviewItem",
    "AppKey",
    "Approval",
    "AuditEvent",
    "Automation",
    "AutomationSeen",
    "AutomationVersion",
    "Budget",
    "ByokKey",
    "Channel",
    "ChannelDestination",
    "ChannelIdentity",
    "ChannelThread",
    "Chatbot",
    "Citation",
    "Conversation",
    "ConversationShare",
    "DataSource",
    "Delivery",
    "Document",
    "DocumentIndex",
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
    "KnowledgeScan",
    "LegalHold",
    "McpServer",
    "Membership",
    "Message",
    "Notification",
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
    "ToolCall",
    "ToolPolicy",
    "UsageRecord",
    "User",
]
