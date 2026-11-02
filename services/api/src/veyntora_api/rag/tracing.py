"""One Langfuse trace per answer, sent as OpenTelemetry spans to Langfuse's OTLP endpoint.

The trace holds the question, the answer, the steps with their timings, the model and token
usage, and which sources were used (titles and scores). Chunk text and prompts are not
copied into traces. Tracing is off unless Langfuse is set up in Integrations (ADR 0024);
a changed address or key takes effect within a minute, without a restart.

A dedicated TracerProvider is used so the graph server's own OpenTelemetry setup is not
affected. A trace can also keep its steps in memory (`collect=True`) for the Playground,
which shows them step by step.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

import structlog
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Tracer
from veyntora_providers.interfaces import Hosting
from veyntora_providers.secrets import OpenBaoReader, SecretReader

from veyntora_api.db.models.platform import IntegrationKind
from veyntora_api.db.session import get_sessionmaker
from veyntora_api.integrations import runtime as integrations
from veyntora_api.rag.guard import Masker, rule_spans
from veyntora_api.settings import get_settings

log = structlog.get_logger()


def _value(value: Any, mask: bool = False) -> Any:
    if isinstance(value, bool | int | float):
        return value
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    # Governance: personal data in traces is masked with the local rules (e-mail, IBAN,
    # phone, card numbers) unless an admin switched that off.
    return Masker().mask(text, rule_spans(text)) if mask else text


class StepSpan:
    def __init__(
        self, span: Span | None, record: dict[str, Any] | None = None, *, mask: bool = False
    ) -> None:
        self._span = span
        self._record = record
        self._mask = mask

    def set(self, **attrs: Any) -> None:
        for key, value in attrs.items():
            if value is None:
                continue
            if self._span is not None:
                self._span.set_attribute(key, _value(value, self._mask))
            if self._record is not None:
                self._record["attrs"][key] = value


class Trace:
    """Spans of one run. With no tracer configured every call is a no-op."""

    def __init__(self, tracer: Tracer | None, *, collect: bool = False, mask: bool = False) -> None:
        self._tracer = tracer
        self.mask = mask
        self.root: Span | None = None
        # Steps in the order they ran: {"name", "ms", "attrs"} (only with collect=True).
        self.steps: list[dict[str, Any]] | None = [] if collect else None

    @property
    def id(self) -> str | None:
        if self.root is None:
            return None
        return format(self.root.get_span_context().trace_id, "032x")

    @contextmanager
    def run(self, name: str, **attrs: Any) -> Iterator[Trace]:
        if self._tracer is None:
            yield self
            return
        with self._tracer.start_as_current_span(name) as span:
            self.root = span
            self.set(**{"langfuse.trace.name": name, **attrs})
            yield self

    @contextmanager
    def step(self, name: str, *, generation: bool = False) -> Iterator[StepSpan]:
        record: dict[str, Any] | None = None
        if self.steps is not None:
            record = {"name": name, "ms": 0, "attrs": {}}
            self.steps.append(record)
        t0 = time.perf_counter()
        try:
            if self._tracer is None:
                yield StepSpan(None, record)
                return
            with self._tracer.start_as_current_span(name) as span:
                kind = "generation" if generation else "span"
                span.set_attribute("langfuse.observation.type", kind)
                yield StepSpan(span, record, mask=self.mask)
        finally:
            if record is not None:
                record["ms"] = round((time.perf_counter() - t0) * 1000)

    def set(self, **attrs: Any) -> None:
        if self.root is not None:
            for key, value in attrs.items():
                if value is not None:
                    self.root.set_attribute(key, _value(value, self.mask))


_TTL_SECONDS = 60.0


class _Tracers:
    """The Langfuse tracer for the current settings, looked up at most once a minute."""

    def __init__(self) -> None:
        self.checked_at = -_TTL_SECONDS
        self.fingerprint: str | None = None
        self.provider: TracerProvider | None = None
        self.tracer: Tracer | None = None
        self.external = False
        self.reader: SecretReader | None = None
        self.lock = asyncio.Lock()

    async def get(self) -> Tracer | None:
        if time.monotonic() - self.checked_at < _TTL_SECONDS:
            return self.tracer
        async with self.lock:
            if time.monotonic() - self.checked_at >= _TTL_SECONDS:
                try:
                    await self._refresh()
                except Exception as exc:  # a trace is never worth failing an answer
                    log.warning("tracing.settings_unavailable", error=type(exc).__name__)
                self.checked_at = time.monotonic()
        return self.tracer

    async def _refresh(self) -> None:
        s = get_settings()
        if self.reader is None:
            self.reader = OpenBaoReader(s.openbao_url, Path(s.openbao_token_file))
        async with get_sessionmaker()() as db:
            conn = await integrations.resolve(db, self.reader, IntegrationKind.LANGFUSE)
        fingerprint = (
            hashlib.sha256(f"{conn.url}\0{conn.public_key}\0{conn.secret}".encode()).hexdigest()
            if conn
            else None
        )
        if fingerprint != self.fingerprint:
            if self.provider is not None:
                self.provider.shutdown()  # sends what is still buffered
            self.provider = _provider(conn) if conn else None
            self.tracer = self.provider.get_tracer("veyntora.fast_rag") if self.provider else None
            self.fingerprint = fingerprint
        self.external = bool(conn and conn.hosting is Hosting.EXTERNAL)


def _provider(conn: integrations.Connection) -> TracerProvider:
    token = base64.b64encode(f"{conn.public_key}:{conn.secret}".encode()).decode()
    provider = TracerProvider(resource=Resource.create({"service.name": "veyntora-graphs"}))
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=f"{conn.url}/api/public/otel/v1/traces",
                headers={"Authorization": f"Basic {token}"},
                timeout=5,
            )
        )
    )
    return provider


_tracers = _Tracers()


class _Rules(Protocol):
    @property
    def mask_traces(self) -> bool: ...
    @property
    def external_traces(self) -> bool: ...


async def new_trace(ctx: _Rules, *, collect: bool = False) -> Trace:
    """A trace under the run's data rules: an external Langfuse only receives the traces of
    chatbots whose rule allows it, and always with personal data masked."""
    tracer = await _tracers.get()
    if _tracers.external:
        return Trace(tracer if ctx.external_traces else None, collect=collect, mask=True)
    return Trace(tracer, collect=collect, mask=ctx.mask_traces)
