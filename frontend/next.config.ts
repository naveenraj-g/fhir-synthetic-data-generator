import type { NextConfig } from "next";

// Where the FastAPI backend lives. Browser code only ever calls /backend/*, which is proxied here.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // The Docker image builds a self-contained server (`.next/standalone`) so it does not need node_modules at run time.
  // Opt-in, because `next start` does not work with this output and `pnpm start` should keep working.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  // Lets the dev server be opened as http://127.0.0.1:3000 as well as localhost (handy when a browser profile is stuck on one).
  allowedDevOrigins: ["127.0.0.1"],
  // The API has routes with a trailing slash (POST /generations/). Without this, Next redirects them to the slashless
  // form and FastAPI then redirects back to its own origin, which the browser blocks.
  skipTrailingSlashRedirect: true,
  // The default proxy timeout is 30 s, after which Next drops the connection ("socket hang up") even though the API is
  // still working. Real Synthea runs routinely take longer, so allow 10 minutes for any call that waits on the API.
  experimental: { proxyTimeout: 600_000 },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    // Order matters: the trailing-slash rule must come first so "/backend/x/" is forwarded as "x/", not "x".
    return [
      { source: "/backend/:path*/", destination: `${BACKEND_URL}/:path*/` },
      { source: "/backend/:path*", destination: `${BACKEND_URL}/:path*` },
    ];
  },
};

export default nextConfig;
