"use client";

import { useState } from "react";
import { SAMPLE_QUESTIONS } from "@/lib/sample-questions";

interface SuggestedQuestionsProps {
  visible: boolean;
}

const SUBJECTS = [
  {
    key: "math" as const,
    label: "Maths",
    icon: "📐",
    questions: SAMPLE_QUESTIONS.math,
  },
  {
    key: "english" as const,
    label: "English",
    icon: "📖",
    questions: SAMPLE_QUESTIONS.english,
  },
  {
    key: "history" as const,
    label: "History",
    icon: "🏛️",
    questions: SAMPLE_QUESTIONS.history,
  },
];

export function SuggestedQuestions({ visible }: SuggestedQuestionsProps) {
  const [dismissed, setDismissed] = useState(false);

  if (!visible || dismissed) return null;

  return (
    <div className="bg-amber-50 border border-amber-200 rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-medium text-amber-800">
          💡 Not sure what to ask? Try one of these:
        </p>
        <button
          onClick={() => setDismissed(true)}
          className="text-amber-400 hover:text-amber-600 transition-colors text-lg leading-none"
          aria-label="Dismiss suggestions"
        >
          ×
        </button>
      </div>
      <div className="grid grid-cols-3 gap-3">
        {SUBJECTS.map(({ key, label, icon, questions }) => (
          <div key={key}>
            <p className="text-xs font-semibold text-amber-700 mb-2">
              {icon} {label}
            </p>
            <ul className="space-y-1">
              {questions.map((q) => (
                <li key={q}>
                  <span className="text-xs text-amber-900 leading-snug block cursor-default">
                    {q}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
