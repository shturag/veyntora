"""One Langfuse trace per answer, sent as OpenTelemetry spans to Langfuse's OTLP endpoint.

The trace holds the question, the answer, the steps with their timings, the model and token
usage, and which sources were used (titles and scores). Chunk text and prompts are not
copied into traces. Tracing is off unless Langfuse keys are configured.

A dedicated TracerProvider is used so the graph server's own OpenTelemetry setup is not
affected.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Tracer

from veyntora_api.settings import Settings, get_settings


def _value(value: Any) -> Any:
    if isinstance(value, str | bool | int | float):
        return value
    return json.dumps(value, default=str, ensure_ascii=False)


class StepSpan:
    def __init__(self, span: Span | None) -> None:
        self._span = span

    def set(self, **attrs: Any) -> None:
        if self._span is not None:
            for key, value in attrs.items():
                if value is not None:
                    self._span.set_attribute(key, _value(value))


class Trace:
    """Spans of one run. With no tracer configured every call is a no-op."""

    def __init__(self, tracer: Tracer | None) -> None:
        self._tracer = tracer
        self.root: Span | None = None

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
        if self._tracer is None:
            yield StepSpan(None)
            return
        with self._tracer.start_as_current_span(name) as span:
            span.set_attribute("langfuse.observation.type", "generation" if generation else "span")
            yield StepSpan(span)

    def set(self, **attrs: Any) -> None:
        if self.root is not None:
            for key, value in attrs.items():
                if value is not None:
                    self.root.set_attribute(key, _value(value))


@lru_cache
def _tracer() -> Tracer | None:
    s: Settings = get_settings()
    secret = s.langfuse_secret_key.get_secret_value()
    if not (s.langfuse_url and s.langfuse_public_key and secret):
        return None
    token = base64.b64encode(f"{s.langfuse_public_key}:{secret}".encode()).decode()
    provider = TracerProvider(resource=Resource.create({"service.name": "veyntora-graphs"}))
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=f"{s.langfuse_url.rstrip('/')}/api/public/otel/v1/traces",
                headers={"Authorization": f"Basic {token}"},
                timeout=5,
            )
        )
    )
    return provider.get_tracer("veyntora.fast_rag")


def new_trace() -> Trace:
    return Trace(_tracer())
