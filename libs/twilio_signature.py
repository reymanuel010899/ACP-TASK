"""Twilio request signatures and ACP-TASK self-identifying callback tokens."""

import base64
import hashlib
import hmac
import json
import time


def compute_twilio_signature(auth_token, url, params):
    """Compute Twilio's HMAC-SHA1 form-webhook signature.

    ``params`` may be a mapping or a sequence of pairs. A sequence preserves
    repeated form fields, which must all participate in validation.
    """
    if not auth_token or not url:
        raise ValueError("auth token and exact request URL are required")
    pairs = params.items() if hasattr(params, "items") else params
    message = url + "".join(
        "%s%s" % (key, value)
        for key, value in sorted(
            ((str(key), str(value)) for key, value in pairs),
            key=lambda item: (item[0], item[1]),
        )
    )
    digest = hmac.new(
        auth_token.encode("utf-8"), message.encode("utf-8"), hashlib.sha1
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def validate_twilio_signature(auth_token, signature, url, params):
    if not isinstance(signature, str) or not signature:
        return False
    expected = compute_twilio_signature(auth_token, url, params)
    return hmac.compare_digest(expected, signature)


class CallbackTokenCodec:
    """Sign tenant/effect correlation without relying on a Twilio SID."""

    def __init__(self, secret, clock=None):
        if not isinstance(secret, (bytes, str)) or not secret:
            raise ValueError("callback token secret is required")
        self.secret = secret.encode("utf-8") if isinstance(secret, str) else secret
        self.clock = clock or time.time

    def issue(self, tenant_id, effect_id, identity_address, expires_at):
        payload = {
            "tenant_id": tenant_id, "effect_id": effect_id,
            "identity_address": identity_address, "expires_at": int(expires_at),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self.secret, raw, hashlib.sha256).digest()
        return "%s.%s" % (_b64(raw), _b64(signature))

    def decode(self, token):
        try:
            encoded, signed = token.split(".", 1)
            raw, signature = _unb64(encoded), _unb64(signed)
            expected = hmac.new(self.secret, raw, hashlib.sha256).digest()
            if not hmac.compare_digest(expected, signature):
                raise ValueError
            payload = json.loads(raw.decode("utf-8"))
            if int(payload["expires_at"]) < int(self.clock()):
                raise ValueError
            for key in ("tenant_id", "effect_id", "identity_address"):
                if not payload.get(key):
                    raise ValueError
            return payload
        except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("invalid or expired callback token")


def _b64(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
