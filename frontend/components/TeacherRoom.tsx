/**
 * TeacherRoom — escalation monitoring and session join component.
 *
 * Teachers can join live student sessions when escalated.
 * Uses Supabase Realtime to receive escalation notifications.
 */
"use client";

import { useEffect, useState } from "react";
import {
  LiveKitRoom,
  ParticipantAudioTile,
  RoomAudioRenderer,
  useParticipants,
} from "@livekit/components-react";
import "@livekit/components-styles";
import { createClient } from "@supabase/supabase-js";

interface EscalationEvent {
  id: number;
  session_id: string;
  room_name: string;
  reason: string;
  teacher_token: string;
  created_at: string;
}

interface TeacherRoomProps {
  teacherName: string;
}

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

function ActiveSession({
  escalation,
  onLeave,
}: {
  escalation: EscalationEvent;
  onLeave: () => void;
}) {
  const livekitUrl =
    process.env.NEXT_PUBLIC_LIVEKIT_URL ?? "ws://localhost:7880";

  return (
    <div className="flex flex-col gap-4">
      <div className="bg-green-100 border border-green-300 rounded-xl px-4 py-3">
        <p className="text-sm font-semibold text-green-800">
          🔴 Live Session — {escalation.room_name}
        </p>
        <p className="text-xs text-green-600 mt-1">
          Reason: {escalation.reason}
        </p>
      </div>

      <LiveKitRoom
        token={escalation.teacher_token}
        serverUrl={livekitUrl}
        connect={true}
        audio={true}
        video={false}
      >
        <RoomAudioRenderer />
        <TeacherRoomParticipants />
      </LiveKitRoom>

      <button
        onClick={onLeave}
        className="py-3 rounded-xl bg-red-100 text-red-700 font-semibold hover:bg-red-200 transition-colors"
      >
        Leave Session
      </button>
    </div>
  );
}

function TeacherRoomParticipants() {
  const participants = useParticipants();
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-slate-400 font-medium uppercase tracking-wide">
        Participants ({participants.length})
      </p>
      {participants.map((p) => (
        <div
          key={p.identity}
          className="flex items-center gap-2 bg-white rounded-lg px-3 py-2 border border-slate-100"
        >
          <div className="w-2 h-2 rounded-full bg-green-400" />
          <span className="text-sm text-slate-700">{p.name ?? p.identity}</span>
        </div>
      ))}
    </div>
  );
}

export function TeacherRoom({ teacherName }: TeacherRoomProps) {
  const [escalations, setEscalations] = useState<EscalationEvent[]>([]);
  const [activeEscalation, setActiveEscalation] =
    useState<EscalationEvent | null>(null);

  // Subscribe to Supabase Realtime escalation_events
  useEffect(() => {
    if (!supabaseUrl || !supabaseAnonKey) return;

    const supabase = createClient(supabaseUrl, supabaseAnonKey);

    const channel = supabase
      .channel("escalation-events")
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "escalation_events",
        },
        (payload) => {
          const event = payload.new as EscalationEvent;
          setEscalations((prev) => [event, ...prev]);

          // Show browser notification if permitted
          if ("Notification" in window && Notification.permission === "granted") {
            new Notification("Student needs help!", {
              body: event.reason,
              icon: "/favicon.ico",
            });
          }
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  // Request notification permission
  useEffect(() => {
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
  }, []);

  if (activeEscalation) {
    return (
      <div className="p-6">
        <ActiveSession
          escalation={activeEscalation}
          onLeave={() => setActiveEscalation(null)}
        />
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6 mb-6">
        <h1 className="text-xl font-bold text-slate-800 mb-1">
          Teacher Portal
        </h1>
        <p className="text-sm text-slate-500">
          Welcome, {teacherName}. You&apos;ll receive notifications when
          students need support.
        </p>
      </div>

      {escalations.length === 0 ? (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-12 text-center">
          <div className="text-4xl mb-4">📡</div>
          <p className="text-slate-400 text-sm">
            Monitoring for escalations...
          </p>
          <p className="text-slate-300 text-xs mt-2">
            You&apos;ll be notified here and via browser notification when a
            student needs help.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wide">
            Escalation Requests
          </h2>
          {escalations.map((e) => (
            <div
              key={e.id}
              className="bg-white rounded-2xl shadow-sm border border-amber-200 p-4"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-sm font-semibold text-slate-800">
                    Room: {e.room_name}
                  </p>
                  <p className="text-sm text-slate-600 mt-1">{e.reason}</p>
                  <p className="text-xs text-slate-400 mt-2">
                    {new Date(e.created_at).toLocaleTimeString()}
                  </p>
                </div>
                <button
                  onClick={() => setActiveEscalation(e)}
                  className="flex-shrink-0 px-4 py-2 bg-brand-600 text-white rounded-xl text-sm font-semibold hover:bg-brand-700 transition-colors"
                >
                  Join Session
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
