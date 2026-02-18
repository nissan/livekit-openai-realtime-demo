/**
 * StudentRoom — main voice interaction component.
 *
 * CRITICAL: useVoiceAssistant (used inside AgentStateIndicator and useAgentState)
 * MUST be wrapped in AgentSessionProvider.
 * See PLAN.md Critical Gotchas #9.
 *
 * Architecture:
 *   LiveKitRoom (provides room context)
 *     └── AgentSessionProvider (provides agent state context)
 *           └── StudentRoomInner (uses hooks that depend on both)
 */
"use client";

import { useState } from "react";
import {
  LiveKitRoom,
  AgentSessionProvider,
  VoiceAssistantControlBar,
  RoomAudioRenderer,
} from "@livekit/components-react";
import "@livekit/components-styles";

import { SubjectBadge } from "./SubjectBadge";
import { AgentStateIndicator } from "./AgentStateIndicator";
import { TranscriptPanel } from "./TranscriptPanel";
import { EscalationBanner } from "./EscalationBanner";
import { useTranscript } from "@/hooks/useTranscript";

interface StudentRoomProps {
  token: string;
  livekitUrl: string;
  studentName: string;
}

function StudentRoomInner({ studentName }: { studentName: string }) {
  const [teacherJoined, setTeacherJoined] = useState(false);
  const turns = useTranscript();

  // Derive current subject from latest assistant turn
  const latestSubject =
    [...turns].reverse().find((t) => t.role === "assistant")?.subject ?? null;

  return (
    <div className="flex flex-col h-full gap-4">
      {/* Header */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4 flex items-center justify-between">
        <div>
          <h1 className="font-bold text-slate-800">
            Hi, {studentName}! 👋
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Speak naturally — I&apos;ll route you to the right tutor
          </p>
        </div>
        <SubjectBadge subject={latestSubject} />
      </div>

      {/* Escalation banner (conditionally rendered) */}
      <EscalationBanner onTeacherJoined={() => setTeacherJoined(true)} />

      {/* Transcript */}
      <div className="flex-1 bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
        <div className="p-3 border-b border-slate-100 flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
            Conversation
          </span>
          <span className="text-xs text-slate-300">
            {turns.length} turn{turns.length !== 1 ? "s" : ""}
          </span>
        </div>
        <TranscriptPanel className="h-[calc(100%-44px)]" />
      </div>

      {/* Agent state + controls */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
        <div className="flex items-center justify-between mb-4">
          <AgentStateIndicator />
          {teacherJoined && (
            <span className="text-xs text-green-600 font-medium">
              👩‍🏫 Teacher present
            </span>
          )}
        </div>
        {/* LiveKit microphone + mute controls */}
        <VoiceAssistantControlBar />
      </div>

      {/* Render remote audio (agent voice) */}
      <RoomAudioRenderer />
    </div>
  );
}

export function StudentRoom({ token, livekitUrl, studentName }: StudentRoomProps) {
  return (
    <LiveKitRoom
      token={token}
      serverUrl={livekitUrl}
      connect={true}
      audio={true}
      video={false}
      onDisconnected={() => {
        // Could redirect to a session summary page
        console.log("Disconnected from room");
      }}
    >
      {/* AgentSessionProvider REQUIRED for useVoiceAssistant — Gotcha #9 */}
      <AgentSessionProvider>
        <StudentRoomInner studentName={studentName} />
      </AgentSessionProvider>
    </LiveKitRoom>
  );
}
