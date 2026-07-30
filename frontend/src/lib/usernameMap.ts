/**
 * Browser-local `username -> principal_id` mapping (frontend unit U4, per
 * KTD1 in the login/register plan).
 *
 * The backend has no username index at all -- `principal_id` (a base64
 * ed25519 public key) is the only thing the Registry/Vault know how to look
 * up a keyring by. So a returning user who wants to log in with just a
 * username (R2) needs the browser itself to remember which `principal_id`
 * that username maps to, *on this device*. That mapping lives in
 * `localStorage` (not `sessionStorage`): it must outlive a single tab/session
 * so "log in with my username" keeps working after the browser is closed and
 * reopened, and it is safe to persist indefinitely because the value is a
 * public key, not a secret.
 *
 * This module owns the storage key and shape so the read side (this unit,
 * U4's login flow) and the write side (U7's registration flow, a later unit)
 * agree byte-for-byte on both. **U4 only reads this map** -- registration
 * (U7) is what ever writes to it, including any "this username is already
 * mapped to a different principal_id on this device" collision check. Do not
 * add a write helper here until U7 needs one; keeping the write side absent
 * until then is deliberate, not an oversight.
 *
 * Storage shape: a single JSON object at {@link AGENTTRUST_USERNAME_MAP_KEY},
 * flat `{ [username: string]: string }`, mapping the exact username string
 * the user registered with (case-sensitive, no normalization applied by this
 * module) to their base64 `principal_id`. Example:
 *
 * ```json
 * { "alice": "3v9k...principalIdBase64...==", "bob": "Qh2m...==" }
 * ```
 */

/** localStorage key for the username -> principal_id map. Read side: this module (U4). Write side: U7 (registration). */
export const AGENTTRUST_USERNAME_MAP_KEY = "agenttrust-username-map";

export type UsernameMap = Record<string, string>;

function readUsernameMap(): UsernameMap {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(AGENTTRUST_USERNAME_MAP_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return {};
    }
    const map: UsernameMap = {};
    for (const [username, principalId] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof principalId === "string" && principalId.length > 0) {
        map[username] = principalId;
      }
    }
    return map;
  } catch {
    // localStorage unavailable (private mode, corrupted JSON, etc.) --
    // treat as "no mapping known", never throw.
    return {};
  }
}

/**
 * Look up the `principal_id` this device remembers for `username`, or
 * `null` if this device has no record of that username (never registered
 * here, or the mapping was cleared/corrupted). Exact string match --
 * callers are expected to pass an already-trimmed username.
 */
export function lookupPrincipalId(username: string): string | null {
  if (!username) return null;
  const map = readUsernameMap();
  const principalId = map[username];
  return typeof principalId === "string" && principalId.length > 0 ? principalId : null;
}
