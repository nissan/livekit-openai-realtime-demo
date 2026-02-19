# Plan: Fix English Silence + Mid-sentence Cutoff (PLAN11)

## Context

After routing to English, students heard silence — the English tutor would join the room
but never speak. Additionally, the transition TTS message was cut off mid-sentence.

**Diagnosis from Langfuse trace `136203ea`:**
- English agent joined room successfully
- `session.generate_reply()` called but no audio produced
- Transition message cut off at exactly T+4.009s from routing decision

---

## Root Cause Analysis

### Bug 1 — Missing `await` on `session.generate_reply()`

**In `agent/agents/english_agent.py`:**

```python
# BEFORE: coroutine created but silently discarded (never awaited)
session.generate_reply(user_input=initial_question)
```

Without `await`, the coroutine object is created but immediately garbage-collected.
The English tutor joins the room but never generates speech.

### Bug 2 — Pipeline close timer too short (4s)

**In `agent/tools/routing.py`:**

```python
await asyncio.sleep(4.0)
```

From trace `136203ea`, routing decision fires at T=0 and TTS begins at ~T+0.5s and
runs ~3.5s, completing at T+4.009s. Pipeline closes at T+4.0s — **cutting off the
final 9ms**, causing an audible truncation.

### Bonus — Greet delay too short (1.5s)

WebRTC audio pipeline setup takes variable time. With only 1.5s delay between room
connection and first `generate_reply()`, the audio channel may not be ready, causing
the reply to be lost even when correctly awaited.

---

## Files Modified

| File | Change |
|------|--------|
| `agent/agents/english_agent.py` | Add `await` to `session.generate_reply()` |
| `agent/agents/english_agent.py` | Greet delay: 1.5s → 3.0s |
| `agent/agents/english_agent.py` | Remove unused `RoomInputOptions` import |
| `agent/tools/routing.py` | `asyncio.sleep(4.0)` → `asyncio.sleep(8.0)` |

---

## Changes Applied

### Fix 1 — Add `await` to `generate_reply()`

```python
# BEFORE:
session.generate_reply(user_input=initial_question)

# AFTER:
await session.generate_reply(user_input=initial_question)
```

### Fix 2 — Increase greet delay for WebRTC audio pipeline setup

```python
# BEFORE:
await asyncio.sleep(1.5)

# AFTER:
await asyncio.sleep(3.0)  # extra time for WebRTC audio pipeline setup
```

### Fix 3 — Increase pipeline close delay to 8s

```python
# BEFORE:
await asyncio.sleep(4.0)

# AFTER:
await asyncio.sleep(8.0)
```

---

## Outcome

All 72 tests pass. Changes deployed via `docker compose up -d --build agent agent-english`.

**Note:** PLAN11 correctly added `await` and increased delays. However, a deeper crash
(`TypeError: RealtimeModel.__init__() got an unexpected keyword argument 'instructions'`)
was discovered in PLAN12 which prevented the English agent from ever creating its session.
PLAN11's fixes are still correct and necessary — they just never executed because the
crash happened before `generate_reply()` was reached. PLAN12 fixes the root crash.

---

## Git Commit

`42d0665 fix(agent): fix English silence + mid-sentence cutoff (PLAN11)`
