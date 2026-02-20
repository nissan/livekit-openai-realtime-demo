# Plan 23: Amend LinkedIn Article — POC Framing + Platform Evaluation Criteria

## Context

The article currently presents the project as a production system retrospective. The user clarifies
the actual intent: **this was a deliberate proof-of-concept** to gain first-hand experience building
voice AI + agent-powered applications. OpenAI Realtime and LiveKit were chosen as **accelerators**
(not the only choices). The tutoring domain was picked to exercise specific scenarios: specialist
routing, mixed voice/text agents, child-safety requirements. The goal was to identify and document
the compounding challenges of voice AI — lessons intended to generalise beyond this specific stack.

Two gaps the article currently has:
1. **The POC framing is understated.** "What began as a proof-of-concept" appears once but doesn't
   explain *why* those platforms were chosen, or that the domain was deliberately picked as a
   learning vehicle.
2. **The "What We Would Do Differently" section has no platform evaluation guidance.** The ten
   lessons are SDK-specific gotchas. Readers can't tell which lessons are LiveKit/OpenAI-specific
   and which generalise to DeepGram, ElevenLabs, Anthropic, Gemini, or any future platform.

---

## Changes Required

### Change 1 — Reframe "The Journey" opening (lines 9–13)

**Current paragraph 2:**
> The `livekit-openai-realtime-demo` project is an AI-powered tutoring assistant where a student
> can ask questions about mathematics, history, or English via voice, and be routed to a specialist
> agent in real time. What began as a proof-of-concept became a case study in the compounding
> complexity of voice AI systems.

**Replace with (2 paragraphs):**
> The `livekit-openai-realtime-demo` project was deliberately conceived as a proof-of-concept: a
> structured experiment to gain first-hand experience building a production-grade voice AI and
> agent-powered application. OpenAI Realtime and LiveKit were chosen as **accelerators** — mature
> infrastructure that let us focus on orchestration, safety, and reliability rather than WebRTC
> plumbing. The tutoring domain was selected to exercise the scenarios that matter most in real
> deployments: specialist routing across heterogeneous models, mixed voice-and-text agent sessions,
> and child-safety requirements that most demos never encounter.
>
> The goal was not to ship the best tutoring system — it was to identify the compounding challenges
> of voice AI systems in a controlled domain, surface every failure, and extract lessons that
> generalise beyond this specific stack. What follows is that audit.

---

### Change 2 — Add "Platform Evaluation Criteria" subsection to "What We Would Do Differently"

Add a 4th recommendation after the existing three, before the closing `---`. Title:
**"Evaluate the platform against first principles, not features."**

This section abstracts the ten SDK-specific lessons into six evaluation criteria that apply to any
voice AI platform (DeepGram, ElevenLabs, Anthropic, Gemini Flash, etc.):

**Six criteria (derived from actual pain points):**

| Criterion | First Principle | LiveKit/OpenAI Realtime finding |
|---|---|---|
| **Latency–safety trade-off surface** | Where can you inspect/modify content before it reaches the user? | Native speech-to-speech (gpt-realtime) gives ~230ms TTFB but bypasses sentence-level guardrail; decomposed pipeline (STT→LLM→TTS) adds ~300ms but allows full interception |
| **Event system semantics** | Sync vs async callbacks; single vs multi-subscriber topics | LiveKit v1.4 silently drops async `.on()` callbacks; `lk.transcription` has single-subscriber ownership |
| **Session lifecycle granularity** | Who owns session lifetime — you or the platform? | `session.interrupt()` is all-or-nothing; `aclose()` with a delay was the only fine-grained option |
| **API stability across versions** | How often do types and contracts change without deprecation warnings? | `tts_node` return type changed from `str` to `AudioFrame` in v1.4 with no warning |
| **Observable internals** | Can you attach instrumentation to the platform's internal decisions? | LiveKit emits events you can span; OpenAI Realtime surfaces `conversation_item_added` post-hoc only |
| **Infrastructure transparency** | What deployment assumptions does the platform make? | LiveKit requires explicit `rtc.node_ip` for macOS Docker; without it ICE candidates are silently wrong |

The written form in the article should be prose paragraphs (not a table), referencing the specific
lessons by number where relevant (e.g., "Lesson 1", "Lesson 4"), and explicitly calling out which
insights are LiveKit/OpenAI-specific vs. which are universal across any voice AI stack.

---

## File to Modify

- `LINKEDIN_ARTICLE.md` (project root)
  - Paragraph replacement: lines ~9–13 (The Journey, paragraph 2)
  - New subsection appended to "What We Would Do Differently" before the closing `---` (after line 306)

---

## Exact Edits

### Edit 1 — The Journey paragraph 2

**old_string:**
```
The `livekit-openai-realtime-demo` project is an AI-powered tutoring assistant where a student can ask questions about mathematics, history, or English via voice, and be routed to a specialist agent in real time. What began as a proof-of-concept became a case study in the compounding complexity of voice AI systems.
```

**new_string:**
```
The `livekit-openai-realtime-demo` project was deliberately conceived as a proof-of-concept: a structured experiment to gain first-hand experience building a production-grade voice AI and agent-powered application. OpenAI Realtime and LiveKit were chosen as **accelerators** — mature infrastructure that let us focus on orchestration, safety, and reliability rather than WebRTC plumbing. The tutoring domain was selected because it exercises the scenarios that matter most in real deployments: specialist routing across heterogeneous models, mixed voice-and-text agent sessions, and child-safety requirements that most demos never encounter.

The goal was not to ship the best tutoring system — it was to identify the compounding challenges of voice AI systems in a controlled domain, surface every failure, and extract lessons that generalise beyond this specific stack. What follows is that audit.
```

### Edit 2 — Append to "What We Would Do Differently"

Added 4th recommendation: **"Evaluate the platform against first principles, not features."**

Six numbered criteria:
1. Latency–safety trade-off surface (interception point)
2. Event model semantics (sync/async, single/multi-subscriber)
3. Session lifetime ownership
4. API stability and deprecation discipline
5. Observable internals (instrumentation surface)
6. Infrastructure transparency (deployment assumptions)

---

## Verification

After edits:
- "The Journey" section makes explicit: POC intent, accelerator framing, deliberate domain selection
- "What We Would Do Differently" has 4 recommendations, last one being the platform criteria
- Six numbered criteria are concrete, traceable back to specific lessons by number
- No references need updating (no new citations — criteria are derived from existing lessons)
- Article word count grows by ~500 words (within LinkedIn Article limits)

## Status: COMPLETED

Commit message: `docs: add POC framing and platform evaluation criteria to LinkedIn article`
