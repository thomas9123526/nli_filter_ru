// Production: static export (out/) served by the Python backend (`python -m nli_viewer serve`).
// Development: `npm run dev` on :3000, /api/* forwarded to the backend (NLI_VIEWER_BACKEND, default :8000).
import { PHASE_DEVELOPMENT_SERVER } from "next/constants.js";

export default function config(phase) {
  const common = { reactStrictMode: true, images: { unoptimized: true } };
  if (phase === PHASE_DEVELOPMENT_SERVER) {
    const backend = process.env.NLI_VIEWER_BACKEND || "http://127.0.0.1:8000";
    return {
      ...common,
      async rewrites() {
        return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
      },
    };
  }
  return { ...common, output: "export", trailingSlash: true };
}
