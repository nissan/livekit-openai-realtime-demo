# Plan 21: LinkedIn Article — Learning Voice Agent Technical Retrospective

## Status: COMPLETED

## Context

Write a LinkedIn Article (long-form, markdown-formatted, no character limit) that serves as a
technical retrospective and research reference for the `livekit-openai-realtime-demo` project built
across 20 iterative engineering plans. The audience is senior engineers, AI researchers, and
engineering leaders. The article cites relevant academic papers, industry standards, and published
best practices alongside concrete engineering lessons learned.

**Output file**: `LINKEDIN_ARTICLE.md` in the project root.

---

## Article Structure

### Title
```
20 Plans, 13 Services, 4 AI Agents: Lessons from Building a Production Voice Tutoring System
```

### Sections

1. **Opening hook** — Frame the 20-plan journey; three reasons voice AI is harder than text AI
2. **The Architecture** — Two-session design (ASCII diagram), routing graph (ASCII), GuardedAgent
   tts_node code snippet, model selection table
3. **The Safety Pipeline** — Three stages (omni-moderation → Haiku rewrite → async audit),
   sentence-boundary rationale, Constitutional AI connection, true-positive integration test
4. **Observability: Why OTEL Was Non-Negotiable** — Langfuse v3 + OTEL architecture,
   six span categories, latency budget
5. **Testing at Three Levels** — Test pyramid ASCII, synthetic 63-question dataset (PLAN18),
   integration test engineering, true-positive security tests
6. **Ten Lessons from Twenty Plans** — Most time-costly failures (numbered list)
7. **Architecture Patterns and Research Context** — MoA, ITS, Constitutional AI, turn-taking
8. **What We Would Do Differently** — State machine, OTEL from day one, integration before unit
9. **Conclusion** — Iterative AI engineering; transferable lessons
10. **References** — 20 citations: 10 academic, 8 industry, 2 background

---

## Key Source Files Referenced

| File | What it illustrates |
|---|---|
| `agent/agents/base.py:51–114` | GuardedAgent.tts_node — sentence buffering + guardrail |
| `agent/services/guardrail.py:80–230` | Three-stage safety pipeline |
| `agent/tools/routing.py` | Cross-agent routing, skip_next_user_turns, OTEL spans |
| `agent/tests/integration/test_guardrail_security.py` | True-positive security test pattern |
| `agent/tests/fixtures/synthetic_questions.py` | 63-question synthetic routing dataset |

---

## Implementation

1. ✅ Read key source files to verify code snippets
2. ✅ Write `LINKEDIN_ARTICLE.md` to project root
3. ✅ Create `PLAN21.md` (this file) for architect audit trail
4. ✅ Commit with message: `docs: LinkedIn article — 20-plan voice AI retrospective`
5. ✅ Push to GitHub

---

## Verification Criteria

- [x] All code snippets match actual source files
- [x] All 20 references have valid arXiv/DOI/URL links
- [x] ASCII diagrams accurately reflect two-session architecture
- [x] Test counts match current state (178 unit + 16 integration + 66 E2E = 260)
- [x] Word count appropriate for LinkedIn Article (2000–3000 words)

---

## References (20 citations)

### Academic Papers
1. Bai et al. (2022). Constitutional AI. arXiv:2212.08073
2. Bloom (1984). The 2 Sigma Problem. DOI:10.3102/0013189X013006004
3. VanLehn (2011). Relative Effectiveness of Tutoring Systems. DOI:10.1080/00461520.2011.611369
4. Wang et al. (2024). Mixture-of-Agents. arXiv:2406.04692
5. Ribeiro et al. (2020). CheckList. arXiv:2005.04118
6. Skantze (2021). Turn-Taking in Conversational Systems. DOI:10.1016/j.csl.2020.101178
7. Liu et al. (2024). AgentBench. arXiv:2308.03688
8. Park et al. (2023). Generative Agents. arXiv:2304.03442
9. Shen et al. (2023). HuggingGPT. arXiv:2303.17580
10. Dubey et al. (2024). Llama 3. arXiv:2407.21783

### Industry Standards
11. OpenTelemetry Specification (2023)
12. Fowler, M. TestPyramid (2012)
13. Cohn, M. Succeeding with Agile (2009)
14. W3C WebRTC 1.0 (2021)
15. LiveKit Agents Docs (2024)
16. OpenAI Moderation API (2024)
17. Langfuse OTEL Integration (2024)
18. Supabase Row Level Security (2024)

### Background Reading
19. Wooldridge (2009). Introduction to MultiAgent Systems
20. Chase (2022). LangChain
