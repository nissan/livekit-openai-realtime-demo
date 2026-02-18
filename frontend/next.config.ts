import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output for Docker containerisation
  // Produces a self-contained build that doesn't require node_modules at runtime
  output: "standalone",

  // Allow WebSocket connections to LiveKit
  experimental: {
    serverComponentsExternalPackages: ["livekit-server-sdk"],
  },
};

export default nextConfig;
