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
import type { DataPacket_Kind, TextStreamHandler } from "livekit-client";

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

  // PLAN16: subscribe to lk.transcription text streams from the English Realtime agent.
  // The conversation_item_added path is broken (forwarded_text="" in SDK) so the
  // data-channel publish_data("transcript") never fires for English turns.
  // The English agent's transcription node pipeline publishes lk.transcription to the
  // room — the frontend (a remote participant) receives it here.
  // NOTE: if conversation_item_added is fixed in a future SDK update we may get
  // duplicate entries — a duplicate is far better than no transcript at all.
  useEffect(() => {
    if (!room) return;

    const handler: TextStreamHandler = async (reader, participantInfo) => {
      try {
        const text = await reader.readAll();
        if (text.trim()) {
          setTurns((prev) => [
            ...prev,
            {
              speaker: "english",
              role: "assistant" as const,
              content: text,
              subject: "english",
              turn: 0,
              session_id: "",
              timestamp: Date.now(),
            },
          ]);
        }
      } catch {
        // Stream closed early (e.g. pipeline closed) — ignore
      }
    };

    room.registerTextStreamHandler("lk.transcription", handler);
    return () => {
      room.unregisterTextStreamHandler("lk.transcription");
    };
  }, [room]);

  return turns;
}
