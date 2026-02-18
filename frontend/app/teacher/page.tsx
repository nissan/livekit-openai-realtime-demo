"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { TeacherRoom } from "@/components/TeacherRoom";
import { ErrorBoundary } from "@/components/ErrorBoundary";

function TeacherPageContent() {
  const searchParams = useSearchParams();
  const name = searchParams.get("name") ?? "Teacher";

  return (
    <ErrorBoundary context="teacher-room">
      <TeacherRoom teacherName={name} />
    </ErrorBoundary>
  );
}

export default function TeacherPage() {
  return (
    <div className="min-h-screen">
      <div className="max-w-2xl mx-auto">
        <Suspense
          fallback={
            <div className="min-h-screen flex items-center justify-center">
              <div className="w-12 h-12 border-4 border-brand-500 border-t-transparent rounded-full animate-spin" />
            </div>
          }
        >
          <TeacherPageContent />
        </Suspense>
      </div>
    </div>
  );
}
