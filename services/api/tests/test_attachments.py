from typing import Any
from uuid import uuid4

import pytest
from veyntora_api.db.models.conversations import ChatAttachment
from veyntora_api.rag import attachments
from veyntora_providers.interfaces import ParsedDoc, ParsedSection


async def test_plain_text_and_html_are_read_without_a_parser() -> None:
    text, mime = await attachments.read_text("notes.md", "# Hi\nÄrger".encode(), None)
    assert text == "# Hi\nÄrger" and mime == "text/markdown"
    html = b"<html><style>p{}</style><body><p>Hello</p><script>x()</script><p>world</p></body>"
    text, _ = await attachments.read_text("page.html", html, None)
    assert text == "Hello\nworld"
    text, _ = await attachments.read_text("legacy.txt", "Grüße".encode("cp1252"), None)
    assert text == "Grüße"


async def test_other_formats_need_the_parser() -> None:
    with pytest.raises(attachments.AttachmentError, match="document parser"):
        await attachments.read_text("report.pdf", b"%PDF", None)
    with pytest.raises(attachments.AttachmentError, match="cannot be attached"):
        await attachments.read_text("tool.exe", b"MZ", None)

    class Parser:
        async def parse(self, file: Any, opts: Any) -> ParsedDoc:
            assert file.mime_type == "application/pdf"
            return ParsedDoc("r", None, [ParsedSection(("A",), "First"), ParsedSection((), "")])

    text, mime = await attachments.read_text("report.pdf", b"%PDF", Parser())
    assert text == "First" and mime == "application/pdf"
    assert ".pdf" in attachments.accepted(parser=True)
    assert ".pdf" not in attachments.accepted(parser=False)


def test_long_files_are_cut_and_shared_fairly() -> None:
    kept, cut = attachments.keep("x" * (attachments.MAX_KEPT_CHARS + 5))
    assert len(kept) == attachments.MAX_KEPT_CHARS and cut

    def row(n: int) -> ChatAttachment:
        return ChatAttachment(id=uuid4(), name=f"f{n}", text="y" * n, truncated=False)

    small, big = row(100), row(attachments.MAX_PROMPT_CHARS)
    fitted = attachments.fit([small, big])
    assert len(fitted[0].text) == 100 and not fitted[0].cut
    assert len(fitted[1].text) == attachments.MAX_PROMPT_CHARS - 100 and fitted[1].cut
