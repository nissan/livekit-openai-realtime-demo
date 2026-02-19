# Agent worker Dockerfile
# Python 3.11 — livekit-agents v1.4 drops Python 3.9 support (see PLAN.md Gotcha #2)
FROM python:3.11-slim

# Use /workspace/agent so the parent /workspace can be added to PYTHONPATH,
# making `from agent.agents.xxx import ...` resolve correctly.
WORKDIR /workspace/agent

# System deps required by livekit-ffi native library (GLib, audio pipeline)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libglib2.0-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency installation
RUN pip install --no-cache-dir uv

# Copy dependency files first for layer caching
COPY pyproject.toml ./

# Install dependencies
RUN uv pip install --system --no-cache -e .

# Add /workspace to PYTHONPATH so `from agent.agents.xxx` resolves to
# /workspace/agent/agents/xxx — matching the host development import structure.
ENV PYTHONPATH=/workspace

# Download Silero VAD weights at build time to avoid 200MB download on startup
# See PLAN.md: Latency Strategy — Download VAD weights at Docker build time
RUN python -c "from livekit.plugins import silero; import asyncio; asyncio.run(silero.VAD.load())" || true

# Copy source code
COPY . .

# Default: run the pipeline worker (learning-orchestrator)
# Override CMD in docker-compose to run english worker separately if needed
CMD ["python", "main.py", "start"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import livekit.agents; print('ok')" || exit 1
