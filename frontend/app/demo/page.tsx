"use client";

import { useState, useEffect } from "react";
import { SAMPLE_QUESTIONS } from "@/lib/sample-questions";

const STORAGE_KEY = "demo-walkthrough-progress";

interface CheckItem {
  id: string;
  label: string;
  hint?: string;
}

interface Scenario {
  id: string;
  title: string;
  subtitle: string;
  icon: string;
  items: CheckItem[];
}

const SCENARIOS: Scenario[] = [
  {
    id: "routing",
    title: "Scenario 1 — Subject Routing",
    subtitle: "Test that each subject routes correctly",
    icon: "🗺️",
    items: [
      {
        id: "routing-math",
        label: `Say: "${SAMPLE_QUESTIONS.math[0]}"`,
        hint: "SubjectBadge should show 📐 Maths",
      },
      {
        id: "routing-english",
        label: `Say: "${SAMPLE_QUESTIONS.english[0]}"`,
        hint: "SubjectBadge should show 📖 English",
      },
      {
        id: "routing-history",
        label: `Say: "${SAMPLE_QUESTIONS.history[0]}"`,
        hint: "SubjectBadge should show 🏛️ History",
      },
    ],
  },
  {
    id: "multiturn",
    title: "Scenario 2 — Multi-turn Session",
    subtitle: "Test that the agent handles topic switches",
    icon: "🔄",
    items: [
      {
        id: "multiturn-switch",
        label: "Ask a maths question, then ask a history question",
        hint: "SubjectBadge should update from 📐 to 🏛️",
      },
      {
        id: "multiturn-return",
        label: "Return to maths with another maths question",
        hint: "SubjectBadge should switch back to 📐",
      },
    ],
  },
  {
    id: "escalation",
    title: "Scenario 3 — Escalation",
    subtitle: "Test the teacher escalation flow",
    icon: "🆘",
    items: [
      {
        id: "escalation-trigger",
        label: `Say: "${SAMPLE_QUESTIONS.escalation[0]}"`,
        hint: "Agent should escalate to teacher",
      },
      {
        id: "escalation-teacher",
        label: "Check teacher portal at /teacher",
        hint: "Should receive escalation notification",
      },
      {
        id: "escalation-banner",
        label: "Check student session for EscalationBanner",
        hint: "Banner should appear in student view",
      },
    ],
  },
  {
    id: "edge",
    title: "Scenario 4 — Edge Cases",
    subtitle: "Test boundary behaviours",
    icon: "🧪",
    items: [
      {
        id: "edge-offtopic",
        label: `Say: "${SAMPLE_QUESTIONS.edge[0]}"`,
        hint: "Agent should redirect politely to school topics",
      },
      {
        id: "edge-crosssubject",
        label: `Say: "${SAMPLE_QUESTIONS.edge[1]}"`,
        hint: "Routes to math OR history — either is correct",
      },
    ],
  },
];

const TOTAL_ITEMS = SCENARIOS.reduce((sum, s) => sum + s.items.length, 0);

export default function DemoPage() {
  const [checked, setChecked] = useState<Record<string, boolean>>({});

  // Load persisted state
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) setChecked(JSON.parse(stored));
    } catch {
      // ignore
    }
  }, []);

  const toggle = (id: string) => {
    setChecked((prev) => {
      const next = { ...prev, [id]: !prev[id] };
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        // ignore
      }
      return next;
    });
  };

  const resetAll = () => {
    setChecked({});
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  };

  const completedCount = Object.values(checked).filter(Boolean).length;

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 sticky top-0 z-10">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-slate-800">Testing Walkthrough</h1>
            <p className="text-sm text-slate-500 mt-0.5">
              Start a student session in another tab, then work through these scenarios
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-slate-600">
              {completedCount} / {TOTAL_ITEMS} completed
            </span>
            <div
              className="h-2 w-24 bg-slate-200 rounded-full overflow-hidden"
              role="progressbar"
              aria-valuenow={completedCount}
              aria-valuemax={TOTAL_ITEMS}
            >
              <div
                className="h-full bg-green-500 rounded-full transition-all"
                style={{ width: `${(completedCount / TOTAL_ITEMS) * 100}%` }}
              />
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-3xl mx-auto px-6 py-8 space-y-6">
        {/* Quick links */}
        <div className="flex gap-3">
          <a
            href="/student?name=Tester"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
          >
            Open Student Session →
          </a>
          <a
            href="/teacher?name=DemoTeacher"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-4 py-2 bg-slate-700 text-white text-sm font-medium rounded-lg hover:bg-slate-800 transition-colors"
          >
            Open Teacher Portal →
          </a>
          <button
            onClick={resetAll}
            className="ml-auto px-4 py-2 text-sm text-slate-500 hover:text-slate-700 border border-slate-200 rounded-lg hover:border-slate-300 transition-colors"
          >
            Reset progress
          </button>
        </div>

        {/* Scenario cards */}
        {SCENARIOS.map((scenario) => {
          const done = scenario.items.filter((i) => checked[i.id]).length;
          return (
            <div
              key={scenario.id}
              className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden"
            >
              <div className="p-4 border-b border-slate-100 flex items-center gap-3">
                <span className="text-2xl">{scenario.icon}</span>
                <div className="flex-1">
                  <h2 className="font-semibold text-slate-800">{scenario.title}</h2>
                  <p className="text-xs text-slate-400 mt-0.5">{scenario.subtitle}</p>
                </div>
                <span className="text-xs text-slate-400">
                  {done}/{scenario.items.length}
                </span>
              </div>
              <ul className="divide-y divide-slate-50">
                {scenario.items.map((item) => (
                  <li key={item.id}>
                    <label className="flex items-start gap-3 p-4 cursor-pointer hover:bg-slate-50 transition-colors">
                      <input
                        type="checkbox"
                        checked={!!checked[item.id]}
                        onChange={() => toggle(item.id)}
                        className="mt-0.5 h-4 w-4 rounded border-slate-300 text-green-600 focus:ring-green-500"
                      />
                      <div>
                        <span
                          className={`text-sm ${
                            checked[item.id]
                              ? "line-through text-slate-400"
                              : "text-slate-700"
                          }`}
                        >
                          {item.label}
                        </span>
                        {item.hint && (
                          <p className="text-xs text-slate-400 mt-0.5">{item.hint}</p>
                        )}
                      </div>
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}

        {/* Langfuse section */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6">
          <h2 className="font-semibold text-slate-800 mb-3">
            Langfuse Trace Analysis
          </h2>
          <p className="text-sm text-slate-500 mb-4">
            After running scenarios, evaluate response quality in Langfuse:
          </p>
          <ol className="space-y-2 text-sm text-slate-600">
            <li className="flex gap-2">
              <span className="font-mono text-xs bg-slate-100 px-2 py-0.5 rounded text-slate-500 shrink-0">1</span>
              Go to{" "}
              <a
                href="http://localhost:3001"
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:underline"
              >
                http://localhost:3001
              </a>{" "}
              → Traces
            </li>
            <li className="flex gap-2">
              <span className="font-mono text-xs bg-slate-100 px-2 py-0.5 rounded text-slate-500 shrink-0">2</span>
              Filter by <code className="text-xs bg-slate-100 px-1 rounded">user.id = Tester</code> or{" "}
              <code className="text-xs bg-slate-100 px-1 rounded">session.id</code>
            </li>
            <li className="flex gap-2">
              <span className="font-mono text-xs bg-slate-100 px-2 py-0.5 rounded text-slate-500 shrink-0">3</span>
              Click a trace → find the LLM span for the subject agent response
            </li>
            <li className="flex gap-2">
              <span className="font-mono text-xs bg-slate-100 px-2 py-0.5 rounded text-slate-500 shrink-0">4</span>
              Click{" "}
              <strong>&ldquo;Add Score&rdquo;</strong> → set{" "}
              <code className="text-xs bg-slate-100 px-1 rounded">name=&quot;quality&quot;</code>,{" "}
              <code className="text-xs bg-slate-100 px-1 rounded">value=1-5</code> + comment
            </li>
            <li className="flex gap-2">
              <span className="font-mono text-xs bg-slate-100 px-2 py-0.5 rounded text-slate-500 shrink-0">5</span>
              Langfuse Scores dashboard shows distribution per agent
            </li>
          </ol>
        </div>

        {/* Sample questions reference */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6">
          <h2 className="font-semibold text-slate-800 mb-4">Sample Questions Reference</h2>
          <div className="grid grid-cols-3 gap-4">
            {(["math", "english", "history"] as const).map((subject) => {
              const icons = { math: "📐", english: "📖", history: "🏛️" };
              const labels = { math: "Maths", english: "English", history: "History" };
              return (
                <div key={subject}>
                  <p className="text-xs font-semibold text-slate-600 mb-2">
                    {icons[subject]} {labels[subject]}
                  </p>
                  <ul className="space-y-1">
                    {SAMPLE_QUESTIONS[subject].map((q) => (
                      <li key={q} className="text-xs text-slate-500 leading-snug">
                        &ldquo;{q}&rdquo;
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
