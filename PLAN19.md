# PLAN19: LLM / TTS / STT Integration Test Suite

## Context

All 171 existing tests mock every external API call — no network access required. This
means a broken API key, a deprecated model name, or an API contract change can only be
caught manually. PLAN19 adds a `tests/integration/` suite that calls the real
OpenAI and Anthropic APIs to verify end-to-end connectivity for every AI service the
agent depends on.

Tests skip gracefully when real API keys are absent (safe for CI). When real keys are
present, they exercise the actual models and confirm audio round-trips work.

---

## Architecture Notes (from exploration)

- **Parent `tests/conftest.py`** has `autouse=True` fixture `mock_env_vars` that patches ALL
  env vars with fake keys for every test. Integration tests run in `tests/integration/` and
  inherit this fixture — so the integration conftest must override the fakes with real keys.
- **Module-level singletons** in `guardrail.py` (`_openai_client`, `_anthropic_client`) are
  lazily initialised. Must be reset to `None` before each integration test so they pick up
  the real API keys (not the fakes set by unit tests run earlier in the session).
- **Real keys are captured at module-load time** (before any monkeypatching) via
  `os.environ.get(...)` at the top of the integration conftest — this is the only safe
  moment to read them.

---

## Files Created / Modified

| File | Change |
|---|---|
| `agent/tests/integration/__init__.py` | **New** — package marker (empty) |
| `agent/tests/integration/conftest.py` | **New** — real-key capture, skip logic, singleton reset |
| `agent/tests/integration/test_llm.py` | **New** — 3 LLM tests (Haiku, Sonnet, GPT) |
| `agent/tests/integration/test_tts_stt.py` | **New** — 4 TTS/STT tests incl. round-trip |
| `agent/tests/integration/test_guardrail.py` | **New** — 4 live moderation + rewrite tests |
| `agent/pyproject.toml` | **Modified** — added `integration` marker + `pytest-timeout` dev dep |
| `PLAN19.md` | **New** — architect audit trail (root) |

---

## Test Inventory

### `test_llm.py` (3 tests)
- `test_claude_haiku_responds` — claude-haiku-4-5-20251001, "What is 2 + 2?", assert "4" in response
- `test_claude_sonnet_solves_arithmetic` — claude-sonnet-4-6, "What is 12 times 15?", assert "180"
- `test_openai_gpt_answers_history` — gpt-4o-mini, history question, assert "rome"/"roman" in response

### `test_tts_stt.py` (4 tests)
- `test_tts_alloy_returns_audio` — gpt-4o-mini-tts/alloy, non-empty bytes
- `test_tts_onyx_returns_audio` — gpt-4o-mini-tts/onyx, non-empty bytes
- `test_tts_fable_returns_audio` — gpt-4o-mini-tts/fable, non-empty bytes
- `test_tts_to_stt_round_trip` — TTS → WAV → STT, "forty"/"42" in transcript

### `test_guardrail.py` (4 tests)
- `test_clean_math_question_not_flagged` — check("What is 7 times 8?"), flagged=False
- `test_clean_history_question_not_flagged` — check("Who was Julius Caesar?"), flagged=False
- `test_rewrite_returns_non_empty_string` — rewrite(medieval warfare text), len > 0
- `test_check_and_rewrite_passes_clean_text` — check_and_rewrite("capital of France?"), unchanged

---

## Verification

```bash
# Install new dev dep
uv sync --directory agent

# Integration tests only (requires real API keys in env)
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/integration/ -v -s

# Unit tests only (no keys needed — integration tests auto-skip)
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v --ignore=tests/integration/

# Full suite — integration tests show SKIPPED if keys absent, PASSED if present
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v

# Expected with real keys: 171 unit + 11 integration = 182 passed
# Expected without real keys: 171 passed, 11 skipped
```
