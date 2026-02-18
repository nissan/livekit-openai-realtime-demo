"""
Root pytest conftest.py — adds the project parent to sys.path so that
`from agent.models.session_state import SessionUserdata` works correctly.

The agent/ directory is the Python package root; its parent must be on sys.path
for `import agent` to resolve.
"""
import sys
import os

# Add livekit-openai-realtime-demo/ (parent of agent/) to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
