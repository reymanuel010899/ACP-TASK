"""Tiny stand-in for a provider process, used by test_supervisor.

Serves the agent-card health endpoint (with a trust extension carrying a
principal_id) so the supervisor's health-check flips the agent to ``online``,
and prints a startup line so log capture can be asserted. Runs until killed.
"""

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

CARD = {
    "name": "stub-provider",
    "url": None,
    "capabilities": {
        "streaming": False,
        "extensions": [
            {
                "uri": "https://treessera.com/extensions/trust/v1",
                "params": {"principal_id": "stub-principal-123"},
            }
        ],
    },
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/.well-known/agent-card.json":
            body = json.dumps(CARD).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    print("stub provider up on %d" % args.port, flush=True)
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
