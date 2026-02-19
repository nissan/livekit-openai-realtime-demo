# Plan: Per-Agent TTS Voices

## Context

All pipeline agents (Orchestrator, Math, History) currently share a single TTS voice
(`"ash"`) configured at the session level in `main.py:114`. The English Realtime agent
also uses `"ash"`. The user wants each agent to have a distinct voice so the session
sounds like different people talking.

**LiveKit agents v1.4 mechanism**: Each `Agent` accepts an optional `tts=` parameter
in `__init__`. When set, `Agent.default.tts_node()` (called in `GuardedAgent.tts_node`)
prefers the agent's own TTS over the session-level TTS — the same pattern already used
for per-agent LLMs (`MathAgent` overrides with `anthropic.LLM`, `HistoryAgent` with
`openai.LLM`). **No changes to `GuardedAgent.base.py` or `main.py` are required.**

---

## Proposed Voice Assignments

| Agent | Voice | Rationale |
|---|---|---|
| **OrchestratorAgent** | `alloy` | Warm, friendly concierge — welcoming and neutral |
| **MathAgent** | `onyx` | Deep, authoritative — precise and methodical |
| **HistoryAgent** | `fable` | Expressive, narrative — suits storytelling |
| **EnglishAgent** (Realtime) | `shimmer` | Light, animated — creative language focus |

All voices are from OpenAI's `gpt-4o-mini-tts` model voice set.
The session-level default in `main.py` stays as `"ash"` (unreachable fallback).

---

## Files Modified

| File | Change |
|---|---|
| `agent/agents/orchestrator.py` | Added `openai` import, `ORCHESTRATOR_TTS_VOICE = "alloy"` constant, `tts_voice` class attr, `tts=` in `__init__` |
| `agent/agents/math_agent.py` | Added `openai` import, `MATH_TTS_VOICE = "onyx"` constant, `tts_voice` class attr, `tts=` in `__init__` |
| `agent/agents/history_agent.py` | Added `HISTORY_TTS_VOICE = "fable"` constant, `tts_voice` class attr, `tts=` in `__init__` (openai already imported) |
| `agent/agents/english_agent.py` | Changed `voice="ash"` → `voice="shimmer"` in `RealtimeModel` constructor |

New test file:

| File | Change |
|---|---|
| `agent/tests/test_agent_voices.py` | New — 4 tests verifying distinct voice assignments |

---

## Implementation Details

### `agent/agents/orchestrator.py`

```python
from livekit.plugins import anthropic, openai   # added openai

ORCHESTRATOR_TTS_VOICE = "alloy"

class OrchestratorAgent(GuardedAgent):
    agent_name = "orchestrator"
    tts_voice = ORCHESTRATOR_TTS_VOICE

    def __init__(self, chat_ctx=None):
        super().__init__(
            instructions=ORCHESTRATOR_SYSTEM_PROMPT,
            llm=anthropic.LLM(model="claude-haiku-4-5-20251001", temperature=0.1),
            tts=openai.TTS(model="gpt-4o-mini-tts", voice=ORCHESTRATOR_TTS_VOICE),
            chat_ctx=chat_ctx,
        )
```

### `agent/agents/math_agent.py`

```python
from livekit.plugins import anthropic, openai   # added openai

MATH_TTS_VOICE = "onyx"

class MathAgent(GuardedAgent):
    agent_name = "math"
    tts_voice = MATH_TTS_VOICE

    def __init__(self, chat_ctx=None):
        super().__init__(
            instructions=MATH_SYSTEM_PROMPT,
            llm=anthropic.LLM(model="claude-sonnet-4-6", temperature=0.3),
            tts=openai.TTS(model="gpt-4o-mini-tts", voice=MATH_TTS_VOICE),
            chat_ctx=chat_ctx,
        )
```

### `agent/agents/history_agent.py`

```python
HISTORY_TTS_VOICE = "fable"

class HistoryAgent(GuardedAgent):
    agent_name = "history"
    tts_voice = HISTORY_TTS_VOICE

    def __init__(self, chat_ctx=None):
        model = os.environ.get("OPENAI_HISTORY_MODEL", _DEFAULT_HISTORY_MODEL)
        super().__init__(
            instructions=HISTORY_SYSTEM_PROMPT,
            llm=openai.LLM(model=model),
            tts=openai.TTS(model="gpt-4o-mini-tts", voice=HISTORY_TTS_VOICE),
            chat_ctx=chat_ctx,
        )
```

### `agent/agents/english_agent.py`

Changed `voice="ash"` → `voice="shimmer"` in the `RealtimeModel` constructor.

---

## Test Results

```
44 passed in 1.17s
```

| File | Before | Added | After |
|---|---|---|---|
| `test_agent_voices.py` | 0 | 4 | 4 |
| All other test files | 40 | 0 | 40 |
| **Total** | **40** | **4** | **44** |

---

## Verification Commands

```bash
# Smoke test — imports + voice constants visible
PYTHONPATH=$(pwd) uv run --directory agent python3 -c "
from agent.agents.orchestrator import OrchestratorAgent
from agent.agents.math_agent import MathAgent
from agent.agents.history_agent import HistoryAgent
print('Orchestrator:', OrchestratorAgent.tts_voice)
print('Math:        ', MathAgent.tts_voice)
print('History:     ', HistoryAgent.tts_voice)
"

# Full test suite
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v

# Targeted: just voice tests
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/test_agent_voices.py -v
```

After restarting the stack, connect and speak to each agent in turn to hear the
distinct voices: Orchestrator (alloy), Math (onyx), History (fable), English (shimmer).

## Status: IMPLEMENTED ✓
Date: 2026-02-19
