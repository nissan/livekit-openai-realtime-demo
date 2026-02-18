import { NextResponse } from "next/server";

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  if (
    !body ||
    typeof body !== "object" ||
    typeof (body as Record<string, unknown>).error !== "string"
  ) {
    return NextResponse.json({ error: "error field required" }, { status: 400 });
  }

  const { error, errorName, componentStack, context, timestamp } =
    body as Record<string, string>;

  console.error(
    JSON.stringify({
      level: "error",
      source: "client",
      error,
      errorName,
      componentStack,
      context,
      timestamp: timestamp ?? new Date().toISOString(),
    })
  );

  return NextResponse.json({ logged: true });
}
