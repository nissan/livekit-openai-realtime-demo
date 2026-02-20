# PLAN18: Synthetic Question Fixtures + Parametrised Routing/Guardrail Tests

## Context

PLAN17 added 30 regression tests and OTEL latency spans. However, all routing tests
call routing *implementation functions* directly with hand-written question strings.
There are no **parametrised, categorised test datasets** that verify:
- Does the routing impl correctly record each subject's question in span attributes?
- Does the guardrail fire for every one of the 13 OpenAI moderation categories?
- Does the escalation path trigger for each class of distress signal?
- Do specialist system prompts cover their expected topic areas?

A synthetic fixture dataset solves all of this: define questions once, run them across
multiple assertions automatically. Adding a new category in future means adding one row
to the fixtures file — no new test code required.

**No LLM calls needed** — routing tests call `_route_to_*_impl()` directly (bypasses LLM
classification). Guardrail tests mock the OpenAI moderation API response. The actual
question text is irrelevant to the mock — only the *category metadata* matters.

---

## Fixture Design

### `agent/tests/fixtures/synthetic_questions.py` (new file)

```python
@dataclass
class SyntheticQuestion:
    question: str         # natural-language question text
    expected_agent: str   # "math" | "history" | "english" | "orchestrator"
    category: str         # broad topic bucket
    rationale: str        # why this question belongs to this agent

@dataclass
class GuardrailInput:
    input_text: str         # representative (non-harmful) placeholder text
    category: str           # OpenAI moderation category name
    description: str        # human-readable description for test docs
```

### Question Sets

| Set | Count | Purpose |
|---|---|---|
| `MATH_QUESTIONS` | 10 | Parametrise routing-to-math tests |
| `HISTORY_QUESTIONS` | 10 | Parametrise routing-to-history tests |
| `ENGLISH_QUESTIONS` | 10 | Parametrise routing-to-english tests |
| `SPECIALIST_OFFTOPIC` | 9 | Cross-subject (math-gets-history, history-gets-english, etc.) |
| `ESCALATION_SIGNALS` | 6 | Distress / welfare signals → escalate_to_teacher |
| `GUARDRAIL_INPUTS` | 13 | One per OpenAI moderation category — all use mock API responses |
| `EDGE_CASES` | 5 | Ambiguous / multi-subject questions |

**Total fixtures: 63 questions** covering all routing paths and every guardrail category.

**Note on GUARDRAIL_INPUTS**: These use innocuous placeholder text (e.g. `"[harassment test input]"`).
The moderation API is mocked so actual harmful content is never needed — only the category
label matters for the parametrised assertion.

---

## New Test File

### `agent/tests/test_synthetic_routing.py` (new file, ~250 lines)

**Six test classes, all parametrised:**

#### 1. `TestSyntheticMathRouting` (10 params)
For each question in `MATH_QUESTIONS`:
- Call `_route_to_math_impl(agent, context, question.question)` with mocked tracer + transcript_store
- Assert `userdata.current_subject == "math"`
- Assert `specialist._pending_question == question.question`
- Assert `userdata.skip_next_user_turns == 1`
- Assert routing span `to_agent` attribute == `"math"`

#### 2. `TestSyntheticHistoryRouting` (10 params)
Same pattern for `HISTORY_QUESTIONS` → `_route_to_history_impl`, `current_subject == "history"`.

#### 3. `TestSyntheticEnglishRouting` (10 params)
For each question in `ENGLISH_QUESTIONS`:
- Call `_route_to_english_impl` with mocked LiveKitAPI (successful dispatch)
- Assert `userdata.current_subject == "english"`
- Assert dispatch called with `CreateAgentDispatchRequest(agent_name="learning-english")`
- Assert question is included in dispatch metadata

#### 4. `TestSyntheticGuardrailTrigger` (13 params)
For each entry in `GUARDRAIL_INPUTS`:
- Mock `_openai_client.moderations.create` to return flagged=True for that category
- Call `check(input.input_text)`
- Assert `result.flagged is True`
- Assert `input.category in result.categories`
- Then call `check_and_rewrite()` with same mock + mocked `rewrite()`
- Assert `rewrite` was called exactly once (not zero, not twice)

#### 5. `TestSyntheticEscalation` (6 params)
For each signal in `ESCALATION_SIGNALS`:
- Call `_escalate_impl(agent, context, signal.question)` with mocked human_escalation + transcript_store
- Assert `userdata.escalated is True`
- Assert `userdata.escalation_reason == signal.question`

#### 6. `TestAgentSystemPromptValidation` (structural, no params)
Static checks that agent prompts cover required topics:
- Orchestrator: contains keywords `route_to_math`, `route_to_history`, `route_to_english`
- Orchestrator: contains `escalate_to_teacher`
- MathAgent: instructions reference arithmetic, algebra, geometry
- HistoryAgent: instructions reference history, civilisations, events
- EnglishAgent: instructions reference grammar, writing, vocabulary
- All specialist instructions contain off-topic routing phrase (route_back_to_orchestrator)
- Guardrail MODERATION_CATEGORIES list == 13 items (regression: no category silently removed)
- GUARDRAIL_INPUTS fixture covers every MODERATION_CATEGORIES entry

---

## Files Created

| File | Description |
|---|---|
| `agent/tests/fixtures/__init__.py` | Empty package marker |
| `agent/tests/fixtures/synthetic_questions.py` | 63-item fixture dataset |
| `agent/tests/test_synthetic_routing.py` | 6 test classes, ~53 parametrised cases |
| `PLAN18.md` | This file — architect audit trail |

No existing files modified.

---

## Key File References

- `agent/agents/orchestrator.py` — OrchestratorAgent system prompt (routing criteria)
- `agent/agents/math_agent.py` — MathAgent system prompt (topics + off-topic detection)
- `agent/agents/history_agent.py` — HistoryAgent system prompt (topics + off-topic detection)
- `agent/agents/english_agent.py` — EnglishAgent system prompt (topics + handoff trigger)
- `agent/services/guardrail.py` — `MODERATION_CATEGORIES` list (13 items), `check()`, `check_and_rewrite()`
- `agent/tools/routing.py` — `_route_to_math_impl`, `_route_to_history_impl`, `_route_to_english_impl`, `_escalate_impl`
- `agent/tests/test_guardrail.py` — `_make_moderation_response()` helper pattern (reused)
- `agent/tests/test_orchestrator_routing.py` — `_make_mock_context()` pattern (reused)
- `frontend/lib/sample-questions.ts` — existing sample questions cross-referenced for realism

---

## Verification

```bash
# Run new synthetic tests only
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/test_synthetic_routing.py -v

# Run full suite — all existing + ~53 new tests must pass
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v
```

## Implementation Notes

- `_make_moderation_response_for_category(category)` helper builds a `SimpleNamespace` mock
  where exactly one category attribute is `True` (score=0.9) and all others are `False`
  (score=0.01). This precisely matches the `cat_map` attribute lookup in `guardrail.check()`.
- `LiveKitAPI` is lazy-imported inside `_route_to_english_impl`'s try block — patch at
  `livekit.api.LiveKitAPI` to intercept it.
- `human_escalation.escalate_to_teacher` is awaited (not fire-and-forget) → mock as `AsyncMock`.
- `asyncio.create_task` is patched globally to suppress background task creation in all routing tests.
- English routing returns a plain `str` on success (not a tuple like math/history).
