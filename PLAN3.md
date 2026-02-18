# Plan: Error Boundary + Log-Error API + Tests

## Context

The student page (`/student`) was crashing silently when `AgentSessionProvider` (renamed to `SessionProvider` in `@livekit/components-react` v2.9.19) caused an import error. The crash was only visible in browser DevTools — no server-side record, no user-visible fallback, no alerting path.

**Goal**: Add a React Error Boundary that (1) shows a graceful fallback UI on any render crash, (2) automatically reports the error to a server-side `/api/log-error` endpoint so errors appear in structured server logs (and eventually in any log aggregator). Add Playwright E2E tests to verify both the boundary and the endpoint.

---

## Files Created

| File | Purpose |
|---|---|
| `frontend/components/ErrorBoundary.tsx` | Reusable React class component — catches render errors, shows fallback UI, POSTs to `/api/log-error` |
| `frontend/app/api/log-error/route.ts` | `POST /api/log-error` — validates body, writes structured JSON to server stderr |
| `frontend/app/test-error-boundary/page.tsx` | Dev-only test page — button triggers a controlled crash; used by Playwright |
| `frontend/tests/e2e/error-boundary.spec.ts` | Playwright tests for boundary fallback UI, retry button, log-error POST interception, and API endpoint validation |

## Files Modified

| File | Change |
|---|---|
| `frontend/app/student/page.tsx` | Wrap `<StudentRoom …/>` with `<ErrorBoundary context="student-room">` |
| `frontend/app/teacher/page.tsx` | Wrap `<TeacherRoom …/>` with `<ErrorBoundary context="teacher-room">` |

---

## Implementation Detail

### 1. `frontend/components/ErrorBoundary.tsx`

React class component (required — hooks cannot catch render errors).

Props:
- `context` — string label sent to `/api/log-error` for filtering in logs (e.g. "student-room", "teacher-room", "test-page")
- `fallback` — optional custom fallback node; defaults to built-in "Something went wrong" UI
- "Try Again" button resets `state.hasError` to `false`, re-rendering children
- `fetch` failure in `componentDidCatch` is swallowed silently (never cascade errors in error handlers)

### 2. `frontend/app/api/log-error/route.ts`

Validation rules (400 responses):
- Missing or non-string `error` field → 400 `{ error: "error field required" }`
- Non-JSON body → 400 `{ error: "Invalid JSON body" }`

200 response: `{ logged: true }`

Structured JSON written to `console.error` (parseable by Datadog, CloudWatch, etc.):
```json
{
  "level": "error",
  "source": "client",
  "error": "...",
  "errorName": "...",
  "componentStack": "...",
  "context": "...",
  "timestamp": "..."
}
```

### 3. `frontend/app/test-error-boundary/page.tsx`

Lightweight test-only page. State toggle causes `CrashingComponent` to throw.
No nav links from main app; only reachable via direct URL (used by Playwright).

### 4. `frontend/tests/e2e/error-boundary.spec.ts`

Seven tests across two `describe` blocks:

**Block 1: Error Boundary UI** (via `/test-error-boundary`)
- shows "Component loaded successfully" before crash
- shows fallback UI ("Something went wrong") after crash
- "Try Again" button resets the boundary back to normal
- boundary triggers POST to /api/log-error (route interception)

**Block 2: /api/log-error endpoint** (direct API tests)
- returns 200 + { logged: true } for valid POST body
- returns 400 for missing error field
- returns 400 for non-JSON body

---

## Verification

### Manual
```bash
# Start frontend
cd frontend && npm run dev

# Open http://localhost:3000/test-error-boundary
# Click "Trigger Error" → boundary fallback appears
# Click "Try Again" → resets to normal
# Check terminal for structured JSON error log

# Confirm /api/log-error POST:
curl -s -X POST http://localhost:3000/api/log-error \
  -H "Content-Type: application/json" \
  -d '{"error":"test","context":"manual"}' | jq .
# Expected: {"logged":true}
```

### Playwright
```bash
cd frontend && npm run test:e2e -- --grep "error-boundary"
# Or run all:
npm run test:e2e
```
Expected: 7 new tests pass (all in error-boundary.spec.ts), existing 25 tests unaffected.

---

## Status: IMPLEMENTED (2026-02-18)
