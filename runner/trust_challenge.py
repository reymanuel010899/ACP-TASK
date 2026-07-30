"""Signature challenge — proof of key possession for the Verified tier.

Declaring an AgentTrust identity on a card is a *claim*; anyone could paste
another agent's ``principal_id``. This turns the claim into a *proof*: the
verifier sends a fresh nonce, the agent signs it with its private key, and the
verifier checks (a) the returned public key matches the declared
``principal_id`` and (b) the signature is valid. Only then is the agent
``verified``. An agent that can't sign the nonce stays ``basic``.

The agent's ``principal_id`` is cryptographically bound to its public key —
``atp:principal:<label>:<sha256(b64_pubkey)[:16]>`` (see
``agents/provider/agent.py``) — so a copied id can never pass: the attacker
cannot produce a signature for a key whose hash matches the stolen id.
"""

import base64
import hashlib
import json
import secrets
import urllib.error
import urllib.request

import nacl.exceptions
import nacl.signing

_HEADERS = {
    "User-Agent": "AgentTrust-Console/1.0 (trust-challenge)",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def principal_matches_pubkey(principal_id, public_key_b64):
    # type: (str, str) -> bool
    """True if ``public_key_b64`` is the key ``principal_id`` was derived from.

    Supports the agent id format (``atp:principal:<label>:<hash16>`` where
    ``hash16 = sha256(b64_pubkey)[:16]``) and the raw form where the id IS the
    base64 public key (the user-register convention)."""
    if not isinstance(principal_id, str) or not isinstance(public_key_b64, str):
        return False
    digest = hashlib.sha256(public_key_b64.encode("ascii")).hexdigest()[:16]
    if principal_id.endswith(":" + digest):
        return True
    return principal_id == public_key_b64


def verify_signature(public_key_b64, message, signature_b64):
    # type: (str, str, str) -> bool
    try:
        vk = nacl.signing.VerifyKey(base64.b64decode(public_key_b64))
        vk.verify(message.encode("utf-8"), base64.b64decode(signature_b64))
        return True
    except (ValueError, TypeError, nacl.exceptions.BadSignatureError,
            nacl.exceptions.CryptoError):
        return False


def _data_part(result):
    # type: (dict) -> dict
    for part in (result or {}).get("parts") or []:
        if isinstance(part, dict) and part.get("kind") == "data":
            data = part.get("data")
            if isinstance(data, dict):
                return data
    return {}


def prove_identity(callable_url, principal_id, timeout=6.0, nonce=None):
    # type: (str, str, float, str) -> bool
    """Challenge the agent at ``callable_url`` to sign a fresh nonce; return
    True iff it proves it holds the private key for ``principal_id``.

    Any failure — unreachable, wrong shape, mismatched key, bad signature —
    returns False (the agent simply stays ``basic``); it never raises."""
    if not callable_url or not principal_id:
        return False
    nonce = nonce or secrets.token_hex(24)
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": "trust-%s" % secrets.token_hex(6),
        "method": "message/send",
        "params": {"message": {
            "kind": "message",
            "messageId": "msg-%s" % secrets.token_hex(6),
            "role": "user",
            "parts": [{"kind": "data", "data": {"type": "trust.challenge", "nonce": nonce}}],
        }},
    }).encode("utf-8")
    try:
        req = urllib.request.Request(callable_url, data=body, headers=_HEADERS, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            envelope = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False

    proof = _data_part(envelope.get("result") or {})
    if proof.get("type") != "trust.proof":
        return False
    pub = proof.get("public_key")
    sig = proof.get("signature")
    if not isinstance(pub, str) or not isinstance(sig, str):
        return False
    return principal_matches_pubkey(principal_id, pub) and verify_signature(pub, nonce, sig)
