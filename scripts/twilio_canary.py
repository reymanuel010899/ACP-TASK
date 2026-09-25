#!/usr/bin/env python3
"""One-effect Twilio canary restricted to a dedicated test subaccount.

Dry-run is the default. A real effect requires all three independent gates:
``TWILIO_CANARY_ENABLED=true``, ``--execute``, and the exact spend phrase.
Destinations can only come from ``TWILIO_CANARY_VERIFIED_DESTINATIONS_JSON``;
there is intentionally no ``--to`` argument.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from libs.connectors.twilio import TwilioActionExecutor, TwilioCredentialConnector
from agents.orchestrator.voice_definition import VoiceDefinition


CONFIRMATION = "I_UNDERSTAND_THIS_COSTS_MONEY"
FAMILIES = ("sms", "whatsapp", "voice")


def _required(name, env):
    value = env.get(name)
    if not isinstance(value, str) or not value:
        raise RuntimeError("%s is required" % name)
    return value


def _destination(family, env):
    try:
        configured = json.loads(_required("TWILIO_CANARY_VERIFIED_DESTINATIONS_JSON", env))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("verified destinations must be JSON") from exc
    value = configured.get(family) if isinstance(configured, dict) else None
    if not isinstance(value, str) or not value:
        raise RuntimeError("no verified destination is configured for %s" % family)
    return value


def build_payload(family, env, now=None):
    now = int(time.time() if now is None else now)
    destination = _destination(family, env)
    callback = _required("TWILIO_CANARY_STATUS_CALLBACK", env)
    if family == "sms":
        return {"to": destination, "from": _required("TWILIO_CANARY_SMS_FROM", env),
                "status_callback": callback, "body": "Tessera SMS canary %s" % now}
    if family == "whatsapp":
        if env.get("TWILIO_CANARY_WHATSAPP_SESSION_OPEN", "").casefold() != "true":
            raise RuntimeError("WhatsApp canary requires a verified open session window")
        return {"to": destination, "from": _required("TWILIO_CANARY_WHATSAPP_FROM", env),
                "status_callback": callback, "body": "Tessera WhatsApp canary %s" % now}
    definition = {
        "persona_id": "canary", "persona_version": "1",
        "model": _required("TWILIO_CANARY_PINNED_VOICE_MODEL", env), "voice": "eve",
        "opening_script": "This is a Tessera test call. No action is required.",
        "topic_policy_id": "canary-only", "topic_policy_version": "1",
        "maximum_duration_seconds": 30, "transfer_policy_id": "none",
        "transfer_policy_version": "1", "recording": False,
    }
    digest = VoiceDefinition.from_mapping(definition).digest
    return {"to": destination, "from": _required("TWILIO_CANARY_VOICE_FROM", env),
            "status_callback": callback, "twiml_url": _required("TWILIO_CANARY_TWIML_URL", env),
            "maximum_duration_seconds": 30, "ring_timeout_seconds": 15,
            "recording": False, "definition_hash": digest}


def run(family, execute=False, confirmation=None, env=None, connector=None, executor=None):
    env = os.environ if env is None else env
    if family not in FAMILIES:
        raise ValueError("unsupported canary family")
    account = _required("TWILIO_CANARY_ACCOUNT_SID", env)
    dedicated = _required("TWILIO_CANARY_DEDICATED_SUBACCOUNT_SID", env)
    if account != dedicated:
        raise PermissionError("canary account is not the dedicated test subaccount")
    payload = build_payload(family, env)
    result = {"family": family, "mode": "dry-run", "destination": "***" + payload["to"][-4:]}
    if not execute:
        return result
    if env.get("TWILIO_CANARY_ENABLED", "").casefold() != "true" or confirmation != CONFIRMATION:
        raise PermissionError("real canary requires explicit enablement and spend confirmation")
    token = _required("TWILIO_CANARY_AUTH_TOKEN", env)
    connector = connector or TwilioCredentialConnector()
    state = connector.verify_account(account, token)
    required_family = {"sms": "sms:send", "whatsapp": "sms:send", "voice": "voice:call"}[family]
    if state.get("status") != "verified" or required_family not in set(state.get("families") or ()):
        raise PermissionError("dedicated subaccount does not hold the requested family")
    owner = state.get("owner_account_sid")
    if not owner or owner == account:
        raise PermissionError("canary credentials do not identify a Twilio subaccount")
    allowed_senders = {item.get("sender_id") for item in state.get("senders") or () if item.get("enabled")}
    raw_sender = payload["from"].removeprefix("whatsapp:")
    if raw_sender not in allowed_senders:
        raise PermissionError("canary sender is not owned and enabled on the dedicated subaccount")
    capability = {"sms": "twilio.sms.send", "whatsapp": "twilio.whatsapp.freeform.send",
                  "voice": "twilio.voice.call"}[family]
    executor = executor or TwilioActionExecutor()
    receipt = executor.execute(capability, payload, {"account_id": account, "access_token": token})
    return {"family": family, "mode": "executed", "provider_id": receipt["provider_id"],
            "status": receipt["status"], "destination": result["destination"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", required=True, choices=FAMILIES)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-spend")
    args = parser.parse_args(argv)
    try:
        outcome = run(args.family, args.execute, args.confirm_spend)
    except (RuntimeError, PermissionError, ValueError) as exc:
        print("TWILIO_CANARY_REFUSED=" + json.dumps({"error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print("TWILIO_CANARY=" + json.dumps(outcome, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
