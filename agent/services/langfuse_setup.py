"""
OTEL → Langfuse observability setup.

Langfuse v3 uses HTTP/protobuf for OTEL ingestion — NOT gRPC.
Endpoint: {langfuse_host}/api/public/otel/v1/traces
Auth: Basic base64(public_key:secret_key)

See PLAN.md Critical Gotchas #13.
"""
from __future__ import annotations

import base64
import logging
import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

logger = logging.getLogger(__name__)


def setup_langfuse_tracing() -> TracerProvider | None:
    """
    Configure OTEL tracing to export to Langfuse.
    Returns the TracerProvider, or None if config is missing.

    Called once at worker startup in main.py.
    """
    langfuse_host = os.environ.get("LANGFUSE_HOST", "http://localhost:3001")
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")

    if not public_key or not secret_key:
        logger.warning(
            "LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY not set — "
            "OTEL tracing disabled. Set these env vars to enable Langfuse."
        )
        return None

    # Build Basic auth header: base64(public_key:secret_key)
    credentials = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()

    exporter = OTLPSpanExporter(
        endpoint=f"{langfuse_host}/api/public/otel/v1/traces",
        headers={"Authorization": f"Basic {credentials}"},
    )

    resource = Resource.create({
        "service.name": "learning-voice-agent",
        "service.version": "1.0.0",
    })

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    logger.info("Langfuse OTEL tracing configured → %s", langfuse_host)
    return provider


def get_tracer(name: str = "learning-agent"):
    """Get an OTEL tracer for manual span creation."""
    return trace.get_tracer(name)


def set_session_span_attributes(
    span,
    session_id: str,
    student_identity: str,
) -> None:
    """
    Attach Langfuse session/user attributes to an OTEL span.

    Langfuse indexes these automatically for filtering in the UI:
      - langfuse.session_id → Session dimension
      - langfuse.user_id    → User dimension
    """
    span.set_attribute("langfuse.session_id", session_id)
    span.set_attribute("langfuse.user_id", student_identity)
    span.set_attribute("session.id", session_id)
    span.set_attribute("user.id", student_identity)


def create_session_trace(
    session_id: str,
    student_identity: str,
    room_name: str,
) -> dict:
    """
    Return OTEL-compatible trace metadata dict for Langfuse session tracking.

    Use as span attributes on the session root span:
        span.set_attributes(create_session_trace(...))
    """
    return {
        "langfuse.session_id": session_id,
        "langfuse.user_id": student_identity,
        "session.id": session_id,
        "user.id": student_identity,
        "room.name": room_name,
        "service.name": "learning-voice-agent",
    }
