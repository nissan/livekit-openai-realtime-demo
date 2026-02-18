/**
 * useAgentState — wraps useVoiceAssistant from @livekit/components-react.
 *
 * IMPORTANT: useVoiceAssistant MUST be used inside AgentSessionProvider.
 * See PLAN.md Critical Gotchas #9.
 *
 * AgentState values: "initializing" | "listening" | "thinking" | "speaking"
 */
"use client";

import { useVoiceAssistant } from "@livekit/components-react";

export type AgentStateValue =
  | "initializing"
  | "listening"
  | "thinking"
  | "speaking"
  | "disconnected";

export interface AgentStateResult {
  state: AgentStateValue;
  isInitializing: boolean;
  isListening: boolean;
  isThinking: boolean;
  isSpeaking: boolean;
  isActive: boolean;
}

export function useAgentState(): AgentStateResult {
  const { state } = useVoiceAssistant();

  const agentState = (state ?? "disconnected") as AgentStateValue;

  return {
    state: agentState,
    isInitializing: agentState === "initializing",
    isListening: agentState === "listening",
    isThinking: agentState === "thinking",
    isSpeaking: agentState === "speaking",
    isActive:
      agentState === "listening" ||
      agentState === "thinking" ||
      agentState === "speaking",
  };
}
