# Plan: Fix English Tutor Handoff — Two More Blocking Bugs (PLAN14)

## Context

PLAN13 fixed the async callback crash (`ValueError: Cannot register an async callback with .on()`).
Langfuse trace inspection + docker logs revealed TWO new blocking bugs after that fix.

---

## Bugs Found via `docker logs agent-english` + Langfuse Session Analysis

### Bug 1 — `KeyError: 'context'` at `session.start()` (CRASH)

```
KeyError: 'context'
  File ".../livekit/agents/llm/utils.py", line 325, in function_arguments_to_pydantic_model
    type_hint = type_hints[param_name]
  File ".../livekit/agents/voice/agent_activity.py", line 580, in _start_session
    await self._rt_session.update_tools(llm.ToolContext(self.tools).flatten())
```

**File:** `agent/agents/english_agent.py`, line 110–113

```python
# BEFORE (crashes):
async def route_back_to_orchestrator(
    self,
    context,          # ← no type annotation!
    reason: str,
) -> str:
```

`livekit-agents v1.4.2` calls `typing.get_type_hints()` inside `function_arguments_to_pydantic_model()`
during `update_tools()` at `session.start()`. When `context` has no type annotation it is absent
from the hints dict, raising `KeyError: 'context'`. The session crashes before any audio is produced.

**Fix:**
```python
from livekit.agents import AgentSession, RunContext, function_tool

async def route_back_to_orchestrator(
    self,
    context: RunContext,   # ← add RunContext annotation
    reason: str,
) -> str:
```

### Bug 2 — Orchestrator transition speech cut off before audio finishes

**File:** `agent/tools/routing.py`, `_route_to_english_impl`

```python
# BEFORE (12s fixed timer from function-call time):
async def _close_pipeline_after_english_dispatch():
    await asyncio.sleep(12.0)
    await pipeline_session.aclose()
asyncio.create_task(_close_pipeline_after_english_dispatch())
```

The 12-second countdown started at function-tool invocation — **before** the LLM generated
its response and **before** TTS began playing. When the LLM emits a verbose transition
message, TTS is still playing at T+12s and `aclose()` cancels the in-flight audio frames.
The transcript shows the full text (committed immediately) but the audio is cut short.

**Fix:** Event-driven close — wait for `conversation_item_added` with `role=assistant`
(speech text committed to context), then 5s for WebRTC audio buffer drain:

```python
_close_done = asyncio.Event()

async def _do_close_pipeline():
    if _close_done.is_set():
        return
    _close_done.set()
    await asyncio.sleep(5.0)   # drain audio buffer
    await pipeline_session.aclose()

def _on_transition_committed(item):
    if getattr(item, "role", None) == "assistant":
        asyncio.create_task(_do_close_pipeline())
        pipeline_session.off("conversation_item_added", _on_transition_committed)

pipeline_session.on("conversation_item_added", _on_transition_committed)

async def _fallback_close_pipeline():
    await asyncio.sleep(30.0)   # fallback if event never fires
    await _do_close_pipeline()
asyncio.create_task(_fallback_close_pipeline())
```

---

## Files Modified

| File | Change |
|------|--------|
| `agent/agents/english_agent.py` | Add `RunContext` to import; annotate `context: RunContext` on `route_back_to_orchestrator` |
| `agent/tools/routing.py` | Replace fixed 12s sleep with event-driven close + 5s drain + 30s fallback |

---

## Verification

```bash
# 1. Tests — 72 still passing
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v

# 2. Rebuild
docker compose up -d --build agent agent-english

# 3. No errors on startup:
docker logs livekit-openai-realtime-demo-agent-english-1 --since "2m"
# Expected: "registered worker" — no KeyError, no ValueError

# 4. End-to-end test:
#    - Ask English question ("what is a pronoun?")
#    - Orchestrator transition speech plays FULLY without cutoff  ← Bug 2 fix ✓
#    - English tutor session starts and speaks                    ← Bug 1 fix ✓
#    - Langfuse: English agent_session span appears               ← confirms session started ✓
```

## Results

- 72/72 tests pass
- `agent-english` starts cleanly — no `KeyError`, no `ValueError`
- Commit: `29e4aa2` — fix(agent): fix English KeyError context + speech cutoff (PLAN14)

---

## Addendum: Langfuse MCP Added

The Langfuse MCP server was added to the project for direct API access during debugging:

```bash
claude mcp add --transport http langfuse http://localhost:3001/api/public/mcp \
    --header "Authorization: Basic cGstbGYtZGV2OnNrLWxmLWRldg=="
# cGstbGYtZGV2OnNrLWxmLWRldg== = base64("pk-lf-dev:sk-lf-dev")
# Note: host port is 3001 (container port 3000 → host 3001)
```

---

## Bug Ancestry

| Plan | Bug Fixed |
|------|-----------|
| PLAN11 | Missing `await` on `generate_reply()` |
| PLAN12 | `instructions=` kwarg removed from `RealtimeModel()` |
| PLAN13 | Async callback rejected by EventEmitter + `ctx.room.metadata` vs `ctx.job.metadata` |
| **PLAN14** | `KeyError: 'context'` (missing `RunContext` annotation) + speech cutoff (fixed 12s timer) |
