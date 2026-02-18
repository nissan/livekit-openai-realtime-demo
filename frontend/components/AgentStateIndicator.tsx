"use client";

import { useAgentState } from "@/hooks/useAgentState";

const STATE_LABELS: Record<string, string> = {
  initializing: "Connecting...",
  listening: "Listening",
  thinking: "Thinking...",
  speaking: "Speaking",
  disconnected: "Disconnected",
};

const STATE_COLORS: Record<string, string> = {
  initializing: "text-slate-400",
  listening: "text-green-600",
  thinking: "text-amber-600",
  speaking: "text-blue-600",
  disconnected: "text-red-500",
};

export function AgentStateIndicator() {
  const { state, isSpeaking, isListening, isThinking } = useAgentState();

  const isAnimated = isSpeaking || isListening || isThinking;
  const color = STATE_COLORS[state] ?? "text-slate-400";
  const label = STATE_LABELS[state] ?? state;

  return (
    <div className="flex items-center gap-3">
      {/* Waveform animation */}
      <div
        className={`flex items-end gap-[3px] h-6 ${color}`}
        aria-hidden="true"
      >
        {[1, 2, 3, 4, 5].map((i) => (
          <div
            key={i}
            className={`w-1 rounded-full bg-current transition-all duration-300 ${
              isAnimated
                ? `wave-bar`
                : "h-1"
            }`}
            style={
              isAnimated
                ? {
                    height: `${Math.random() * 16 + 8}px`,
                    animationDelay: `${(i - 1) * 0.15}s`,
                  }
                : {}
            }
          />
        ))}
      </div>

      {/* Status label */}
      <span className={`text-sm font-medium ${color}`} role="status">
        {label}
      </span>
    </div>
  );
}
