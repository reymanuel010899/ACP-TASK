// POST /api/agents/verify-connect -> runner: dry-run inspection of an external
// agent URL. Fetches + validates its card and returns the detected name,
// version, principal_id and capabilities so the console can preview what will
// be connected before committing.

import { proxyRunner } from "@/lib/runnerProxy";

export async function POST(request: Request): Promise<Response> {
  const body = await request.text();
  return proxyRunner("/agents/verify-connect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
}
