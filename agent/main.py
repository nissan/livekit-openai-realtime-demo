"""
LiveKit Agents worker entrypoint.

Registers two worker types:
  - "learning-orchestrator": pipeline session (Orchestrator → Math → History)
  - "learning-english": Realtime session (English agent, same room)

Session lifecycle:
  1. Student joins room → frontend dispatches "learning-orchestrator"
  2. Worker connects, creates SessionUserdata
  3. Supabase: create_session_record()
  4. AgentSession configured with STT + TTS + VAD + OrchestratorAgent
  5. conversation_item_added → publish to room data channel (topic: "transcript")
  6. On shutdown: save session report to Supabase

See PLAN.md: Session Lifecycle
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
)
from livekit.plugins import openai, silero

from agent.agents.orchestrator import OrchestratorAgent
from agent.agents.english_agent import create_english_realtime_session
from agent.models.session_state import SessionUserdata
from agent.services import transcript_store
from agent.services.langfuse_setup import setup_langfuse_tracing, get_tracer, create_session_trace

logger = logging.getLogger(__name__)
_tracer = None  # initialised after setup_langfuse_tracing() in __main__


def _parse_dispatch_metadata(metadata: str) -> dict:
    """Parse 'key:value|key:value' dispatch metadata into a dict."""
    result = {}
    for part in metadata.split("|"):
        if ":" in part:
            key, _, value = part.partition(":")
            result[key] = value
    return result

# -------------------------------------------------------------------
# Worker startup — download model weights before first request
# -------------------------------------------------------------------

def prewarm(proc: JobProcess):
    """
    Download Silero VAD weights at container startup.
    Avoids 200MB download on first student connection.
    See PLAN.md: Latency Strategy.
    """
    proc.userdata["vad"] = silero.VAD.load()  # sync load in prewarm


# -------------------------------------------------------------------
# Pipeline session entrypoint (Orchestrator + Math + History)
# -------------------------------------------------------------------

async def pipeline_session_entrypoint(ctx: JobContext):
    """
    Handles the "learning-orchestrator" dispatch.
    Creates the pipeline AgentSession and starts with OrchestratorAgent.
    """
    # Must be called in each worker subprocess (not just __main__) so OTEL is configured
    setup_langfuse_tracing()

    await ctx.connect()

    # Get student identity from the first participant (the student)
    participant = None
    for p in ctx.room.remote_participants.values():
        participant = p
        break

    # Wait briefly for participant if room is just forming
    if participant is None:
        await asyncio.sleep(1.0)
        for p in ctx.room.remote_participants.values():
            participant = p
            break

    student_identity = participant.identity if participant else "unknown-student"
    room_name = ctx.room.name

    # Recover session_id and question if this pipeline session was re-dispatched
    # after an English Realtime session.
    # Metadata format: "return_from_english:{id}|question:{text}" or "session:{id}|question:{text}"
    # FIXED (PLAN13): ctx.job.metadata holds dispatch request metadata, not ctx.room.metadata
    meta = _parse_dispatch_metadata(ctx.job.metadata or "")
    recovered_session_id = meta.get("return_from_english")
    if not recovered_session_id:
        recovered_session_id = meta.get("session")  # plain session recovery

    pending_question = meta.get("question", "")

    if recovered_session_id:
        logger.info("Recovering session_id from English return: %s", recovered_session_id)

    # Initialise session state
    userdata = SessionUserdata(
        student_identity=student_identity,
        room_name=room_name,
    )
    if recovered_session_id:
        userdata.session_id = recovered_session_id
        userdata.current_subject = "orchestrator"  # back at orchestrator after English

    # If there's a pending_question from re-dispatch metadata, it will be injected via
    # generate_reply(user_input=pending_question) in on_enter — suppress the phantom entry.
    if pending_question:
        userdata.skip_next_user_turns = 1

    # Log session creation to Supabase
    await transcript_store.create_session_record(
        session_id=userdata.session_id,
        room_name=room_name,
        student_identity=student_identity,
    )

    logger.info(
        "Pipeline session starting [session=%s, room=%s, student=%s]",
        userdata.session_id, room_name, student_identity
    )

    # Session start marker — creates root trace context in Langfuse for this session
    tracer = get_tracer("pipeline-session")
    with tracer.start_as_current_span("session.start") as span:
        span.set_attributes(create_session_trace(
            userdata.session_id, student_identity, room_name
        ))
        span.set_attribute("session_type", "pipeline")
        span.set_attribute("recovered", bool(recovered_session_id))

    # VAD loaded in prewarm; await the coroutine if needed
    vad = ctx.proc.userdata.get("vad")
    if asyncio.iscoroutine(vad):
        vad = await vad

    # Configure AgentSession with full STT+LLM+TTS+VAD pipeline
    session = AgentSession(
        userdata=userdata,
        stt=openai.STT(model="gpt-4o-transcribe"),
        tts=openai.TTS(model="gpt-4o-mini-tts", voice="ash"),
        vad=vad,
        min_endpointing_delay=0.4,   # prevent premature cutoff
        max_endpointing_delay=2.0,   # cap long pauses
    )

    # Publish transcript turns to room data channel (topic: "transcript")
    # Frontend subscribes via useTranscript hook
    @session.on("conversation_item_added")
    def on_conversation_item(event):
        # v1.4: event is ConversationItemAddedEvent; event.item is the ChatMessage
        msg = event.item
        role = msg.role  # "user" | "assistant"
        if role == "user":
            # Skip phantom "user" messages injected by generate_reply(user_input=pending_q)
            # in GuardedAgent.on_enter() — these are routing context, not real student speech.
            # String-match is unreliable (LLM varies question_summary wording/casing).
            # Use a counter: routing fns set skip_next_user_turns=1; we consume it here.
            if getattr(userdata, "skip_next_user_turns", 0) > 0:
                userdata.skip_next_user_turns -= 1
                return
            speaker = "student"
        else:
            # speaking_agent is set by GuardedAgent.on_enter() AFTER the transition message
            # fires, so it correctly identifies who SAID the message (not who we routed TO).
            speaker = userdata.speaking_agent or userdata.current_subject or "orchestrator"

        # FIXED (PLAN7): ChatContent is str | AudioContent | ImageContent.
        # The old hasattr(part, "text") check was always False for plain str objects.
        # Use the built-in text_content property which correctly filters isinstance(c, str).
        content = msg.text_content or ""

        if content:
            # Emit OTEL span with session/user/subject context for Langfuse filtering
            with tracer.start_as_current_span("conversation.item") as span:
                span.set_attribute("student.name", userdata.student_identity)
                span.set_attribute("session.id", userdata.session_id)
                span.set_attribute("langfuse.session_id", userdata.session_id)
                span.set_attribute("langfuse.user_id", userdata.student_identity)
                span.set_attribute("user.id", userdata.student_identity)
                span.set_attribute("subject_area", userdata.current_subject or "")
                span.set_attribute("turn_number", userdata.turn_number)
                span.set_attribute("role", role)

            # Publish to data channel for real-time frontend display
            payload = json.dumps({
                "speaker": speaker,
                "role": role,
                "content": content,
                "subject": userdata.current_subject,
                "turn": userdata.turn_number,
                "session_id": userdata.session_id,
            })
            asyncio.create_task(
                ctx.room.local_participant.publish_data(
                    payload.encode(), topic="transcript"
                )
            )

            # Save to Supabase
            asyncio.create_task(transcript_store.save_transcript_turn(
                session_id=userdata.session_id,
                turn_number=userdata.turn_number,
                speaker=speaker,
                role=role,
                content=content,
                subject_area=userdata.current_subject,
            ))

    # Start session with OrchestratorAgent
    # v1.4 API: agent is first positional arg; participant is not accepted
    orchestrator = OrchestratorAgent()
    if pending_question:
        orchestrator._pending_question = pending_question
    await session.start(orchestrator, room=ctx.room)

    # Wait for session to complete — v1.4 has no session.wait(); use close event
    session_closed = asyncio.Event()
    session.on("close", lambda _: session_closed.set())
    await session_closed.wait()

    # Save session report on close
    session_report = {
        "session_id": userdata.session_id,
        "student_identity": student_identity,
        "room_name": room_name,
        "subjects_covered": list(set(userdata.previous_subjects + ([userdata.current_subject] if userdata.current_subject else []))),
        "total_turns": userdata.turn_number,
        "escalated": userdata.escalated,
        "escalation_reason": userdata.escalation_reason,
    }

    # Try to get full conversation history if available
    try:
        history = session.history
        # v1.4: ChatContext is not iterable; use .messages() to get the list
        session_report["conversation_summary"] = [
            {"role": msg.role, "content": str(msg.content)[:500]}
            for msg in history.messages()
        ]
    except AttributeError:
        pass

    await transcript_store.close_session_record(
        session_id=userdata.session_id,
        session_report=session_report,
    )

    # Session end marker — records final stats in Langfuse
    with tracer.start_as_current_span("session.end") as span:
        span.set_attribute("langfuse.session_id", userdata.session_id)
        span.set_attribute("langfuse.user_id", student_identity)
        span.set_attribute("session.id", userdata.session_id)
        span.set_attribute("session_type", "pipeline")
        span.set_attribute("total_turns", userdata.turn_number)
        span.set_attribute("escalated", userdata.escalated)
        span.set_attribute("subjects_covered", ",".join(set(
            userdata.previous_subjects + ([userdata.current_subject] if userdata.current_subject else [])
        )))

    logger.info(
        "Pipeline session ended [session=%s, turns=%d, escalated=%s]",
        userdata.session_id, userdata.turn_number, userdata.escalated
    )


# -------------------------------------------------------------------
# English Realtime session entrypoint
# -------------------------------------------------------------------

async def english_session_entrypoint(ctx: JobContext):
    """
    Handles the "learning-english" dispatch.
    Creates a Realtime AgentSession (OpenAI gpt-realtime) in the same room.
    """
    # Must be called in each worker subprocess so OTEL is configured
    setup_langfuse_tracing()

    await ctx.connect()

    participant = None
    for p in ctx.room.remote_participants.values():
        participant = p
        break

    if participant is None:
        await asyncio.sleep(1.0)
        for p in ctx.room.remote_participants.values():
            participant = p
            break

    student_identity = participant.identity if participant else "unknown-student"
    room_name = ctx.room.name

    # Recover or create session userdata
    # Metadata format: "session:{id}|question:{text}"
    # FIXED (PLAN13): ctx.job.metadata holds dispatch request metadata, not ctx.room.metadata
    meta = _parse_dispatch_metadata(ctx.job.metadata or "")
    existing_session_id = meta.get("session")
    initial_question = meta.get("question", "")

    userdata = SessionUserdata(
        student_identity=student_identity,
        room_name=room_name,
        current_subject="english",
    )
    if existing_session_id:
        userdata.session_id = existing_session_id

    logger.info(
        "English Realtime session starting [session=%s, room=%s]",
        userdata.session_id, room_name
    )

    session = await create_english_realtime_session(
        room=ctx.room,
        participant=participant,
        session_userdata=userdata,
        initial_question=initial_question,
    )

    # Session start marker for the English Realtime session in Langfuse
    tracer_eng = get_tracer("english-session")
    with tracer_eng.start_as_current_span("session.start") as span:
        span.set_attributes(create_session_trace(
            userdata.session_id, student_identity, room_name
        ))
        span.set_attribute("session_type", "realtime_english")

    session_closed = asyncio.Event()
    session.on("close", lambda _: session_closed.set())
    await session_closed.wait()

    # Session end marker for Langfuse
    with tracer_eng.start_as_current_span("session.end") as span:
        span.set_attribute("langfuse.session_id", userdata.session_id)
        span.set_attribute("langfuse.user_id", student_identity)
        span.set_attribute("session.id", userdata.session_id)
        span.set_attribute("session_type", "realtime_english")

    logger.info(
        "English Realtime session ended [session=%s]",
        userdata.session_id
    )


# -------------------------------------------------------------------
# Worker registration
# -------------------------------------------------------------------

if __name__ == "__main__":
    # Set up Langfuse OTEL tracing before starting workers
    setup_langfuse_tracing()

    agent_type = os.environ.get("AGENT_TYPE", "orchestrator")

    if agent_type == "english":
        cli.run_app(
            WorkerOptions(
                entrypoint_fnc=english_session_entrypoint,
                agent_name="learning-english",
                # No prewarm — RealtimeModel handles audio natively, no VAD needed
            ),
        )
    else:
        cli.run_app(
            WorkerOptions(
                entrypoint_fnc=pipeline_session_entrypoint,
                prewarm_fnc=prewarm,
                agent_name="learning-orchestrator",
            ),
        )
