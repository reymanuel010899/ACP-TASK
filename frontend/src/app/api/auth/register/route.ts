// POST /api/auth/register -- BFF proxy for the Registry's `POST
// /auth/register` (see `registry/app.py::RegistryService.register_user` /
// the `elif segments == ["auth", "register"]` branch in `do_POST`).
//
// Unlike the pure byte-forwarding proxies (`/api/auth/login`, the `GET` half
// of `/api/vault/keyring`), this route must parse the JSON body rather than
// forward it untouched: it injects `public_key: principal_id` before
// forwarding to the Registry. In this MVP the `principal_id` IS the public
// key (per `libs/session.py`'s own convention), and
// `registry/user_index.py::get_public_key` resolves a value stored
// SEPARATELY at registration time -- it is never derived automatically from
// `principal_id`. Sending `public_key` explicitly now costs nothing and
// avoids a backfill migration if `require_signatures` is ever turned on
// later, since `RequestAuthenticator` fails closed for any principal with
// no resolvable public key. If the body isn't a JSON object (or
// `principal_id` isn't a usable string), the payload is forwarded
// unmodified so the Registry's own validation produces its own accurate
// 422 (`registry/app.py::register_user`), rather than this route trying to
// duplicate that validation logic and risk drifting from it.
//
// The Registry's response body/status are otherwise forwarded back
// unchanged (404s, 422s, etc. -- error-passthrough shape mirroring
// `web/app.py::_handle_auth_register`), EXCEPT for 409 (duplicate
// `principal_id`), which gets a distinct, friendlier `{error: string}`
// message here instead of the Registry's raw "principal already
// registered". `principal_id` is client-generated (a fresh keypair per
// registration attempt, see U7), so a genuine collision is vanishingly
// rare -- this 409 case is almost always the client's own prior attempt
// having already landed (KTD5), which U7's resume-in-place logic handles
// by treating it as success-continue, not a collision. The rare true
// collision still needs an actionable message telling the user to retry
// (which mints a fresh identity client-side), rather than a raw backend
// string that reads like a login-style "already have an account" error.
//
// No request signing: this deployment's Registry runs with
// `require_signatures=False` by default (see the plan's U3 Approach).

import { getRegistryUrl } from "@/lib/backendConfig";

export async function POST(request: Request): Promise<Response> {
  const rawBody = await request.text();

  let payload: unknown;
  try {
    payload = rawBody ? JSON.parse(rawBody) : {};
  } catch (err) {
    return jsonError(
      400,
      `invalid JSON body: ${err instanceof Error ? err.message : String(err)}`,
    );
  }

  let forwardBody: string;
  if (typeof payload === "object" && payload !== null && !Array.isArray(payload)) {
    const augmented: Record<string, unknown> = { ...(payload as Record<string, unknown>) };
    const principalId = augmented.principal_id;
    if (typeof principalId === "string" && principalId) {
      augmented.public_key = principalId;
    }
    forwardBody = JSON.stringify(augmented);
  } else {
    // Not a JSON object -- forward as received and let the Registry's own
    // "request body must be a JSON object" validation handle it.
    forwardBody = rawBody;
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${getRegistryUrl()}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: forwardBody,
    });
  } catch (err) {
    return jsonError(
      502,
      `Registry did not respond: ${err instanceof Error ? err.message : String(err)}`,
    );
  }

  if (upstream.status === 409) {
    // Drain the Registry's own response body without forwarding it -- a
    // distinct, actionable message replaces it (see file header).
    await upstream.arrayBuffer();
    return jsonError(
      409,
      "This identity could not be registered because it already exists. Please try registering again.",
    );
  }

  const responseBody = await upstream.arrayBuffer();
  return new Response(responseBody, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "application/json",
    },
  });
}

function jsonError(status: number, message: string): Response {
  return Response.json({ error: message }, { status });
}
