// /api/vault/keyring -- BFF proxy for the Vault's `/keyring` endpoints
// (see `vault/app.py`'s `VaultService.get_keyring` / `store_keyring`, and
// the `do_GET` / `do_POST` branches keyed on `segments[0] == "keyring"`).
//
// GET /api/vault/keyring?principal_id=... -- fetch an existing keyring.
//
// `principal_id` is deliberately taken from the QUERY STRING, not a
// `[principalId]` dynamic path segment. `principal_id` is standard
// (non-URL-safe) base64 and contains a literal `/` in roughly half of all
// generated keys. A literal `/` in a path segment breaks both Next.js's
// own route matching AND the Vault's own path router, which splits on
// `/` and expects exactly two segments (`vault/app.py::do_GET`:
// `segments = [unquote(s) for s in parts.path.split("/") if s]`). A query
// parameter sidesteps the ambiguity entirely. This was a P0 bug caught
// during plan review -- treat the query-param design as load-bearing, not
// a style choice.
//
// The `principal_id` is percent-encoded here (server-side, via
// `encodeURIComponent`, which escapes `/` as `%2F`) before being placed
// into the Vault's path segment, so that a `/`-containing principal_id
// round-trips: the Vault's `unquote()` on that single path segment decodes
// `%2F` back to `/`, reconstructing the original id.
//
// Byte-forwarding proxy: the Vault's response body/status are forwarded
// back unchanged, including its 404 for an unknown principal_id on GET and
// its 422s for a malformed `store_keyring` body on POST (never swallowed).
// Network failure (Vault unreachable) is a distinct 502 `{error: string}`,
// mirroring `web/app.py`'s error-passthrough shape.
//
// POST /api/vault/keyring -- store a new user's wrapped keyring
// (`{user_principal_id, encrypted_dek, salt, nonce, kdf, kdf_params,
// encrypted_private_key}`, see `vault/app.py::store_keyring` /
// `_KEYRING_FIELDS`). The request body is forwarded to the Vault
// byte-for-byte (no JSON re-parse/re-serialize round trip, same as
// `/api/auth/login`) -- this route does no field injection, unlike
// `/api/auth/register`, since the Vault needs nothing the client doesn't
// already have (the keyring's contents are produced entirely client-side).
//
// No request signing: this deployment's Vault runs with
// `require_signatures=False` by default (see the plan's U3 Approach).

import { getVaultUrl } from "@/lib/backendConfig";

export async function GET(request: Request): Promise<Response> {
  const { searchParams } = new URL(request.url);
  const principalId = searchParams.get("principal_id");

  if (!principalId) {
    return jsonError(400, "missing 'principal_id' query parameter");
  }

  let upstream: Response;
  try {
    upstream = await fetch(
      `${getVaultUrl()}/keyring/${encodeURIComponent(principalId)}`,
      { method: "GET" },
    );
  } catch (err) {
    return jsonError(
      502,
      `Vault did not respond: ${err instanceof Error ? err.message : String(err)}`,
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

export async function POST(request: Request): Promise<Response> {
  const body = await request.arrayBuffer();

  let upstream: Response;
  try {
    upstream = await fetch(`${getVaultUrl()}/keyring`, {
      method: "POST",
      headers: {
        "Content-Type": request.headers.get("content-type") ?? "application/json",
      },
      body,
    });
  } catch (err) {
    return jsonError(
      502,
      `Vault did not respond: ${err instanceof Error ? err.message : String(err)}`,
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
