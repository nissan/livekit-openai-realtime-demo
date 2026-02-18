"use client";

import { useEffect, useState } from "react";
import { useParticipants } from "@livekit/components-react";

interface EscalationBannerProps {
  /** Called when a teacher participant joins the room */
  onTeacherJoined?: () => void;
}

export function EscalationBanner({ onTeacherJoined }: EscalationBannerProps) {
  const participants = useParticipants();
  const [teacherPresent, setTeacherPresent] = useState(false);
  const [escalationRequested, setEscalationRequested] = useState(false);

  useEffect(() => {
    // Detect teacher participant by identity prefix
    const hasTeacher = participants.some(
      (p) => p.identity.startsWith("teacher") || p.name?.toLowerCase().includes("teacher")
    );

    if (hasTeacher && !teacherPresent) {
      setTeacherPresent(true);
      onTeacherJoined?.();
    } else if (!hasTeacher) {
      setTeacherPresent(false);
    }
  }, [participants, teacherPresent, onTeacherJoined]);

  // Listen for escalation data channel message from agent
  useEffect(() => {
    // The agent will update escalation state which can be read
    // via the transcript topic — simplistic detection via content
    // A more robust approach would use a dedicated "escalation" topic
    setEscalationRequested(false); // Reset on mount
  }, []);

  if (!teacherPresent && !escalationRequested) {
    return null;
  }

  if (teacherPresent) {
    return (
      <div className="bg-green-100 border border-green-300 rounded-xl px-4 py-3 flex items-center gap-3">
        <span className="text-green-700 text-lg">👩‍🏫</span>
        <div>
          <p className="text-sm font-semibold text-green-800">
            Your teacher has joined
          </p>
          <p className="text-xs text-green-600">
            They can hear and speak with you directly.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-amber-100 border border-amber-300 rounded-xl px-4 py-3 flex items-center gap-3 animate-pulse-slow">
      <span className="text-amber-700 text-lg">⏳</span>
      <div>
        <p className="text-sm font-semibold text-amber-800">
          Connecting you to a teacher
        </p>
        <p className="text-xs text-amber-600">
          Please wait — your teacher has been notified and will join shortly.
        </p>
      </div>
    </div>
  );
}
