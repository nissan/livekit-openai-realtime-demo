"use client";
import { useState } from "react";
import { ErrorBoundary } from "@/components/ErrorBoundary";

function CrashingComponent({ shouldCrash }: { shouldCrash: boolean }) {
  if (shouldCrash) throw new Error("Test crash: intentional render error");
  return <p>Component loaded successfully</p>;
}

export default function TestErrorBoundaryPage() {
  const [crashed, setCrashed] = useState(false);
  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold mb-4">Error Boundary Test Page</h1>
      <button
        onClick={() => setCrashed(true)}
        className="px-4 py-2 bg-red-600 text-white rounded-lg mb-6 hover:bg-red-700 transition-colors"
      >
        Trigger Error
      </button>
      <ErrorBoundary context="test-page" onReset={() => setCrashed(false)}>
        <CrashingComponent shouldCrash={crashed} />
      </ErrorBoundary>
    </div>
  );
}
