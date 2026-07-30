"""One-shot CLI bridge into vault/crypto.py for the U1 cross-language test.

Used by frontend/src/lib/agentCrypto.test.ts to prove agentCrypto.ts's
keyring blob format is byte-compatible with vault/crypto.py, going through
libs/vault_client.py for the "Python builds/unlocks" side exactly as a real
Python client would.

Commands (JSON on stdin, JSON on stdout):
  build  {password, private_key_b64, iterations} -> {blob, dek_b64}
      Builds a keyring blob locally (no network) via
      vault.crypto.build_keyring_blob -- the caller is responsible for
      uploading `blob` to a running Vault itself.
  unlock {password, base_url, principal_id} -> {dek_b64, private_key_b64}
      Fetches the keyring from a running Vault via
      libs.vault_client.VaultClient.fetch_keyring + unlock_keyring, exactly
      as tests/vault/test_credential_storage.py's "other device" does.

Exits non-zero with {"error": "..."} on stdout on failure.
"""

import base64
import json
import os
import sys

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
sys.path.insert(0, REPO_ROOT)

from vault import crypto  # noqa: E402
from libs.vault_client import VaultClient  # noqa: E402


def cmd_build(payload):
    password = payload["password"]
    private_key = base64.b64decode(payload["private_key_b64"])
    iterations = payload["iterations"]
    blob, dek = crypto.build_keyring_blob(
        password, private_key, iterations=iterations
    )
    return {"blob": blob, "dek_b64": base64.b64encode(dek).decode("ascii")}


def cmd_unlock(payload):
    password = payload["password"]
    client = VaultClient(payload["base_url"])
    blob = client.fetch_keyring(payload["principal_id"])
    dek, private_key = client.unlock_keyring(password, blob)
    return {
        "dek_b64": base64.b64encode(dek).decode("ascii"),
        "private_key_b64": base64.b64encode(private_key).decode("ascii"),
    }


COMMANDS = {"build": cmd_build, "unlock": cmd_unlock}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        print(json.dumps({"error": "usage: vault_crypto_bridge.py build|unlock"}))
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
