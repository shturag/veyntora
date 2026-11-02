"""Files attached to a chat question (ADR 0028).

A file is scanned and read when it is attached, and only its text is kept. Plain text is
read here; other formats by the chatbot's ingestion parser, so nothing leaves the network
that the chatbot's data rule does not already allow. The text goes with every question of
the conversation as numbered sources, which the answer may cite like documents.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers.interfaces import FileRef, ParseOptions

from veyntora_api.db.models.conversations import ChatAttachment, Conversation

# What is kept of one file, and what a question carries of all of them (about 12k tokens).
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_KEPT_CHARS = 200_000
MAX_PROMPT_CHARS = 48_000
# Files a question may bring, and that a conversation may hold.
MAX_PER_QUESTION = 5
MAX_PER_CONVERSATION = 10

TEXT_TYPES = {".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv"}
HTML_TYPES = {".html": "text/html", ".htm": "text/html"}
PARSED_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


NO_PARSER = (
    "This assistant reads text files only (.txt, .md, .csv, .html). For PDF, Office and "
    "image files an admin needs to give it a document parser."
)


class AttachmentError(ValueError):
    """The file cannot be attached; the message is for the person."""


def accepted(*, parser: bool) -> list[str]:
    """File endings people may attach: plain text always, other formats with a parser."""
    return [*TEXT_TYPES, *HTML_TYPES, *(PARSED_TYPES if parser else {})]


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in {"script", "style"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def _decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


async def read_text(filename: str, content: bytes, parser: Any | None) -> tuple[str, str]:
    """The file's text and media type. Raises AttachmentError for what cannot be read."""
    ext = posixpath.splitext(filename.lower())[1]
    if ext in TEXT_TYPES:
        return _decode(content), TEXT_TYPES[ext]
    if ext in HTML_TYPES:
        reader = _Text()
        reader.feed(_decode(content))
        return "\n".join(reader.parts), HTML_TYPES[ext]
    if ext not in PARSED_TYPES:
        raise AttachmentError(f"{ext or 'This file type'} cannot be attached.")
    if parser is None:
        raise AttachmentError(NO_PARSER)
    mime = PARSED_TYPES[ext]
    parsed = await parser.parse(FileRef(filename, mime, content), ParseOptions())
    return "\n\n".join(s.text for s in parsed.sections if s.text.strip()), mime


def keep(text: str) -> tuple[str, bool]:
    """The text that is stored, and whether it was cut."""
    text = text.strip()
    return text[:MAX_KEPT_CHARS], len(text) > MAX_KEPT_CHARS


@dataclass(frozen=True, slots=True)
class Attached:
    id: UUID
    name: str
    text: str
    # Cut to fit the question (the stored text may be longer).
    cut: bool = False


def fit(rows: list[ChatAttachment]) -> list[Attached]:
    """The files' text for one question, shared fairly within MAX_PROMPT_CHARS."""
    out: list[Attached] = []
    left = MAX_PROMPT_CHARS
    for i, row in enumerate(rows):
        share = left // (len(rows) - i)
        text = row.text[:share]
        out.append(Attached(row.id, row.name, text, cut=row.truncated or len(row.text) > share))
        left -= len(text)
    return out


async def for_run(
    db: AsyncSession, *, user_id: UUID, chatbot_id: UUID, thread_id: str, ids: list[str]
) -> list[ChatAttachment]:
    """The files of this question and conversation that the asker may use: their own, for
    this chatbot, and not yet sent in another conversation."""
    wanted: list[UUID] = []
    for i in ids[:MAX_PER_CONVERSATION]:
        try:
            wanted.append(UUID(str(i)))
        except ValueError:
            continue
    if not wanted:
        return []
    conv = await db.scalar(sa.select(Conversation.id).where(Conversation.thread_id == thread_id))
    rows = (
        await db.execute(
            sa.select(ChatAttachment)
            .where(
                ChatAttachment.id.in_(wanted),
                ChatAttachment.user_id == user_id,
                ChatAttachment.chatbot_id == chatbot_id,
                sa.or_(
                    ChatAttachment.conversation_id.is_(None),
                    ChatAttachment.conversation_id == conv,
                ),
            )
            .order_by(ChatAttachment.created_at)
        )
    ).scalars()
    return list(rows)


async def link(db: AsyncSession, conversation_id: UUID, ids: list[UUID]) -> None:
    """The files now belong to the conversation (and are deleted with it)."""
    if ids:
        await db.execute(
            sa.update(ChatAttachment)
            .where(ChatAttachment.id.in_(ids), ChatAttachment.conversation_id.is_(None))
            .values(conversation_id=conversation_id)
        )
