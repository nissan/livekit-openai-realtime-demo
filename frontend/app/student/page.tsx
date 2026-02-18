"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { StudentRoom } from "@/components/StudentRoom";

interface TokenResponse {
  token: string;
  roomName: string;
  identity: string;
  livekitUrl: string;
}

function StudentPageContent() {
  const searchParams = useSearchParams();
  const name = searchParams.get("name") ?? "Student";
  const identity = `student-${name.toLowerCase().replace(/\s+/g, "-")}-${Date.now()}`;

  const [tokenData, setTokenData] = useState<TokenResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const roomName = `session-${Date.now()}`;

    fetch(
      `/api/token?identity=${encodeURIComponent(identity)}&name=${encodeURIComponent(name)}&role=student&room=${encodeURIComponent(roomName)}`
    )
      .then((res) => {
        if (!res.ok) throw new Error(`Token request failed: ${res.status}`);
        return res.json() as Promise<TokenResponse>;
      })
      .then(setTokenData)
      .catch((err) => setError(err.message));
  }, [identity, name]);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <div className="bg-red-50 border border-red-200 rounded-2xl p-8 max-w-md text-center">
          <div className="text-3xl mb-4">❌</div>
          <h2 className="font-bold text-red-800 mb-2">Connection Error</h2>
          <p className="text-red-600 text-sm">{error}</p>
          <a
            href="/"
            className="mt-6 inline-block px-6 py-3 bg-red-600 text-white rounded-xl font-semibold hover:bg-red-700 transition-colors"
          >
            Try Again
          </a>
        </div>
      </div>
    );
  }

  if (!tokenData) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-brand-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-slate-500 text-sm">Connecting to your tutor...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen p-4 md:p-8">
      <div className="max-w-2xl mx-auto h-[calc(100vh-4rem)] flex flex-col">
        <StudentRoom
          token={tokenData.token}
          livekitUrl={tokenData.livekitUrl}
          studentName={name}
        />
      </div>
    </div>
  );
}

export default function StudentPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center">
          <div className="w-12 h-12 border-4 border-brand-500 border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <StudentPageContent />
    </Suspense>
  );
}
