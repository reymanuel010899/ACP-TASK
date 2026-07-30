// POST /api/auth/login -- BFF proxy for the Registry's `POST /auth/login`
// (see `registry/app.py::RegistryService.login_user` / the
// `elif segments == ["auth", "login"]` branch in `do_POST`).
//
// Byte-forwarding proxy: the request body is forwarded to the Registry
// unchanged (no JSON re-parse/re-serialize round trip), and the Registry's
// response body/status are forwarded back unchanged. This mirrors
// `web/app.py::_handle_auth_login`'s error-passthrough shape (`{error:
// string}`) -- both for genuine Registry error responses (passed through
// verbatim: 404 "principal not found", 422 validation errors, etc.) and for
// the network-failure case (Registry unreachable), which gets a synthesized
// 502 `{error: string}` here just as it does there.
//
// No request signing: this deployment's Registry runs with
// `require_signatures=False` by default, so no `X-AT-*` signed headers are
// added here (see the plan's U3 Approach).

import { getRegistryUrl } from "@/lib/backendConfig";

export async function POST(request: Request): Promise<Response> {
  const body = await request.arrayBuffer();

  let upstream: Response;
  try {
    upstream = await fetch(`${getRegistryUrl()}/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": request.headers.get("content-type") ?? "application/json",
      },
      body,
    });
  } catch (err) {
    return jsonError(
      502,
      `Registry did not respond: ${err instanceof Error ? err.message : String(err)}`,
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
