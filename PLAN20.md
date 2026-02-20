# PLAN20: Guardrail Security Test Suite — Harmful Content & TTS Pipeline Coverage

## Context

PLAN19's integration tests only verify **false-positive protection** (clean content not
wrongly flagged). The critical gap is that no tests confirm the guardrail actually
**catches and rewrites harmful content** (true-positive detection). Additionally, the
`tts_node` sentence-buffering pipeline in `GuardedAgent` has zero unit test coverage
despite being the core safety mechanism that every pipeline agent relies on.

This plan adds:
1. **Integration tests** that send mildly harmful content to the real `omni-moderation-latest`
   endpoint and verify it is flagged and rewritten
2. **Unit tests** for `GuardedAgent.tts_node` sentence buffering + guardrail invocation
3. **Additional unit tests** for multi-category detection and edge cases

---

## Architecture Notes

- `GuardedAgent.tts_node` (`agent/agents/base.py:51–114`) buffers LLM text at
  `SENTENCE_ENDINGS = (".", "!", "?", ":", ";")` and calls `check_and_rewrite()` per
  sentence. Remaining partial text is flushed when the stream closes (line 95).
- `check_and_rewrite()` (`agent/services/guardrail.py:196`) returns the **original text
  unchanged** if clean, or a **Haiku rewrite** if flagged.
- `Agent.default.tts_node(agent, text_stream, settings)` is called after filtering —
  this is what actually synthesises audio frames.
- The existing `_make_moderation_response()` helper in `test_guardrail.py` hardcodes
  `harassment_score=0.9`; it needs a `scores` dict param for new tests.
- `GuardedAgent` inherits from `Agent` (LiveKit). Bypass `__init__` with
  `object.__new__(GuardedAgent)` to create a testable instance without LiveKit infra.

---

## Files Created / Modified

| File | Change |
|---|---|
| `agent/tests/integration/test_guardrail_security.py` | **New** — 5 integration tests (true-positive + adversarial inputs) |
| `agent/tests/test_guardrail_tts_node.py` | **New** — 4 unit tests for tts_node sentence buffering |
| `agent/tests/test_guardrail.py` | **Modified** — extend `_make_moderation_response`, add 3 unit tests |
| `PLAN20.md` | **New** — architect audit trail (this file) |

---

## Integration Tests: `agent/tests/integration/test_guardrail_security.py`

Uses the real `omni-moderation-latest` and real Claude Haiku rewriter. Tests skip
when API keys are absent (inherits `require_real_api_keys` from integration conftest).

Mark class `@pytest.mark.timeout(30)`.

### TestHarmfulContentDetected (3 tests)

| Test | Input | Assert |
|---|---|---|
| `test_harassment_phrase_is_flagged` | `"I hate you, you are worthless and stupid."` | `flagged=True`, `"harassment" in categories` |
| `test_flagged_content_gets_rewritten` | same phrase via `check_and_rewrite()` | `result != input` AND `len(result) > 0` |
| `test_rewritten_output_passes_moderation` | rewrite output → `check()` | `flagged=False` (safe text is clean) |

### TestAdversarialInputEdgeCases (2 tests)

| Test | Input | Assert |
|---|---|---|
| `test_empty_text_does_not_crash` | `check("")` | no exception; `isinstance(result.flagged, bool)` |
| `test_very_long_text_handled` | `check("What is mathematics? " * 150)` (~3000 chars, clean) | no exception; `flagged=False` |

---

## Unit Tests: `agent/tests/test_guardrail_tts_node.py`

Tests the `GuardedAgent.tts_node` sentence-buffering and guardrail invocation
**without LiveKit infrastructure** using `object.__new__` + attribute injection.

| Test | Input chunks | Assert |
|---|---|---|
| `test_complete_sentence_triggers_one_guardrail_call` | `["What is", " the answer?"]` | `len(calls) == 1`; `calls[0] == "What is the answer?"` |
| `test_two_sentences_trigger_two_guardrail_calls` | `["Hello. ", "World!"]` | `len(calls) == 2`; first call ends with `.` |
| `test_partial_sentence_flushed_at_stream_end` | `["No punctuation here"]` | `len(calls) == 1`; `calls[0] == "No punctuation here"` |
| `test_rewritten_text_flows_to_tts` | `["Bad sentence."]` with `rewrite_fn=lambda _: "Safe text."` | `received_by_tts == ["Safe text."]` |

---

## Modified Unit Tests: `agent/tests/test_guardrail.py`

Extended `_make_moderation_response` with `scores: dict[str, float] | None = None` param.

### New tests added to existing `TestCheck` class:

| Test | Mock setup | Assert |
|---|---|---|
| `test_multiple_categories_all_returned` | `flagged=True`, `categories=["harassment", "violence"]` | Both `"harassment"` and `"violence"` in `result.categories` |
| `test_highest_score_is_maximum_across_categories` | `scores={"harassment": 0.9, "violence": 0.7}` (both flagged) | `result.highest_score == 0.9` (pytest `approx`) |
| `test_empty_text_does_not_crash` | `_make_moderation_response(flagged=False)` | No exception; `result.flagged is False` |

---

## Verification

```bash
# Unit tests only (no API keys needed)
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/test_guardrail.py tests/test_guardrail_tts_node.py -v

# Integration security tests only (requires real keys)
set -a && source .env && set +a
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/integration/test_guardrail_security.py -v -s

# Full suite
set -a && source .env && set +a
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v

# Expected totals (with real keys):
#   178 unit passed + 16 integration passed = 194 total
# Expected totals (without real keys):
#   178 unit passed, 16 skipped
```

---

## Status: COMPLETE

All tests implemented and verified against the architecture described above.
