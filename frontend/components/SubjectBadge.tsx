"use client";

interface SubjectBadgeProps {
  subject: string | null;
}

const SUBJECT_CONFIG: Record<
  string,
  { label: string; emoji: string; color: string }
> = {
  math: {
    label: "Mathematics",
    emoji: "📐",
    color: "bg-purple-100 text-purple-800 border-purple-200",
  },
  english: {
    label: "English",
    emoji: "📖",
    color: "bg-blue-100 text-blue-800 border-blue-200",
  },
  history: {
    label: "History",
    emoji: "🏛️",
    color: "bg-amber-100 text-amber-800 border-amber-200",
  },
  orchestrator: {
    label: "Routing...",
    emoji: "🔄",
    color: "bg-slate-100 text-slate-600 border-slate-200",
  },
};

export function SubjectBadge({ subject }: SubjectBadgeProps) {
  if (!subject) {
    return (
      <div className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border bg-slate-50 text-slate-400 border-slate-200 text-sm font-medium">
        <span>🎓</span>
        <span>Waiting for question...</span>
      </div>
    );
  }

  const config = SUBJECT_CONFIG[subject] ?? {
    label: subject,
    emoji: "📚",
    color: "bg-green-100 text-green-800 border-green-200",
  };

  return (
    <div
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-sm font-semibold transition-all ${config.color}`}
      aria-label={`Current subject: ${config.label}`}
    >
      <span>{config.emoji}</span>
      <span>{config.label}</span>
    </div>
  );
}
