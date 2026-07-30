"""Boots a real vault.app server for the U1 cross-language round-trip test.

Prints a single JSON line {"host": ..., "port": ...} to stdout once the
server is listening, then serves forever until killed (SIGTERM/SIGINT).
Mirrors the `vault` fixture in tests/vault/test_credential_storage.py, but
run as a standalone process so a Node/Vitest test can drive it over real
HTTP exactly as a browser client eventually will (via the BFF, once U3
exists -- this test predates the BFF, so it talks to Vault directly).
"""

import json
import os
import sys

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
sys.path.insert(0, REPO_ROOT)

from vault.app import make_server  # noqa: E402


def main():
    server = make_server(port=0)
    host, port = server.server_address[:2]
    print(json.dumps({"host": host, "port": port}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
