import asyncio
import struct
from collections.abc import AsyncIterator, Callable

import pytest
from veyntora_api.knowledge import clamd
from veyntora_providers.interfaces import ParsedSection
from veyntora_workers.chunking import (
    Chunk,
    approx_tokens,
    contextual_text,
    detect_language,
    fixed_chunks,
)

DE = (
    "Die Rückerstattung für digitale Produkte ist nach dem Download nicht möglich. "
    "Ausnahmen werden von der Teamleitung genehmigt und sind im Ticket zu dokumentieren. "
    "Wenn ein Kunde sich beschwert, wird der Fall an den Support weitergegeben."
)
EN = (
    "Refunds for digital products are not possible after the download. Exceptions can be "
    "approved by a team lead and have to be documented in the ticket. If a customer "
    "complains, the case is handed to the support team for a decision."
)


def test_fixed_chunks_respect_size_and_overlap() -> None:
    words = " ".join(f"w{i}" for i in range(1000))
    chunks = fixed_chunks([ParsedSection(("Policy",), words)], size=130, overlap=26)
    assert all(approx_tokens(c.text) <= 130 for c in chunks)
    first, second = chunks[0].text.split(), chunks[1].text.split()
    assert first[-20:] == second[:20], "consecutive chunks overlap by ~20 words"
    assert chunks[-1].text.split()[-1] == "w999", "nothing is lost at the end"
    assert all(c.heading_path == ("Policy",) for c in chunks)


def test_language_detection() -> None:
    assert detect_language(DE) == "de"
    assert detect_language(EN) == "en"
    assert detect_language("SKU-1 SKU-2 SKU-3") is None


def test_contextual_header() -> None:
    chunk = Chunk("Not after download.", ("4 Refunds", "4.2 Digital"), (3,), False)
    assert contextual_text("Refund policy", chunk) == (
        "Refund policy > 4 Refunds > 4.2 Digital\n\nNot after download."
    )


@pytest.fixture
async def fake_clamd() -> AsyncIterator[Callable[[bytes], str]]:
    """A clamd stand-in speaking INSTREAM; the reply depends on the received bytes."""
    replies: dict[str, bytes] = {}

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        command = await reader.readuntil(b"\0")
        if command == b"zPING\0":
            writer.write(b"PONG\0")
        else:
            data = b""
            while True:
                (size,) = struct.unpack(">I", await reader.readexactly(4))
                if size == 0:
                    break
                data += await reader.readexactly(size)
            if b"EICAR" in data:
                writer.write(b"stream: Eicar-Test-Signature FOUND\0")
            elif len(data) > 200_000:
                writer.write(b"INSTREAM size limit exceeded. ERROR\0")
            else:
                writer.write(b"stream: OK\0")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    replies["address"] = f"127.0.0.1:{port}".encode()
    yield lambda _: replies["address"].decode()
    server.close()
    await server.wait_closed()


async def test_clamd_clean_infected_and_errors(fake_clamd: Callable[[bytes], str]) -> None:
    address = fake_clamd(b"")
    assert await clamd.ping(address)
    assert (await clamd.scan_bytes(address, b"hello" * 30_000)).clean  # several chunks
    infected = await clamd.scan_bytes(address, b"X5O!P%@AP EICAR test")
    assert not infected.clean and infected.detail == "Eicar-Test-Signature"
    with pytest.raises(clamd.ScannerUnavailableError, match="size limit"):
        await clamd.scan_bytes(address, b"x" * 300_000)


async def test_unreachable_scanner_is_not_clean() -> None:
    assert not await clamd.ping("127.0.0.1:1")
    with pytest.raises(clamd.ScannerUnavailableError):
        await clamd.scan_bytes("127.0.0.1:1", b"data", wait_s=1)
