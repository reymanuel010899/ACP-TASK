"""Minimal HTTP ingestion surface for signed Twilio form callbacks."""

import hashlib
import json
import argparse
import os
from dataclasses import dataclass
from typing import Optional
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

from libs.twilio_signature import validate_twilio_signature


OPT_OUT = frozenset({"stop", "stopall", "unsubscribe", "cancel", "end", "quit"})


@dataclass(frozen=True)
class ExternalCallerPrincipal:
    principal_id: str
    kind: str = "external_caller"


@dataclass(frozen=True)
class InboundVoiceResult:
    state: str
    twiml: str
    tenant_id: Optional[str]
    principal: Optional[ExternalCallerPrincipal]
    capability_projection: frozenset
    transfer_only: bool = False


class InboundVoiceService:
    """Resolve an inbound number without ever falling through to a tenant."""

    VOICE_PROJECTION = frozenset({"public.lookup", "transfer.request", "suppression.create"})

    def __init__(self, identity_owner_resolver, public_corpus_resolver=None,
                 suppression_writer=None, activity_writer=None, emergency_stop=None):
        self.identity_owner_resolver = identity_owner_resolver
        self.public_corpus_resolver = public_corpus_resolver or (lambda _tenant: "")
        self.suppression_writer = suppression_writer
        self.activity_writer = activity_writer
        self.emergency_stop = emergency_stop or (lambda _tenant: False)

    def answer(self, form, event_time=None):
        called, caller = form.get("To"), form.get("From")
        tenant_id = self.identity_owner_resolver(called, event_time) if called else None
        if not tenant_id:
            return InboundVoiceResult(
                "unrouted", _twiml_say("We cannot route your call. Please verify the number and try again."),
                None, None, frozenset(),
            )
        principal = ExternalCallerPrincipal("external-caller:%s" % (caller or "anonymous"))
        if self.emergency_stop(tenant_id):
            return InboundVoiceResult(
                "agent_unavailable", _twiml_say("Our automated assistant is unavailable. We will transfer you to a person."),
                tenant_id, principal, frozenset({"transfer.request"}), True,
            )
        # Corpus is resolved here only to establish the tenant boundary. It is
        # supplied to the bridge through a separately signed session ticket;
        # contact storage is never queried or projected.
        self.public_corpus_resolver(tenant_id)
        return InboundVoiceResult(
            "disclosure_pending", _twiml_say("This call uses an AI assistant. Recording, if enabled, starts only after your consent."),
            tenant_id, principal, self.VOICE_PROJECTION,
        )

    def spoken_stop(self, tenant_id, caller):
        if self.suppression_writer:
            self.suppression_writer(tenant_id=tenant_id, address=caller, channel="voice",
                                    source="spoken_request", restrictive=True)

    def record_unknown_activity(self, tenant_id, call_sid, details):
        if self.activity_writer:
            self.activity_writer(tenant_id=tenant_id, branch_id="unfiled", contact_id=None,
                                 provider_id=call_sid, details=details)


def _twiml_say(message):
    from xml.sax.saxutils import escape
    return '<?xml version="1.0" encoding="UTF-8"?><Response><Say>%s</Say><Hangup/></Response>' % escape(message)


class TwilioWebhookProcessor:
    def __init__(self, events, token_codec, auth_token_resolver,
                 identity_owner_resolver=None, suppression_writer=None,
                 session_window_writer=None):
        self.events = events
        self.token_codec = token_codec
        self.auth_token_resolver = auth_token_resolver
        self.identity_owner_resolver = identity_owner_resolver
        self.suppression_writer = suppression_writer
        self.session_window_writer = session_window_writer

    def process(self, exact_url, signature, form_pairs):
        form = dict(form_pairs)
        token = form.get("AcpToken") or _query_value(exact_url, "token")
        correlation = self.token_codec.decode(token) if token else None
        identity = form.get("To") or form.get("From") or (
            correlation or {}
        ).get("identity_address")
        tenant_id = (correlation or {}).get("tenant_id")
        event_time = form.get("Timestamp")
        if not tenant_id and self.identity_owner_resolver:
            tenant_id = self.identity_owner_resolver(identity, event_time)
        if not tenant_id or not identity:
            return 404, {"error": "identity_not_attributable"}
        auth_token = self.auth_token_resolver(tenant_id, identity)
        if not validate_twilio_signature(auth_token, signature, exact_url, form_pairs):
            return 403, {"error": "invalid_signature"}
        provider_id = form.get("MessageSid") or form.get("CallSid")
        effect_id = (correlation or {}).get("effect_id")
        status = form.get("MessageStatus") or form.get("CallStatus")
        event_type = "status" if status else "inbound_message"
        stable = form.get("EventSid") or provider_id or hashlib.sha256(
            json.dumps(form_pairs, sort_keys=True).encode()
        ).hexdigest()
        event_key = "%s:%s:%s" % (stable, event_type, status or "received")
        inserted = self.events.record(
            tenant_id, event_key, effect_id, identity, event_type, form,
            provider_id=provider_id, status=status,
        )
        if inserted and event_type == "inbound_message":
            body = (form.get("Body") or "").strip().casefold()
            if body in OPT_OUT and self.suppression_writer:
                self.suppression_writer(
                    tenant_id=tenant_id, address=form.get("From"),
                    channel="whatsapp" if str(form.get("From", "")).startswith("whatsapp:") else "sms",
                    source="twilio_keyword", restrictive=True,
                )
            if self.session_window_writer and str(form.get("From", "")).startswith("whatsapp:"):
                self.session_window_writer(
                    tenant_id=tenant_id, address=form.get("From"),
                    sender=form.get("To"), source_event_key=event_key,
                )
        return 200, {"accepted": True, "duplicate": not inserted}


def _query_value(url, name):
    return dict(parse_qsl(urlsplit(url).query, keep_blank_values=True)).get(name)


def make_handler(processor, public_base_url):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8")
            pairs = parse_qsl(raw, keep_blank_values=True)
            exact_url = public_base_url.rstrip("/") + self.path
            status, body = processor.process(
                exact_url, self.headers.get("X-Twilio-Signature"), pairs
            )
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def serve(processor, public_base_url, host="127.0.0.1", port=8140):
    ThreadingHTTPServer((host, port), make_handler(processor, public_base_url)).serve_forever()


def main():
    from libs.twilio_events import TwilioEventRepository
    from libs.twilio_signature import CallbackTokenCodec

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8140)
    args = parser.parse_args()
    public = os.environ.get("TWILIO_PUBLIC_CALLBACK_BASE")
    secret = os.environ.get("TWILIO_CALLBACK_TOKEN_SECRET")
    if not public or not secret:
        raise RuntimeError(
            "TWILIO_PUBLIC_CALLBACK_BASE and TWILIO_CALLBACK_TOKEN_SECRET are required"
        )
    try:
        credentials = json.loads(
            os.environ.get("TWILIO_WEBHOOK_AUTH_TOKENS_JSON", "{}")
        )
    except ValueError as exc:
        raise RuntimeError("TWILIO_WEBHOOK_AUTH_TOKENS_JSON must be JSON") from exc

    def auth_token(tenant_id, _identity):
        value = credentials.get(tenant_id)
        if not isinstance(value, str) or not value:
            raise PermissionError("webhook authority is unavailable")
        return value

    processor = TwilioWebhookProcessor(
        TwilioEventRepository(
            os.environ.get("TWILIO_EVENT_DATABASE", "tessera-twilio-events.db")
        ),
        CallbackTokenCodec(secret), auth_token,
    )
    serve(processor, public, args.host, args.port)


if __name__ == "__main__":
    main()
