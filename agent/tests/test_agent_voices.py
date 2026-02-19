"""Tests that each agent has a distinct TTS voice configured."""


class TestAgentVoiceConfiguration:
    def test_pipeline_agents_have_unique_voices(self):
        from agent.agents.orchestrator import OrchestratorAgent
        from agent.agents.math_agent import MathAgent
        from agent.agents.history_agent import HistoryAgent

        voices = [OrchestratorAgent.tts_voice, MathAgent.tts_voice, HistoryAgent.tts_voice]
        assert len(voices) == len(set(voices)), (
            "All pipeline agents must have distinct tts_voice values, "
            f"got: {voices}"
        )

    def test_orchestrator_voice(self):
        from agent.agents.orchestrator import OrchestratorAgent
        assert OrchestratorAgent.tts_voice == "alloy"

    def test_math_agent_voice(self):
        from agent.agents.math_agent import MathAgent
        assert MathAgent.tts_voice == "onyx"

    def test_history_agent_voice(self):
        from agent.agents.history_agent import HistoryAgent
        assert HistoryAgent.tts_voice == "fable"
