"""Boots a real registry.app server for the U3 BFF route-handler tests.

Prints a single JSON line {"host": ..., "port": ...} to stdout once the
server is listening, then serves forever until killed (SIGTERM/SIGINT).
Mirrors `vault_test_server.py`, but for the Registry -- so the Next.js
route-handler tests for `/api/auth/login` can drive a real
`registry/app.py::login_user` over HTTP, exactly as the BFF will in
production, rather than against a hand-rolled mock.
"""

import json
import os
import sys

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
sys.path.insert(0, REPO_ROOT)

from registry.app import make_server  # noqa: E402


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
