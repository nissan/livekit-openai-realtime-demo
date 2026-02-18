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
import type { DataPacket_Kind } from "livekit-client";

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
      _participant: unknown,
      _kind: DataPacket_Kind,
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

  return turns;
}
