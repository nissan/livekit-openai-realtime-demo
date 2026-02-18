/**
 * StudentRoom — main voice interaction component.
 *
 * Architecture:
 *   LiveKitRoom (provides RoomContext + RoomAudioRenderer)
 *     └── ConnectionGuard (waits for Connected + agent participant)
 *           └── StudentRoomInner (uses hooks that depend on room context)
 *
 * NOTE: SessionProvider from @livekit/components-react v2.9.19 crashes on
 * session.room access before the agent voice pipeline is ready — even after
 * the agent participant joins. We bypass it entirely; useVoiceAssistant()
 * reads from RoomContext (provided by LiveKitRoom) directly.
 * VoiceAssistantControlBar is also replaced with TrackToggle for the same
 * reason (it internally calls useVoiceAssistant which was gated behind SessionProvider).
 */
"use client";

import React, { useState } from "react";
import {
  LiveKitRoom,
  RoomAudioRenderer,
  useConnectionState,
  useAudioPlayback,
  TrackToggle,
} from "@livekit/components-react";
import { ConnectionState, Track } from "livekit-client";
import "@livekit/components-styles";

import { SubjectBadge } from "./SubjectBadge";
import { AgentStateIndicator } from "./AgentStateIndicator";
import { TranscriptPanel } from "./TranscriptPanel";
import { EscalationBanner } from "./EscalationBanner";
import { SuggestedQuestions } from "./SuggestedQuestions";
import { useTranscript } from "@/hooks/useTranscript";

interface StudentRoomProps {
  token: string;
  livekitUrl: string;
  studentName: string;
}

function StudentRoomInner({ studentName }: { studentName: string }) {
  const [teacherJoined, setTeacherJoined] = useState(false);
  const turns = useTranscript();
  const { canPlayAudio, startAudio } = useAudioPlayback();

  // Derive current subject from latest assistant turn
  const latestSubject =
    [...turns].reverse().find((t) => t.role === "assistant")?.subject ?? null;

  return (
    <div className="flex flex-col h-full gap-4">
      {/* Audio enable banner — Chrome blocks AudioContext until user gesture */}
      {!canPlayAudio && (
        <button
          onClick={startAudio}
          className="w-full bg-brand-500 hover:bg-brand-600 text-white text-sm font-semibold rounded-xl px-4 py-3 flex items-center justify-center gap-2 transition-colors"
        >
          🔊 Tap here to enable tutor audio
        </button>
      )}

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

      {/* Suggested questions — auto-hides once conversation starts */}
      <SuggestedQuestions visible={turns.length === 0} />

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
        {/* Microphone toggle — TrackToggle works from RoomContext alone */}
        <TrackToggle source={Track.Source.Microphone} className="lk-button" />
      </div>

      {/* Render remote audio (agent voice) */}
      <RoomAudioRenderer />
    </div>
  );
}

/**
 * Guards rendering until the LiveKit room is fully connected.
 * Must be inside LiveKitRoom so useConnectionState() has room context.
 */
function ConnectionGuard({ children }: { children: React.ReactNode }) {
  const connectionState = useConnectionState();

  if (connectionState !== ConnectionState.Connected) {
    return (
      <div className="flex flex-col h-full items-center justify-center gap-4">
        <div className="w-10 h-10 border-4 border-brand-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-slate-500 text-sm">
          {connectionState === ConnectionState.Reconnecting
            ? "Reconnecting..."
            : "Connecting to your tutor..."}
        </p>
      </div>
    );
  }
  return <>{children}</>;
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
      <ConnectionGuard>
        <StudentRoomInner studentName={studentName} />
      </ConnectionGuard>
    </LiveKitRoom>
  );
}
