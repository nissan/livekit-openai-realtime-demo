# 20 Plans, 13 Services, 4 AI Agents: Lessons from Building a Production Voice Tutoring System

*A technical retrospective for senior engineers, AI researchers, and engineering leaders.*

---

## The Journey

Twenty engineering plans. Thirteen Docker services. Four AI agents. One student asking a maths question at 9pm.

This is the story of building a production voice tutoring system from scratch — iteratively, with real constraints, real failures, and hard-won lessons that no tutorial ever mentions.

The `livekit-openai-realtime-demo` project is an AI-powered tutoring assistant where a student can ask questions about mathematics, history, or English via voice, and be routed to a specialist agent in real time. What began as a proof-of-concept became a case study in the compounding complexity of voice AI systems.

Three things make voice AI qualitatively harder than text AI:

1. **Latency compounds across the pipeline.** VAD → STT → LLM → TTS → WebRTC — each hop adds tens of milliseconds, and a 400ms LLM response that's acceptable in a chat interface is perceptible as unnatural silence in a voice conversation.

2. **Multi-speaker coordination requires explicit timing contracts.** When do you close the pipeline session? When do you let the specialist speak? Getting these timings wrong by 500ms produces audio overlap, double answers, or complete silence.

3. **Child-safety requirements impose a safety layer at every sentence, not every request.** A content moderation check per API call is table stakes. A guardrail that intercepts every sentence before it reaches the TTS engine — that requires a different architectural pattern entirely.

This retrospective documents what we built, what broke, and what we'd do differently.

---

## The Architecture

### Two Sessions, One Room

The system runs two concurrent LiveKit sessions in the same WebRTC room:

```
LiveKit Room (WebRTC)
│
├─ Pipeline Session (learning-orchestrator)
│   ├─ STT: gpt-4o-transcribe
│   ├─ TTS: gpt-4o-mini-tts  (voice varies per agent)
│   ├─ VAD: Silero
│   └─ Agents: OrchestratorAgent → MathAgent ↔ HistoryAgent
│       (all inherit GuardedAgent → tts_node safety pipeline)
│
└─ Realtime Session (learning-english) [dispatched on demand]
    └─ EnglishAgent: gpt-4o-realtime (native speech-to-speech, ~230ms TTFB)
```

The pipeline session handles structured pedagogical interactions. The realtime session handles English conversation practice, where the native audio processing of `gpt-4o-realtime` gives a ~230ms time-to-first-byte advantage over the STT→LLM→TTS chain. This two-session design lets us optimise for different quality axes: structured reasoning vs. conversational fluency.

### The Routing Graph

All four agents can route to each other. The orchestrator classifies intent; specialists handle depth.

```
                    ┌─────────────────────┐
                    │  OrchestratorAgent  │
                    │  Claude Haiku 4.5   │
                    │  (fast routing)     │
                    └──┬────────┬────┬───┘
                       │        │    │
               math    │        │    │ english (dispatch)
                       │  hist  │    │
             ┌─────────▼──┐  ┌──▼───────────┐
             │  MathAgent │  │HistoryAgent  │
             │  Sonnet 4.6│  │  GPT-4o      │
             └──────┬─────┘  └──────┬───────┘
                    │               │
                    └──────↔────────┘
                    direct cross-routing
```

Specialists can route directly to each other — a history question mid-maths session doesn't need an orchestrator round-trip. This is the Mixture-of-Agents pattern (Wang et al., 2024) applied to voice: route to the model best suited to the domain, not the one that happens to be active.

### Model Selection

| Agent | Model | Purpose | Rationale |
|---|---|---|---|
| Orchestrator | Claude Haiku 4.5 | Routing classification | Low cost, < 500ms, consistent at temp=0.1 |
| Math | Claude Sonnet 4.6 | Step-by-step reasoning | Chain-of-thought at scale |
| History | GPT-4o | Factual narrative | Broad knowledge, 128K context |
| English | gpt-4o-realtime | Speech-to-speech | ~230ms TTFB, native audio, no STT→LLM→TTS hop |
| Guardrail check | omni-moderation-latest | Content safety detection | 13 categories, ~5ms, essentially free |
| Guardrail rewrite | Claude Haiku 4.5 | Age-appropriate rewrite | Fast, cheap, system prompt controllable |

The routing classification runs at `temperature=0.1`. Non-deterministic routing is a reliability bug, not a feature. The specialists run at higher temperatures where creative explanation matters.

---

## The Safety Pipeline

Every sentence that any pipeline agent speaks passes through a three-stage guardrail before reaching the TTS engine. This is the `GuardedAgent` base class:

```python
class GuardedAgent(Agent):
    def tts_node(
        self,
        text: AsyncIterable[str],
        model_settings: ModelSettings,
    ) -> AsyncGenerator[rtc.AudioFrame, None]:
        agent = self

        async def _guardrailed_audio():
            session_id = "unknown"
            try:
                session_id = agent.session.userdata.session_id
            except AttributeError:
                pass

            async def _safe_text_stream():
                buffer = ""
                async for chunk in text:
                    buffer += chunk
                    if any(buffer.rstrip().endswith(p) for p in (".", "!", "?", ":", ";")):
                        safe_text = await guardrail_service.check_and_rewrite(
                            buffer,
                            session_id=session_id,
                            agent_name=agent.agent_name,
                        )
                        yield safe_text
                        buffer = ""
                # Flush partial final sentence
                if buffer.strip():
                    yield await guardrail_service.check_and_rewrite(
                        buffer, session_id=session_id, agent_name=agent.agent_name
                    )

            async for frame in Agent.default.tts_node(agent, _safe_text_stream(), model_settings):
                yield frame

        return _guardrailed_audio()
```

The three stages are:

1. **OpenAI `omni-moderation-latest`** — 13 content categories checked in ~5ms. Essentially free. If not flagged, the original text passes through unchanged.
2. **Claude Haiku rewrite** — ~100–150ms for a full age-appropriate rewrite. System prompt instructs it to preserve educational intent, use vocabulary appropriate for ages 8–16, and return only the rewritten text.
3. **Async audit log** — `asyncio.create_task()` fires and forgets the Supabase write. The student hears the rewritten text without waiting for the database write.

The sentence-boundary design is deliberate. Fragment inputs produce unreliable moderation scores — "I hate" and "I hate fractions" score very differently. Waiting for a complete sentence costs 50–200ms of buffer time, which is imperceptible in natural speech but dramatically improves signal quality.

This is the Constitutional AI pattern (Bai et al., 2022) externalised: rather than training harmlessness in, we apply a critic+revise loop at inference time, at sentence granularity.

### Why True-Positive Tests Are Non-Negotiable

Mocks test branching logic. They do not test whether the actual model flags actual harmful content. This integration test is non-optional:

```python
async def test_rewritten_output_passes_moderation(self):
    phrase = "I hate you, you are worthless and stupid."
    rewritten = await check_and_rewrite(
        phrase,
        session_id="integration-test-session",
        agent_name="test-security",
    )
    assert rewritten != phrase
    # The rewrite itself must pass moderation
    follow_up = await check(rewritten)
    assert follow_up.flagged is False
```

This test validates two properties: that the system detects the content, and that its correction does not introduce new problems. A rewriter that turns harassment into veiled harassment would pass a unit test with a mocked moderation API. It would not pass this test.

---

## Observability: Why OTEL Was Non-Negotiable

Langfuse v3 with OpenTelemetry HTTP/protobuf was added in Plan 17 — sixteen plans in. That was sixteen plans too late.

The architecture:
- Each span is created with `tracer.start_as_current_span()` and attributes set inline
- Spans are exported via OTEL HTTP/protobuf to `http://langfuse:3000/api/public/otel/v1/traces`
- Langfuse v3 requires the `langfuse-worker` service to process the BullMQ queue — without it, spans accumulate in Redis and never appear in the UI

Six span categories cover the full session lifecycle:

| Span | Key Attributes |
|---|---|
| `agent.activated` | `agent_name`, `session_id`, `student_identity` |
| `routing.decision` | `from_agent`, `to_agent`, `question_summary`, `decision_ms` |
| `tts.sentence` | `sentence_length`, `guardrail_ms`, `was_rewritten` |
| `guardrail.check` | `text_length`, `flagged`, `highest_score`, `check_ms` |
| `guardrail.rewrite` | `original_length`, `rewritten_length`, `rewrite_ms` |
| `teacher.escalation` | `reason`, `room_name`, `turn_number` |

What traces revealed that unit tests never would: a math agent explaining pronoun usage for 124 tokens during a drain phase — because the conversation history contained an English question from three turns earlier, and the agent was answering it verbatim. The unit test had correct routing. The trace revealed the wrong content.

The latency budget is p50 < 1500ms for `e2e_response_ms` (voice input to first audio frame). Traces make that budget measurable.

---

## Testing at Three Levels

```
           ┌───────────────────────────────────┐
           │       E2E (Playwright)            │  66 tests — UI flows, token API,
           │    chromium + firefox             │  error boundaries
           └──────────────┬────────────────────┘
                          │
           ┌──────────────▼────────────────────┐
           │       Integration Tests           │  16 tests — real LLM/TTS/STT/moderation
           │         (real APIs)               │  skip gracefully if keys absent
           └──────────────┬────────────────────┘
                          │
           ┌──────────────▼────────────────────┐
           │          Unit Tests               │  178 tests — mocked AI APIs
           │         (mocked AI)               │  63-question synthetic routing dataset
           └───────────────────────────────────┘
```

### Synthetic Behavioral Testing (178 unit tests)

The 63-question synthetic dataset in `agent/tests/fixtures/synthetic_questions.py` covers seven categories: math routing (10), history routing (10), English routing (10), specialist off-topic cross-routing (9), escalation signals (6), guardrail inputs by moderation category (13), and ambiguous/multi-subject edge cases (5).

This is the CheckList approach (Ribeiro et al., 2020): test behavioral properties, not implementation details. Adding a new routing rule means adding fixture rows, not new test functions.

### Integration Test Engineering

Integration tests are harder to write correctly than unit tests. Three engineering decisions made them reliable:

1. **Key capture at module load time.** `conftest.py` reads `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` before autouse monkeypatching can shadow them. Tests that need real API access skip gracefully via `pytest.importorskip` when keys are absent.
2. **Singleton reset between tests.** The guardrail module maintains lazy-initialised singletons. Each integration test calls `reset_singletons()` in teardown to prevent state leak.
3. **`pytest-timeout>=2.3.0`.** A test that hangs against a real API is worse than a test that fails. Every integration test has `@pytest.mark.timeout(30)`.

### The 66 Playwright Tests

E2E tests cover the complete student flow: connecting to a room, asking a question, receiving audio, and seeing the transcript update. They also cover error boundaries: what happens when the token API is unreachable, when the room name is invalid, when the browser blocks autoplay.

---

## Ten Lessons from Twenty Plans

### 1. `tts_node` must return `AsyncIterable[rtc.AudioFrame]`, not `AsyncIterable[str]`

LiveKit Agents v1.4 changed the API. Returning strings from `tts_node` produces no error — the agent enters a `Thinking` state and never speaks. Four hours lost.

### 2. Never use `session.interrupt()` unless you want total silence

We called `interrupt()` immediately after dispatching the English agent to clean up the pipeline session. This stopped the orchestrator's handoff sentence mid-word. The student heard half a sentence and then nothing. The fix: wait 3.5 seconds, then call `pipeline_session.aclose()`.

### 3. LLM output is non-deterministic — use counters, not string matching

We tried to detect when a specialist agent had answered a "pending question" by comparing the LLM's reply to the stored question summary. The comparison failed on approximately 30% of sessions. The fix: set `userdata.skip_next_user_turns = 1` and consume it with a counter in `on_conversation_item`.

### 4. Async callbacks in `.on()` are rejected by LiveKit v1.4

The event system expects synchronous callbacks. Passing an `async def` silently drops the event. The fix: schedule with `asyncio.create_task()` inside a synchronous lambda.

### 5. `SessionProvider` crashes before the voice pipeline is ready

`SessionProvider` (from `@livekit/components-react`) accesses `session.room` on render. If the component mounts before the WebRTC connection completes, this throws. The fix: remove `SessionProvider` entirely — `useVoiceAssistant()` reads from `RoomContext` directly and doesn't need the provider.

### 6. `ctx.job.metadata` is not `ctx.room.metadata`

Job metadata and room metadata are separate objects with different lifecycle guarantees. We used the wrong one for session initialisation in three consecutive plans before the distinction became clear.

### 7. macOS Docker + LiveKit requires `rtc.node_ip: 127.0.0.1`

Without this, LiveKit advertises the container-internal IP (`172.17.x.x`) as ICE candidates. The browser receives them and cannot connect. The error message — `could not establish pc connection` — gives no indication that the ICE candidate addresses are wrong.

### 8. Add observability on day one, not plan seventeen

Every trace we examined revealed something that mocks had concealed. Routing decisions, agent activation timing, guardrail latency distribution — none of this is visible in unit test output. The cost of adding OTEL from the start is a few hundred lines of span instrumentation. The cost of adding it in plan seventeen is re-examining every assumption you made in plans one through sixteen.

### 9. True-positive security tests are not optional

A guardrail with 100% unit test coverage and 0% true-positive integration coverage is untested in the dimension that matters most. If the moderation model changes its thresholds, the unit tests will not catch it. The integration tests will.

### 10. `langfuse-worker` is not optional

Langfuse v3 processes OTEL spans via a BullMQ queue in Redis. Without the `langfuse-worker` service, spans arrive, queue in Redis, and never appear in the Langfuse UI. The service is not mentioned prominently in the Langfuse v3 migration guide. This cost three hours of debugging empty dashboards.

---

## Architecture Patterns and Research Context

### Mixture-of-Agents (Wang et al., 2024)

The routing graph instantiates the Mixture-of-Agents pattern: rather than one large model handling all domains, we route to specialised models selected for cost, latency, and quality in their respective domain. Haiku for fast routing decisions; Sonnet for step-by-step mathematical reasoning; GPT-4o for broad historical knowledge.

### Intelligent Tutoring Systems (VanLehn, 2011; Bloom, 1984)

Bloom's 2-sigma finding (1984) established that one-on-one human tutoring produces two standard deviation improvements in student outcomes compared to conventional instruction. VanLehn (2011) quantified the effectiveness of intelligent tutoring systems as 0.76 sigma — significant, but below human tutoring. Voice-native AI tutors narrow this gap by removing the text interface barrier that excludes younger students and slower typists.

### Constitutional AI at Sentence Granularity (Bai et al., 2022)

The guardrail implements the Constitutional AI critic+revise loop at the sentence level. The moderation model acts as the critic; the Haiku rewriter acts as the reviser. The loop runs once per sentence rather than once per session, which means safety is not a coarse filter on complete responses but a continuous constraint on every utterance.

### Turn-Taking (Skantze, 2021)

Skantze's survey of turn-taking in conversational systems identifies timing contracts as the central unsolved problem. Our pipeline handoff timing (3.5s close delay after English dispatch) is an empirical timing contract derived from trial and error, not principled analysis. This is where the field has the most room to grow.

---

## What We Would Do Differently

**Use a state machine for agent lifecycle.** We used ad-hoc boolean flags and integer counters to manage agent transitions. By plan twelve, `SessionUserdata` had seven fields tracking transition state. A formal state machine would have made invalid transitions impossible to represent, not just unlikely to happen.

**Instrument from day one.** Observability is not a logging layer on top of a working system; it is the primary mechanism for understanding what a non-deterministic AI system is actually doing. We added OTEL in plan seventeen. Every insight we gained from traces could have informed plans two through sixteen.

**Write integration tests before unit tests for AI routing.** Unit tests with mocked AI APIs tell you that your branching logic is correct. They do not tell you that the model you're routing with will produce the routing decision you expect. Integration tests with real APIs, run against a small fixture set, catch model-level failures that unit tests structurally cannot.

---

## Conclusion

Twenty plans is not an unusual number for a system of this complexity. It's the actual shape of iterative AI system engineering: each plan revealing constraints that the previous plan exposed, each constraint becoming a design decision, each decision becoming an architectural property that the system now satisfies.

The bugs documented here are not embarrassments — they are the evidence that the system was tested at depth. The latency figures are not performance claims — they are operating constraints the architecture is designed around. The test counts are not vanity metrics — they are the boundary between "we believe this works" and "we can demonstrate that this works."

The specific SDK version gotchas documented here will age. The LiveKit API will change. The Langfuse ingestion architecture will evolve. The lessons about observability from day one, the three-level test pyramid, the true-positive security tests, and the sentence-level safety architecture — those are transferable to any voice AI system, at any scale, in any framework.

---

## References

### Academic Papers

1. Bai, Y. et al. (2022). Constitutional AI: Harmlessness from AI Feedback. *arXiv:2212.08073*. https://arxiv.org/abs/2212.08073

2. Bloom, B. S. (1984). The 2 Sigma Problem: The Search for Methods of Group Instruction as Effective as One-to-One Tutoring. *Educational Researcher*, 13(6), 4–16. https://doi.org/10.3102/0013189X013006004

3. VanLehn, K. (2011). The Relative Effectiveness of Human Tutoring, Intelligent Tutoring Systems, and Other Tutoring Systems. *Educational Psychologist*, 46(4), 197–221. https://doi.org/10.1080/00461520.2011.611369

4. Wang, J. et al. (2024). Mixture-of-Agents Enhances Large Language Model Capabilities. *arXiv:2406.04692*. https://arxiv.org/abs/2406.04692

5. Ribeiro, M. T. et al. (2020). Beyond Accuracy: Behavioral Testing of NLP Models with CheckList. *ACL 2020. arXiv:2005.04118*. https://arxiv.org/abs/2005.04118

6. Skantze, G. (2021). Turn-Taking in Conversational Systems and Human-Robot Interaction: A Review. *Computer Speech & Language*, 67. https://doi.org/10.1016/j.csl.2020.101178

7. Chen, L. et al. (2023). AgentBench: Evaluating LLMs as Agents. *arXiv:2308.03688*. https://arxiv.org/abs/2308.03688

8. Park, J. S. et al. (2023). Generative Agents: Interactive Simulacra of Human Behavior. *arXiv:2304.03442*. https://arxiv.org/abs/2304.03442

9. Shen, Y. et al. (2023). HuggingGPT: Solving AI Tasks with ChatGPT and its Friends in HuggingFace. *arXiv:2303.17580*. https://arxiv.org/abs/2303.17580

10. Dubey, A. et al. (2024). The Llama 3 Herd of Models. *arXiv:2407.21783*. https://arxiv.org/abs/2407.21783

### Industry Standards and Best Practices

11. OpenTelemetry Specification (2023). https://opentelemetry.io/docs/specs/otel/

12. Fowler, M. (2012). TestPyramid. https://martinfowler.com/bliki/TestPyramid.html

13. Cohn, M. (2009). *Succeeding with Agile*. Addison-Wesley. ISBN 0-321-57936-4.

14. W3C (2021). WebRTC 1.0: Real-Time Communication Between Browsers. https://www.w3.org/TR/webrtc/

15. LiveKit Agents Documentation (2024). https://docs.livekit.io/agents/

16. OpenAI Moderation API (2024). https://platform.openai.com/docs/guides/moderation

17. Langfuse OpenTelemetry Integration (2024). https://langfuse.com/docs/integrations/opentelemetry

18. Supabase Row Level Security (2024). https://supabase.com/docs/guides/database/postgres/row-level-security

### Background Reading

19. Wooldridge, M. (2009). *An Introduction to MultiAgent Systems* (2nd ed.). Wiley.

20. Chase, H. (2022). LangChain. https://github.com/langchain-ai/langchain

---

*Source code: https://github.com/nissan/livekit-openai-realtime-demo*

*Plans 1–20 are committed to the repository root as `PLAN.md` through `PLAN20.md` — a full audit trail of every architectural decision.*
