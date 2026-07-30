"""One-shot CLI bridge into libs/signing.py for the U2 cross-language test.

Used by frontend/src/lib/agentSession.test.ts to prove agentSession.ts's
`buildSessionAssertion` output is byte-compatible with libs/signing.py's
`build_session_assertion`/`verify_session_assertion` -- i.e. that a session
assertion minted in TypeScript verifies against the real Python reference
implementation, not a hand-rolled re-implementation of what Python expects.

Commands (JSON on stdin, JSON on stdout):
  verify    {assertion, principal_public_key_b64, now_ts?} -> {session_public_key}
      Verifies an assertion via libs.signing.verify_session_assertion,
      exactly as a real backend verifier would. Raises (non-zero exit,
      {"error": ...}) on signature mismatch, id mismatch, or expiry.
  constants {} -> {default_session_ttl}
      Returns libs.signing.DEFAULT_SESSION_TTL, so tests read the live
      constant instead of hardcoding 900 from memory.

Exits non-zero with {"error": "..."} on stdout on failure.
"""

import json
import os
import sys

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
sys.path.insert(0, REPO_ROOT)

from libs import signing  # noqa: E402


def cmd_verify(payload):
    assertion = payload["assertion"]
    principal_public_key_b64 = payload["principal_public_key_b64"]
    now_ts = payload.get("now_ts")
    session_public_key = signing.verify_session_assertion(
        assertion, principal_public_key_b64, now_ts=now_ts
    )
    return {"session_public_key": session_public_key}


def cmd_constants(_payload):
    return {"default_session_ttl": signing.DEFAULT_SESSION_TTL}


COMMANDS = {"verify": cmd_verify, "constants": cmd_constants}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        print(json.dumps({"error": "usage: signing_bridge.py verify|constants"}))
        sys.exit(2)
    payload = json.load(sys.stdin)
    try:
        result = COMMANDS[sys.argv[1]](payload)
    except Exception as exc:  # noqa: BLE001 -- surface any failure to the caller
        print(json.dumps({"error": "%s: %s" % (type(exc).__name__, exc)}))
        sys.exit(1)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
