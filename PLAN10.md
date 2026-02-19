# Plan: Fix Agent Routing Verbosity + Speaker Attribution (PLAN10)

## Context

Three bugs discovered during manual testing of the PLAN9 build, diagnosed via Langfuse trace
`d53874d1fe5dc9f1a61f90d2ab9c3568` (1m 25s, 4 routing decisions):

**Bug 1 — Math agent not shown in transcript for its first response**
Speaker attribution broken: the math tutor's first response shows as "orchestrator" in transcript.

Root cause: PLAN9 set `speaking_agent` in `GuardedAgent.on_enter()`. But LiveKit's
`drain_agent_activity` span fires the first drain-phase response BEFORE `on_enter()` runs.
So `speaking_agent` is still the old agent's name when `conversation_item_added` fires.

Fix: Set `speaking_agent` proactively inside each routing function (`_route_to_math_impl`,
`_route_to_history_impl`, `_route_to_orchestrator_impl`) immediately after `route_to()`,
so the drain-phase response is correctly attributed from the first token.

**Bug 2 — Math agent answered pronoun question instead of routing**
From trace: routing 3 (22:03:23) shows math agent generated **124 tokens about pronouns**
before calling `route_back_to_orchestrator` — clearly an out-of-scope topic for math.

Root cause: System prompt instruction "Acknowledge briefly and call route_back_to_orchestrator"
allows the LLM to generate a full explanation of the off-topic topic. With "acknowledge briefly",
the model interpreted "briefly" as writing 124 tokens about grammar before routing.

LiveKit's async drain mechanism meant the math agent was still active (routing 2 had just
fired 10 seconds before) when the student asked "what is a pronoun". The drain-phase math agent
processed the new question and generated the full pronoun explanation.

Fix: Replace "Acknowledge briefly" with an explicit prohibition: do NOT explain the off-topic
topic AT ALL. Say one brief routing sentence and immediately call the routing function.

**Bug 3 — Agent stopped mid-sentence**
Consequence of Bug 2: two route_back calls fired 10 seconds apart (routing 2 then routing 3).
The orchestrator started a 4-token response that was cut off mid-drain. No separate fix
needed — eliminating Bug 2 eliminates the double-routing that caused Bug 3.

---

## Evidence from Langfuse Trace

| Span | Time | Event | Tokens | Notes |
|------|------|-------|--------|-------|
| routing.decision 1 | 22:02:43 | orchestrator→math | — | Q: "7×8?" |
| agent_turn (math) | 22:02:45 | Math answers 7×8 | 528→105 | 10.15s |
| routing.decision 2 | 22:03:13 | math→orchestrator | — | Q: "Student asked 7×8, answered" |
| **routing.decision 3** | **22:03:23** | **math→orchestrator AGAIN** | **—** | **Q: "Pronouns — outside math scope"** ← BUG |
| routing.decision 4 | 22:03:38 | orchestrator→english | — | Q: "What is a pronoun?" |

The math agent was still in drain from routing 2 when the pronoun question arrived. It generated
124 tokens about grammar before calling route_back a second time.

---

## Files Modified

| File | Change |
|------|--------|
| `agent/tools/routing.py` | Set `userdata.speaking_agent` proactively in each `_route_to_*_impl` |
| `agent/agents/math_agent.py` | Tighten off-topic instruction: prohibit explaining off-topic content |
| `agent/agents/history_agent.py` | Same tightening |
| `agent/tests/test_routing_speaking_agent.py` | New: 3 tests for speaking_agent set by routing functions |

---

## Changes Made

### Step 1 — `agent/tools/routing.py`: Set `speaking_agent` proactively

In each routing function, immediately after `userdata.route_to(...)`:

**`_route_to_math_impl`** — after `userdata.route_to("math")`:
```python
userdata.speaking_agent = "math"   # set before drain-phase response fires (PLAN10)
```

**`_route_to_history_impl`** — after `userdata.route_to("history")`:
```python
userdata.speaking_agent = "history"   # set before drain-phase response fires (PLAN10)
```

**`_route_to_orchestrator_impl`** — after `userdata.route_to("orchestrator")`:
```python
userdata.speaking_agent = "orchestrator"   # set before drain-phase response fires (PLAN10)
```

### Step 2 — `agent/agents/math_agent.py`: Prohibit off-topic explanations

Replaced:
```
"If the student asks about history, English, or anything outside mathematics, "
"do NOT attempt to answer. Acknowledge briefly and call route_back_to_orchestrator "
"so the main tutor can route to the correct specialist."
```

With:
```
"If the student asks about history, English, or ANYTHING outside mathematics: "
"do NOT explain or describe the off-topic topic at all. "
"Say exactly one brief sentence like 'That sounds like an English question — let me pass you to the right tutor!' "
"then IMMEDIATELY call route_back_to_orchestrator. "
"Do not provide any information about the off-topic subject."
```

### Step 3 — `agent/agents/history_agent.py`: Same tightening

Replaced:
```
"If the student asks about mathematics, English, or anything outside history, "
"do NOT attempt to answer. Acknowledge briefly and call route_back_to_orchestrator "
"so the main tutor can route to the correct specialist."
```

With:
```
"If the student asks about mathematics, English, or ANYTHING outside history: "
"do NOT explain or describe the off-topic topic at all. "
"Say exactly one brief sentence like 'That sounds like a maths question — let me pass you to the right tutor!' "
"then IMMEDIATELY call route_back_to_orchestrator. "
"Do not provide any information about the off-topic subject."
```

### Step 4 — `agent/tests/test_routing_speaking_agent.py` (new file, 3 tests)

Three tests verifying `speaking_agent` is set proactively by routing functions:
- `test_route_to_math_sets_speaking_agent`
- `test_route_to_history_sets_speaking_agent`
- `test_route_back_to_orchestrator_sets_speaking_agent`

---

## Timing Fix Proof for Bug 1

```
With PLAN9 (broken):
  1. _route_to_math_impl() → route_to("math") → speaking_agent still = "orchestrator"
  2. LiveKit drain_agent_activity begins → math's FIRST response fires
  3. conversation_item_added → speaking_agent="orchestrator" ← WRONG speaker in transcript
  4. MathAgent.on_enter() fires → speaking_agent = "math"  (too late)

With PLAN10 (fixed):
  1. _route_to_math_impl() → route_to("math") → speaking_agent = "math"  ← SET HERE
  2. LiveKit drain_agent_activity begins → math's FIRST response fires
  3. conversation_item_added → speaking_agent="math" ← CORRECT ✅
  4. MathAgent.on_enter() fires → speaking_agent = "math"  (redundant but harmless)
```

---

## System Prompt Fix Proof for Bug 2

```
With PLAN9 (broken):
  Student: "What is a pronoun?" (math still draining from routing 2)
  Math LLM: "Acknowledge briefly" → generates 124 tokens about pronouns → calls route_back
  → routing 3 fires (second route_back) → double routing → orchestrator mid-sentence cutoff

With PLAN10 (fixed):
  Student: "What is a pronoun?" (math still draining from routing 2)
  Math LLM: explicit prohibition → ONE sentence: "That sounds like an English question!"
  Math LLM: → IMMEDIATELY calls route_back_to_orchestrator
  → Single clean route_back → no double routing → no mid-sentence cutoff ✅
```

---

## Net Test Count

| File | Before | Added | After |
|------|--------|-------|-------|
| `test_routing_speaking_agent.py` | 0 | 3 | 3 |
| All other test files | 69 | 0 | 69 |
| **Total** | **69** | **+3** | **72** |

---

## Verification

```bash
# 1. Run all tests — target 72 passing
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v

# 2. Rebuild and restart stack
docker compose down && docker compose up -d --build

# 3. Test session:
#    - Ask "What is seven times eight?" → math tutor answers (speaker = "math" from FIRST response)
#    - Ask "What is a pronoun?" → math gives ONE routing sentence, no pronoun explanation
#    - No double routing, no mid-sentence cutoff
#    - Orchestrator correctly routes to English session

# 4. Verify in Langfuse:
#    - routing.decision spans: exactly ONE route per question (no rapid double-routing)
#    - conversation.item spans: speaking_agent matches the agent that generated each turn
#    - No two routing.decision spans < 15s apart from the same source agent
```
