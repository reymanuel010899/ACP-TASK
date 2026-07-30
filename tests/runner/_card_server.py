"""A crypto-real stand-in for an externally hosted agent.

Serves an agent card at /.well-known/agent-card.json and — like a real
AgentTrust agent — answers the signature challenge over A2A ``message/send``,
signing the verifier's nonce with a real ed25519 key whose public key hashes to
the ``principal_id`` it declares. Flags let a test model the failure modes:

- ``with_trust=False`` -> declares no trust extension (plain A2A -> basic).
- ``prove=False``      -> declares the extension but refuses to sign (a claim
                          it cannot back -> basic).
- ``wrong_principal``  -> declares someone else's principal_id (copy attack:
                          it can sign, but the key won't match the id -> basic).
"""

import base64
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import nacl.signing

TRUST_URI = "https://treessera.com/extensions/trust/v1"


def _principal_for(pubkey_b64):
    return "atp:principal:stub:" + hashlib.sha256(pubkey_b64.encode("ascii")).hexdigest()[:16]


class _CardServer:
    def __init__(self, with_trust=True, with_skills=True, prove=True, wrong_principal=False):
        self._with_trust = with_trust
        self._with_skills = with_skills
        self._prove = prove
        self._key = nacl.signing.SigningKey.generate()
        self._pubkey_b64 = base64.b64encode(bytes(self._key.verify_key)).decode("ascii")
        # its true id, or (for the copy-attack test) a stolen one it can't sign for
        self.principal_id = "atp:principal:victim:deadbeefdeadbeef" if wrong_principal else _principal_for(self._pubkey_b64)
        self.httpd = HTTPServer(("127.0.0.1", 0), self._handler())
        self.port = self.httpd.server_address[1]
        self.url = "http://127.0.0.1:%d" % self.port
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def _card(self):
        card = {
            "name": "External Bot",
            "description": "Hosted elsewhere",
            "version": "1.2.3",
            "url": self.url,
            "capabilities": {"extensions": []},
        }
        if self._with_trust:
            card["capabilities"]["extensions"].append(
                {"uri": TRUST_URI, "params": {"principal_id": self.principal_id}}
            )
        if self._with_skills:
            card["skills"] = [{"id": "terraform.generate", "name": "TF"}]
        return card

    def _sign_proof(self, nonce):
        sig = self._key.sign(nonce.encode("utf-8")).signature
        return {
            "type": "trust.proof",
            "principal_id": self.principal_id,
            "public_key": self._pubkey_b64,
            "signature": base64.b64encode(sig).decode("ascii"),
        }

    def _handler(self):
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, status, body):
                raw = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/.well-known/agent-card.json":
                    self._json(200, outer._card())
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                parts = (((body.get("params") or {}).get("message") or {}).get("parts")) or []
                data = next((p.get("data") for p in parts if p.get("kind") == "data"), {}) or {}
                if data.get("type") == "trust.challenge" and outer._prove:
                    result = {"kind": "message", "role": "agent",
                              "parts": [{"kind": "data", "data": outer._sign_proof(data.get("nonce", ""))}]}
                    self._json(200, {"jsonrpc": "2.0", "id": body.get("id"), "result": result})
                else:
                    # a non-proving agent just echoes something unhelpful
                    self._json(200, {"jsonrpc": "2.0", "id": body.get("id"),
                                     "result": {"kind": "message", "role": "agent",
                                                "parts": [{"kind": "text", "text": "ok"}]}})

        return H

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
