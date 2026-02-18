# Plan: Testing Infrastructure, Demo Walkthrough & Langfuse Evaluation

## Context

The codebase has **no tests and no guided walkthrough** despite having pytest and all infra
in place:
- `agent/pyproject.toml` — pytest + pytest-asyncio installed, `asyncio_mode = "auto"`, but
  no `test_*.py` files exist
- No Playwright config or frontend test files
- No sample questions or suggested-question UI for first-time testers
- Langfuse OTEL tracing is wired (OTEL → Langfuse), but traces lack session/user metadata
  so filtering/scoring in the Langfuse UI is painful

User choices:
- **Testing**: UI-only Playwright (no WebRTC mock) + pytest unit tests for agent services
- **Walkthrough UX**: Both — hints panel in student UI **and** a `/demo` text-based page

---

## Part 1 — Playwright (frontend UI tests, CI-friendly)

### Setup
Add to `frontend/package.json` devDependencies:
- `@playwright/test` — test runner
- Test script: `"test:e2e": "playwright test"` and `"test:e2e:ui": "playwright test --ui"`

New file: `frontend/playwright.config.ts`
- `baseURL: "http://localhost:3000"`
- WebServer command: `npm run dev` (or use existing running server)
- Two projects: `chromium`, `firefox`
- `testDir: "./tests/e2e"`

### Test files (new — no existing tests to reuse)

`frontend/tests/e2e/home.spec.ts`
- Renders role selector (Student / Teacher buttons)
- Name input accepts text
- "Start Learning →" navigates to `/student?name=...`
- "Monitor Sessions →" navigates to `/teacher?name=...`
- Empty name shows validation or defaults gracefully

`frontend/tests/e2e/token-api.spec.ts`
- `GET /api/token?identity=test&name=Test&role=student&room=test-room` returns 200
- Response has `{ token, roomName, identity, livekitUrl }` shape
- Missing params return 400

`frontend/tests/e2e/student.spec.ts`
- Navigating to `/student?name=Alex` shows loading spinner
- After token fetch, `StudentRoom` renders (mocked LiveKit — assert no crash)
- Page title and header include student name

`frontend/tests/e2e/teacher.spec.ts`
- `/teacher?name=Ms.+Jones` renders Teacher Portal heading
- Escalation monitoring panel renders ("Monitoring for escalations...")
- No crash without Supabase (Supabase URL missing → graceful fallback)

`frontend/tests/e2e/demo.spec.ts`
- `/demo` renders without crashing
- All 4 scenario sections visible (Math, English, History, Escalation)
- Sample question buttons are clickable
- Progress tracker shows 0 / N questions completed

---

## Part 2 — Pytest unit tests (agent services)

New directory: `agent/tests/`
New files: `agent/tests/__init__.py`, `agent/tests/conftest.py`

### `agent/tests/test_session_state.py`
Tests for `agent/models/session_state.py` — `SessionUserdata`:
- `advance_turn()` increments and returns correct value
- `route_to()` sets `current_subject`, appends previous to `previous_subjects`
- `to_dict()` includes all fields, `created_at` is ISO string

### `agent/tests/test_guardrail.py`
Tests for `agent/services/guardrail.py`:
- `check()` with mocked OpenAI client: clean text → `flagged=False`
- `check()` with mocked OpenAI client: flagged response → `flagged=True, categories=[...]`
- `rewrite()` with mocked Anthropic client: returns rewritten text
- `rewrite()` when client throws → returns safe fallback string
- `check_and_rewrite()`: clean text passes through unchanged
- `check_and_rewrite()`: flagged text triggers rewrite (mock both clients)

Mocking pattern (uses `pytest-mock` or `unittest.mock`):
```python
# Patch the lazy singletons directly
with patch("agent.services.guardrail._openai_client") as mock_oai:
    mock_oai.moderations.create = AsyncMock(return_value=...)
```
Add `pytest-mock>=3.14` to `agent/pyproject.toml` dev-dependencies.

### `agent/tests/test_orchestrator_routing.py`
Tests for routing logic in `agent/agents/orchestrator.py`:
- `OrchestratorAgent` instantiates without error (mock `anthropic.LLM`)
- Routing span attributes are set correctly when `route_to_math()` is called
  (mock `RunContext`, `tracer.start_as_current_span`)
- `route_to()` updates `SessionUserdata.current_subject` as a side effect

---

## Part 3 — Suggested Questions hints panel (student UI)

### New file: `frontend/components/SuggestedQuestions.tsx`

Collapsible panel on the student page showing curated sample questions grouped by subject.
Renders below the header, above the transcript. Collapsed by default after first question asked
(dismisses automatically when `turns.length > 0`).

```
┌─────────────────────────────────────────────────────┐
│ 💡 Not sure what to ask? Try one of these:     [×]  │
├─────────────────────────────────────────────────────┤
│ 📐 Maths       📖 English       🏛️ History           │
│ ──────────     ───────────      ──────────           │
│ What is 7×8?   What is an      Who was Julius       │
│                adjective?       Caesar?              │
│ Explain        their/there/     What caused WW1?    │
│ fractions      they're?                             │
└─────────────────────────────────────────────────────┘
```

Sample questions (4 per subject):

| Math | English | History |
|---|---|---|
| "What is 7 times 8?" | "What is an adjective?" | "Who was Julius Caesar?" |
| "Can you explain fractions?" | "What's the difference between their, there, and they're?" | "What caused World War One?" |
| "How do I find the area of a circle?" | "Can you help me write a better sentence?" | "Tell me about the Egyptian pyramids" |
| "What is the Pythagorean theorem?" | "What is alliteration?" | "What was the Industrial Revolution?" |

### Modify `frontend/components/StudentRoom.tsx`
- Import and render `<SuggestedQuestions />` between header and transcript
- Pass `visible={turns.length === 0}` to auto-hide once conversation starts

---

## Part 4 — `/demo` guided walkthrough page

### New file: `frontend/app/demo/page.tsx`

Standalone page — no name prompt, no LiveKit connection. Pure guidance document with:
1. **Header**: "Testing Walkthrough" + instructions ("Start a student session in another tab, then work through these scenarios")
2. **Scenario cards** (4 sections, each with a checklist):

**Scenario 1 — Subject Routing**
Test that each subject routes correctly:
- [ ] Say: *"What is 7 times 8?"* → SubjectBadge shows 📐 Maths
- [ ] Say: *"What is an adjective?"* → SubjectBadge shows 📖 English
- [ ] Say: *"Who was Julius Caesar?"* → SubjectBadge shows 🏛️ History

**Scenario 2 — Multi-turn session**
Test that the agent handles topic switches:
- [ ] Ask a maths question, then ask a history question → routing switches
- [ ] Return to maths → SubjectBadge updates back

**Scenario 3 — Escalation**
- [ ] Say: *"I'm really confused and upset, nothing makes sense"*
  → Agent escalates → teacher portal at `/teacher` receives notification
  → EscalationBanner appears in student session

**Scenario 4 — Edge cases**
- [ ] Off-topic question ("What's for lunch?") → agent redirects politely
- [ ] Cross-subject question ("What fraction of Roman soldiers were cavalry?") → routes to math OR history

3. **Progress tracker** — checkbox state persisted in `localStorage`
4. **Links**: "Open Student Session →" (opens `/student?name=Tester` in new tab), "Open Teacher Portal →"
5. **Langfuse analysis section** — instructions on where to find traces and how to add scores

### New file: `frontend/app/demo/layout.tsx` (minimal, no LiveKit providers needed)

---

## Part 5 — Langfuse trace enrichment for human evaluation

### Modify `agent/services/langfuse_setup.py`
Add a `create_session_trace()` helper that returns a Langfuse-compatible trace dict:
- Uses OTEL span attributes: `session.id = session_id`, `user.id = student_identity`
- Adds `langfuse.session_id` and `langfuse.user_id` as OTEL resource/span attributes
- These map to Langfuse's "Session" and "User" filter dimensions in the UI

### Modify `agent/main.py` — `on_conversation_item()` handler
Add OTEL span attributes when saving transcript turns:
- `student.name` — from `userdata.student_identity`
- `session.id` — from `userdata.session_id`
- `subject_area` — from transcript turn
- `turn_number` — for ordering

### Modify `agent/agents/orchestrator.py` — routing spans
Enrich existing `routing.decision` spans with:
- `question_summary` — the text the model classified
- `confidence` (if available from LLM response)
- `previous_subject` — for switch detection analysis

### No new SDK needed
All enrichment goes through OTEL attributes which Langfuse automatically indexes.
Langfuse manual scoring workflow (document in README):
1. Go to `http://localhost:3001` → Traces
2. Filter by `user.id` (student name) or `session.id`
3. Click a trace → find the LLM span for the subject agent response
4. Click "Add Score" → set name="quality", value=1-5 + comment
5. Aggregate scores: Langfuse Scores dashboard shows distribution per agent

---

## Files to Create

| File | Purpose |
|---|---|
| `frontend/playwright.config.ts` | Playwright config (baseURL, projects, testDir) |
| `frontend/tests/e2e/home.spec.ts` | Home page navigation tests |
| `frontend/tests/e2e/token-api.spec.ts` | `/api/token` endpoint tests |
| `frontend/tests/e2e/student.spec.ts` | Student page render tests |
| `frontend/tests/e2e/teacher.spec.ts` | Teacher portal render tests |
| `frontend/tests/e2e/demo.spec.ts` | Demo page render tests |
| `frontend/components/SuggestedQuestions.tsx` | Collapsible hints panel |
| `frontend/app/demo/page.tsx` | Guided testing walkthrough page |
| `frontend/app/demo/layout.tsx` | Minimal layout (no LiveKit providers) |
| `agent/tests/__init__.py` | Package marker |
| `agent/tests/conftest.py` | Shared pytest fixtures (mock env vars, mock clients) |
| `agent/tests/test_session_state.py` | SessionUserdata unit tests |
| `agent/tests/test_guardrail.py` | Guardrail check/rewrite unit tests |
| `agent/tests/test_orchestrator_routing.py` | Routing logic unit tests |

## Files to Modify

| File | Change |
|---|---|
| `frontend/package.json` | Add `@playwright/test` devDep + `test:e2e` scripts |
| `frontend/components/StudentRoom.tsx` | Import + render `<SuggestedQuestions />` |
| `agent/pyproject.toml` | Add `pytest-mock` to dev-dependencies |
| `agent/services/langfuse_setup.py` | Add `create_session_trace()` + OTEL attribute helpers |
| `agent/main.py` | Enrich `on_conversation_item` spans with student/session/subject attrs |
| `agent/agents/orchestrator.py` | Enrich routing spans with `question_summary` and `previous_subject` |

## Files unchanged
- `agent/models/session_state.py` — tested but not modified
- `agent/services/guardrail.py` — tested but not modified
- `frontend/app/student/page.tsx` — unchanged (StudentRoom handles hints panel)

---

## Curated Sample Questions (canonical list for both hints panel and /demo page)

```ts
export const SAMPLE_QUESTIONS = {
  math: [
    "What is 7 times 8?",
    "Can you explain what a fraction is?",
    "How do I find the area of a circle?",
    "What is the Pythagorean theorem?",
  ],
  english: [
    "What is an adjective?",
    "What's the difference between their, there, and they're?",
    "Can you help me write a better sentence?",
    "What is alliteration?",
  ],
  history: [
    "Who was Julius Caesar?",
    "What caused World War One?",
    "Tell me about the Egyptian pyramids",
    "What was the Industrial Revolution?",
  ],
  escalation: [
    "I'm really confused and upset, nothing makes sense",
    "I don't understand anything at all and I feel like giving up",
  ],
  edge: [
    "What's for lunch today?",
    "What fraction of Roman soldiers were cavalry?",
  ],
} as const;
```

This will live in `frontend/lib/sample-questions.ts` and be imported by both `SuggestedQuestions.tsx` and `app/demo/page.tsx`.

---

## Verification

### Playwright
```bash
cd frontend && npx playwright install --with-deps
npm run test:e2e          # headless
npm run test:e2e:ui       # interactive UI
```
All tests pass without the full Docker stack (token API test needs `next dev` running).

### Pytest
```bash
cd agent && uv run pytest tests/ -v
```
All tests pass without Docker/external services (all external calls mocked).

### Manual walkthrough
1. `docker compose up`
2. Open `http://localhost:3000/demo` → follow scenario checklist
3. In parallel tab: `http://localhost:3000/student?name=Tester`
4. Work through all 4 scenarios; check progress tracker advances
5. Open `http://localhost:3001` (Langfuse) → filter traces by `student.name = Tester`
6. Add manual scores to response spans to validate quality

### Hints panel
- On `/student` page with no conversation yet: hints panel visible
- After first agent response (`turns.length > 0`): panel auto-collapses
