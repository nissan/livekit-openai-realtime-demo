import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Testing Walkthrough — Learning Voice Agent",
  description: "Guided demo scenarios for testing the Learning Voice Agent",
};

export default function DemoLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
