"use client";
import React from "react";

interface Props {
  children: React.ReactNode;
  context?: string;
  fallback?: React.ReactNode;
  onReset?: () => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    fetch("/api/log-error", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        error: error.message,
        errorName: error.name,
        componentStack: info.componentStack,
        context: this.props.context ?? "unknown",
        timestamp: new Date().toISOString(),
      }),
    }).catch(() => console.error("Failed to report error:", error));
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="min-h-screen flex items-center justify-center p-6">
          <div className="bg-red-50 border border-red-200 rounded-2xl p-8 max-w-md text-center">
            <div className="text-3xl mb-4">⚠️</div>
            <h2 className="font-bold text-red-800 mb-2 text-xl">
              Something went wrong
            </h2>
            {this.state.error && (
              <p className="text-red-600 text-sm mb-4 font-mono break-all">
                {this.state.error.message}
              </p>
            )}
            <button
              onClick={() => {
                this.props.onReset?.();
                this.setState({ hasError: false, error: null });
              }}
              className="px-6 py-3 bg-red-600 text-white rounded-xl font-semibold hover:bg-red-700 transition-colors"
            >
              Try Again
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
