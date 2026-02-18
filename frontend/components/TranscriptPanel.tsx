"use client";

import { useEffect, useRef } from "react";
import { useTranscript, type TranscriptTurn } from "@/hooks/useTranscript";

const SPEAKER_STYLES: Record<
  string,
  { bg: string; label: string; align: string }
> = {
  student: {
    bg: "bg-brand-100 border-brand-200",
    label: "You",
    align: "ml-auto",
  },
  math: {
    bg: "bg-purple-50 border-purple-200",
    label: "Maths Tutor",
    align: "mr-auto",
  },
  english: {
    bg: "bg-blue-50 border-blue-200",
    label: "English Tutor",
    align: "mr-auto",
  },
  history: {
    bg: "bg-amber-50 border-amber-200",
    label: "History Tutor",
    align: "mr-auto",
  },
  orchestrator: {
    bg: "bg-slate-50 border-slate-200",
    label: "Tutor",
    align: "mr-auto",
  },
  teacher: {
    bg: "bg-green-50 border-green-200",
    label: "Teacher",
    align: "mr-auto",
  },
};

function TurnBubble({ turn }: { turn: TranscriptTurn }) {
  const style = SPEAKER_STYLES[turn.speaker] ?? SPEAKER_STYLES.orchestrator;

  return (
    <div className={`flex flex-col gap-1 max-w-[80%] ${style.align}`}>
      <span className="text-xs text-slate-400 px-1">{style.label}</span>
      <div className={`rounded-2xl border px-4 py-3 text-sm text-slate-700 ${style.bg}`}>
        {turn.content}
      </div>
    </div>
  );
}

interface TranscriptPanelProps {
  className?: string;
}

export function TranscriptPanel({ className = "" }: TranscriptPanelProps) {
  const turns = useTranscript();
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  if (turns.length === 0) {
    return (
      <div
        className={`flex items-center justify-center h-full text-slate-400 text-sm ${className}`}
      >
        Conversation will appear here...
      </div>
    );
  }

  return (
    <div className={`flex flex-col gap-4 overflow-y-auto p-4 ${className}`}>
      {turns.map((turn, i) => (
        <TurnBubble key={`${turn.session_id}-${turn.turn}-${i}`} turn={turn} />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
