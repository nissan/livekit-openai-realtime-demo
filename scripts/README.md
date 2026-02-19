# Scripts

## `evaluate_traces.py` — Langfuse Trace Evaluation (PLAN17 Proposal B)

Queries recent session traces from Langfuse, uses an LLM judge (Claude Sonnet) to
evaluate agent behaviour, and writes quality scores back to Langfuse for dashboard
visibility.

### What it evaluates

| Metric | Description | Target |
|---|---|---|
| `routing_correctness` | Did agent route to correct specialist? (0.0–1.0) | > 0.9 |
| `transcript_completeness` | Fraction of turns with non-empty text content | > 0.95 |
| `safety_escalation` | Was a teacher escalation raised? (0=no, 1=yes) | Monitor |
| `e2e_latency_p50_ms` | Median end-to-end response latency | < 1500ms |
| `e2e_latency_p95_ms` | 95th percentile response latency | < 3500ms |
| `session_coherence` | LLM judge: conversation makes educational sense (0.0–1.0) | > 0.8 |

### Prerequisites

```bash
# Langfuse must be running (Docker Compose stack)
docker compose ps langfuse  # should be "healthy"

# Install evaluation dependencies
uv add langfuse anthropic --directory agent
```

### Running

```bash
# Against local Langfuse (default: http://localhost:3001)
PYTHONPATH=$(pwd) \
ANTHROPIC_API_KEY=sk-ant-... \
uv run --directory agent python scripts/evaluate_traces.py

# Against a specific host, limit to 10 traces
LANGFUSE_HOST=http://localhost:3001 \
LANGFUSE_PUBLIC_KEY=pk-lf-dev \
LANGFUSE_SECRET_KEY=sk-lf-dev \
ANTHROPIC_API_KEY=sk-ant-... \
EVAL_TRACE_LIMIT=10 \
PYTHONPATH=$(pwd) uv run --directory agent python scripts/evaluate_traces.py
```

### Cost estimate

- ~$0.01–0.05 per session evaluated (Claude Sonnet pricing, 2025)
- Each session: 1 coherence judge call + N routing judge calls (1 per routing decision)
- Typical session: 2–3 routing decisions → 3–4 LLM calls → ~$0.02

### When to run

This script requires **real session data** to exist in Langfuse.
It is NOT a blocking CI gate. Recommended schedule:
- Manually after demos or testing sessions
- Nightly via CI if enough real sessions exist
- Before and after major agent code changes to track regression

### Viewing results in Langfuse

1. Open Langfuse UI → http://localhost:3001
2. Navigate to **Traces** → select a session trace
3. Click **Scores** tab to see evaluation metrics
4. Navigate to **Dashboard** → create a chart with metric `routing_correctness`

### Adding custom rubrics

Edit `evaluate_traces.py` and add a new judge function:

```python
async def judge_my_metric(client, span_data: dict) -> tuple[float, str]:
    prompt = "Your rubric prompt here..."
    # ... call client.messages.create ...
    return score, reasoning
```

Then call it in the `evaluate_traces()` main loop and write the score via `lf.score()`.
