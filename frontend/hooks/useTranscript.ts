/**
 * useTranscript — subscribes to agent transcript via LiveKit data channel.
 *
 * The agent publishes transcript JSON to topic "transcript" on every turn.
 * This hook receives those messages and maintains a typed transcript list.
 *
 * Message schema matches what agent/main.py publishes via
 * ctx.room.local_participant.publish_data().
 */
"use client";

import { useEffect, useState } from "react";
import { useRoomContext } from "@livekit/components-react";
import type { DataPacket_Kind, TranscriptionSegment } from "livekit-client";

export interface TranscriptTurn {
  speaker: string;
  role: "user" | "assistant";
  content: string;
  subject: string | null;
  turn: number;
  session_id: string;
  timestamp: number;
}

export function useTranscript(): TranscriptTurn[] {
  const room = useRoomContext();
  const [turns, setTurns] = useState<TranscriptTurn[]>([]);

  useEffect(() => {
    if (!room) return;

    function onDataReceived(
      payload: Uint8Array,
      _participant?: unknown,
      _kind?: DataPacket_Kind,
      topic?: string
    ) {
      if (topic !== "transcript") return;

      try {
        const text = new TextDecoder().decode(payload);
        const data = JSON.parse(text) as Omit<TranscriptTurn, "timestamp">;
        setTurns((prev) => [
          ...prev,
          { ...data, timestamp: Date.now() },
        ]);
      } catch {
        // Ignore malformed messages
      }
    }

    room.on("dataReceived", onDataReceived);
    return () => {
      room.off("dataReceived", onDataReceived);
    };
  }, [room]);

  // PLAN16: capture English Realtime agent transcript via the Room's transcriptionReceived
  // event. @livekit/components-react already owns the "lk.transcription" text stream
  // handler (registerTextStreamHandler only allows ONE handler per topic — registering
  // a second throws DataStreamError). It re-emits final segments as the standard
  // room "transcriptionReceived" EventEmitter event, which supports multiple listeners.
  // We only capture final segments from remote participants (the English agent).
  useEffect(() => {
    if (!room) return;

    const seen = new Set<string>();

    function onTranscriptionReceived(
      segments: TranscriptionSegment[],
      participant?: unknown,
    ) {
      // Skip local participant (student mic) — only capture agent turns
      if (!participant || participant === room.localParticipant) return;

      const finalSegments = segments.filter(
        (s) => s.final && s.text.trim() && !seen.has(s.id)
      );
      if (finalSegments.length === 0) return;

      finalSegments.forEach((s) => seen.add(s.id));
      const combined = finalSegments.map((s) => s.text).join(" ");

      setTurns((prev) => [
        ...prev,
        {
          speaker: "english",
          role: "assistant" as const,
          content: combined,
          subject: "english",
          turn: 0,
          session_id: "",
          timestamp: Date.now(),
        },
      ]);
    }

    room.on("transcriptionReceived", onTranscriptionReceived);
    return () => {
      room.off("transcriptionReceived", onTranscriptionReceived);
    };
  }, [room]);

  return turns;
}
