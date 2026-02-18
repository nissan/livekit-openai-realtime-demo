"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function HomePage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [role, setRole] = useState<"student" | "teacher">("student");

  function handleStart() {
    if (!name.trim()) return;
    const encoded = encodeURIComponent(name.trim());
    if (role === "student") {
      router.push(`/student?name=${encoded}`);
    } else {
      router.push(`/teacher?name=${encoded}`);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <div className="bg-white rounded-2xl shadow-xl p-10 w-full max-w-md">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="text-5xl mb-4">🎓</div>
          <h1 className="text-3xl font-bold text-slate-800 mb-2">
            Learning Tutor
          </h1>
          <p className="text-slate-500 text-sm">
            AI-powered voice tutoring for Maths, English &amp; History
          </p>
        </div>

        {/* Role selector */}
        <div className="flex rounded-xl overflow-hidden border border-slate-200 mb-6">
          <button
            onClick={() => setRole("student")}
            className={`flex-1 py-3 text-sm font-semibold transition-colors ${
              role === "student"
                ? "bg-brand-600 text-white"
                : "bg-white text-slate-600 hover:bg-slate-50"
            }`}
          >
            🎒 Student
          </button>
          <button
            onClick={() => setRole("teacher")}
            className={`flex-1 py-3 text-sm font-semibold transition-colors ${
              role === "teacher"
                ? "bg-brand-600 text-white"
                : "bg-white text-slate-600 hover:bg-slate-50"
            }`}
          >
            📚 Teacher
          </button>
        </div>

        {/* Name input */}
        <div className="mb-6">
          <label
            htmlFor="name"
            className="block text-sm font-medium text-slate-700 mb-2"
          >
            Your name
          </label>
          <input
            id="name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleStart()}
            placeholder={role === "student" ? "e.g. Alex" : "e.g. Ms. Johnson"}
            className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-brand-500 text-slate-800 placeholder-slate-400"
            autoComplete="name"
            autoFocus
          />
        </div>

        {/* CTA */}
        <button
          onClick={handleStart}
          disabled={!name.trim()}
          className="w-full py-4 rounded-xl bg-brand-600 text-white font-bold text-lg hover:bg-brand-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {role === "student" ? "Start Learning →" : "Monitor Sessions →"}
        </button>

        {/* Info */}
        <p className="text-center text-xs text-slate-400 mt-6">
          {role === "student"
            ? "Your session is private and recorded for learning improvement."
            : "Teachers can join student sessions when escalated."}
        </p>
      </div>
    </main>
  );
}
