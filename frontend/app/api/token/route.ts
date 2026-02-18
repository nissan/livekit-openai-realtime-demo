/**
 * LiveKit JWT generation API route.
 *
 * CRITICAL: livekit-server-sdk v2 made toJwt() ASYNC.
 * Always await token.toJwt() — see PLAN.md Critical Gotchas #4.
 *
 * Student tokens trigger agent dispatch via RoomConfiguration + RoomAgentDispatch
 * using typed classes from @livekit/protocol (NOT plain objects — Gotcha #5).
 */
import { NextRequest, NextResponse } from "next/server";
import { AccessToken } from "livekit-server-sdk";
import { RoomAgentDispatch, RoomConfiguration } from "@livekit/protocol";

const API_KEY = process.env.LIVEKIT_API_KEY!;
const API_SECRET = process.env.LIVEKIT_API_SECRET!;

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const identity = searchParams.get("identity");
  const name = searchParams.get("name") ?? identity;
  const role = searchParams.get("role") ?? "student";
  const roomName = searchParams.get("room") ?? `session-${Date.now()}`;

  if (!identity) {
    return NextResponse.json(
      { error: "identity parameter is required" },
      { status: 400 }
    );
  }

  if (!API_KEY || !API_SECRET) {
    console.error("LIVEKIT_API_KEY or LIVEKIT_API_SECRET not configured");
    return NextResponse.json(
      { error: "LiveKit not configured on server" },
      { status: 500 }
    );
  }

  const token = new AccessToken(API_KEY, API_SECRET, {
    identity,
    name: name ?? identity,
    ttl: "2h",
  });

  token.addGrant({
    roomJoin: true,
    room: roomName,
    canPublish: true,
    canSubscribe: true,
    // Teachers get roomAdmin to see all participants and mute if needed
    roomAdmin: role === "teacher",
  });

  // Student tokens trigger pipeline agent dispatch via typed classes (v2 pattern)
  // See PLAN.md: LiveKit Token section
  if (role === "student") {
    token.roomConfig = new RoomConfiguration({
      agents: [
        new RoomAgentDispatch({
          agentName: "learning-orchestrator",
          metadata: JSON.stringify({ student: identity, room: roomName }),
        }),
      ],
    });
  }

  // MUST be awaited — changed to async in livekit-server-sdk v2
  const jwt = await token.toJwt();

  return NextResponse.json({
    token: jwt,
    roomName,
    identity,
    role,
    livekitUrl: process.env.NEXT_PUBLIC_LIVEKIT_URL ?? "ws://localhost:7880",
  });
}
