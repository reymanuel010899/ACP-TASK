"""Closed Twilio REST adapters for account verification and messaging effects."""

from __future__ import annotations

import re
from urllib.parse import quote

import requests

from libs.connectors.base import (
    ProviderHTTPError,
    ProviderNetworkError,
    StaticCredentialConnector,
    UnsupportedCapabilityError,
)


API_ROOT = "https://api.twilio.com/2010-04-01"
MESSAGING_ROOT = "https://messaging.twilio.com/v1"
_SID = re.compile(r"^AC[0-9a-fA-F]{32}$")


class TwilioAPIError(ProviderHTTPError):
    """A filtered Twilio failure carrying retry and certainty metadata."""

    def __init__(self, status_code, operation, code=None, retry_after=None):
        super().__init__("twilio", status_code, operation)
        self.code = str(code or "twilio_error")
        self.retry_after = retry_after
        self.category = self._category(status_code, self.code)

    @staticmethod
    def _category(status, code):
        if status == 429:
            return "rate_limit"
        if status in (401, 403):
            return "auth"
        if status >= 500:
            return "transient"
        if str(code) in {"21211", "21606", "21610", "21612", "21614"}:
            return "validation"
        return "provider"


class TwilioCredentialConnector(StaticCredentialConnector):
    """Verify one Twilio subaccount and derive its live messaging authority."""

    provider = "twilio"

    def __init__(self, http=None, timeout=10.0, expected_callback_base=None):
        self.http = http or requests
        self.timeout = timeout
        self.expected_callback_base = (
            expected_callback_base.rstrip("/") if expected_callback_base else None
        )

    def scope_catalog(self):
        return {
            "twilio.voice.call": frozenset({"twilio:voice:call"}),
            "twilio.sms.send": frozenset({"twilio:sms:send"}),
            "twilio.whatsapp.freeform.send": frozenset(
                {"twilio:whatsapp:freeform"}
            ),
            "twilio.whatsapp.template.send": frozenset(
                {"twilio:whatsapp:template"}
            ),
        }

    def verify_account(self, account_id, auth_token):
        if not _SID.match(account_id or "") or not auth_token:
            raise ValueError("a Twilio Account SID and auth token are required")
        account = self._request(
            "GET", "%s/Accounts/%s.json" % (API_ROOT, quote(account_id)),
            "account verification", account_id, auth_token,
        )
        status = account.get("status")
        if status != "active":
            return {
                "provider": "twilio", "account_id": account_id,
                "status": "suspended" if status == "suspended" else "unverified",
                "families": [], "senders": [], "templates": [],
            }
        numbers = self._request(
            "GET",
            "%s/Accounts/%s/IncomingPhoneNumbers.json?PageSize=1000"
            % (API_ROOT, quote(account_id)),
            "number enumeration", account_id, auth_token,
        ).get("incoming_phone_numbers", [])
        senders = []
        families = set()
        callback_drift = []
        for item in numbers:
            number = item.get("phone_number")
            capabilities = item.get("capabilities") or {}
            if not number:
                continue
            if capabilities.get("SMS") or capabilities.get("sms"):
                families.add("sms:send")
                senders.append({
                    "sender_id": number, "family": "sms", "countries": [],
                    "enabled": True,
                })
            if capabilities.get("Voice") or capabilities.get("voice"):
                families.add("voice:call")
                senders.append({
                    "sender_id": number, "family": "voice", "countries": [],
                    "enabled": True,
                })
            if self.expected_callback_base:
                for field in ("sms_url", "voice_url"):
                    value = item.get(field)
                    if value and not value.startswith(self.expected_callback_base + "/"):
                        callback_drift.append({"sender_id": number, "field": field})
        return {
            "provider": "twilio", "account_id": account_id,
            "status": "verified", "families": sorted(families),
            "senders": senders, "templates": [],
            "owner_account_sid": account.get("owner_account_sid"),
            "callback_drift": callback_drift,
        }

    def _request(self, method, url, operation, account_id, auth_token, **kwargs):
        try:
            response = self.http.request(
                method, url, auth=(account_id, auth_token),
                timeout=self.timeout, **kwargs
            )
        except requests.RequestException as exc:
            raise ProviderNetworkError("twilio %s network failure" % operation) from exc
        if not 200 <= response.status_code < 300:
            try:
                body = response.json()
            except (TypeError, ValueError, AttributeError):
                body = {}
            raise TwilioAPIError(
                response.status_code, operation, body.get("code"),
                response.headers.get("Retry-After"),
            )
        try:
            body = response.json()
        except (TypeError, ValueError, AttributeError) as exc:
            raise TwilioAPIError(response.status_code, operation) from exc
        if not isinstance(body, dict):
            raise TwilioAPIError(response.status_code, operation)
        return body


class TwilioAccountManager:
    """Provision or bind a customer subaccount and mint its Standard API key."""

    def __init__(self, parent_sid, parent_token, http=None, timeout=10.0):
        self.parent_sid = parent_sid
        self.parent_token = parent_token
        self.http = http or requests
        self.timeout = timeout

    def create_subaccount(self, tenant_id):
        response = self._request(
            "POST", "%s/Accounts.json" % API_ROOT,
            data={"FriendlyName": "ACP-TASK %s" % tenant_id},
        )
        return {"account_sid": response["sid"], "auth_token": response["auth_token"]}

    def mint_standard_key(self, account_sid, account_token, friendly_name):
        try:
            response = self.http.request(
                "POST", "%s/Accounts/%s/Keys.json" % (API_ROOT, quote(account_sid)),
                auth=(account_sid, account_token), timeout=self.timeout,
                data={"FriendlyName": friendly_name},
            )
        except requests.RequestException as exc:
            raise ProviderNetworkError("twilio API key creation network failure") from exc
        if not 200 <= response.status_code < 300:
            raise TwilioAPIError(response.status_code, "API key creation")
        body = response.json()
        return {"api_key_sid": body["sid"], "api_key_secret": body["secret"]}

    def _request(self, method, url, **kwargs):
        try:
            response = self.http.request(
                method, url, auth=(self.parent_sid, self.parent_token),
                timeout=self.timeout, **kwargs
            )
        except requests.RequestException as exc:
            raise ProviderNetworkError("twilio subaccount network failure") from exc
        if not 200 <= response.status_code < 300:
            raise TwilioAPIError(response.status_code, "subaccount creation")
        return response.json()


class TwilioActionExecutor:
    """Literal, allowlisted Twilio message creation adapter."""

    def __init__(self, http=None, timeout=10.0, dispatch_ledger=None):
        self.http = http or requests
        self.timeout = timeout
        self.dispatch_ledger = dispatch_ledger

    def read(self, capability_id, payload, provider_context):
        raise UnsupportedCapabilityError("unsupported Twilio read capability")

    def execute(self, capability_id, payload, provider_context):
        if capability_id not in {
            "twilio.sms.send", "twilio.whatsapp.freeform.send",
            "twilio.whatsapp.template.send", "twilio.voice.call",
        }:
            raise UnsupportedCapabilityError("unsupported Twilio capability")
        account_sid = (
            provider_context.get("account_id")
            or provider_context.get("provider_account_id")
        )
        token = provider_context.get("access_token")
        if not account_sid or not token:
            raise PermissionError("Twilio account authority is unavailable")
        data = (
            self._voice_payload(payload) if capability_id == "twilio.voice.call"
            else self._message_payload(capability_id, payload)
        )
        if self.dispatch_ledger is not None:
            tenant_id = provider_context.get("tenant_id")
            dispatch_key = provider_context.get("dispatch_key")
            effect_id = provider_context.get("effect_id")
            if not all((tenant_id, dispatch_key, effect_id)):
                raise PermissionError("dispatch ledger binding is unavailable")
            return self.dispatch_ledger.dispatch(
                tenant_id, dispatch_key, effect_id, payload,
                provider_context.get("callback_token") or payload["status_callback"],
                lambda _intent: self._create_effect(
                    capability_id, data, provider_context, account_sid, token
                ),
            )
        return self._create_effect(
            capability_id, data, provider_context, account_sid, token
        )

    def _create_effect(self, capability_id, data, provider_context,
                        account_sid, token):
        resource = "Calls" if capability_id == "twilio.voice.call" else "Messages"
        operation = "call creation" if resource == "Calls" else "message creation"
        try:
            response = self.http.request(
                "POST", "%s/Accounts/%s/%s.json" % (API_ROOT, quote(account_sid), resource),
                auth=(provider_context.get("api_key_sid") or account_sid, token),
                timeout=self.timeout, data=data,
            )
        except requests.Timeout as exc:
            # Once the request crosses the network boundary a timeout does
            # not prove Twilio rejected it.  Preserve that uncertainty so the
            # write-ahead ledger blocks a duplicate send.
            raise TimeoutError("twilio %s outcome is unknown" % operation) from exc
        except requests.RequestException as exc:
            raise ProviderNetworkError("twilio %s network failure" % operation) from exc
        if not 200 <= response.status_code < 300:
            try:
                body = response.json()
            except (TypeError, ValueError, AttributeError):
                body = {}
            raise TwilioAPIError(
                response.status_code, operation, body.get("code"),
                response.headers.get("Retry-After"),
            )
        body = response.json()
        return {
            "provider": "twilio", "capability_id": capability_id,
            "provider_id": body["sid"], "status": body.get("status", "queued"),
        }

    def terminate_call(self, call_sid, provider_context):
        if not isinstance(call_sid, str) or not call_sid.startswith("CA"):
            raise ValueError("a Twilio Call SID is required")
        account_sid = provider_context.get("account_id") or provider_context.get("provider_account_id")
        token = provider_context.get("access_token")
        if not account_sid or not token:
            raise PermissionError("Twilio account authority is unavailable")
        try:
            response = self.http.request(
                "POST", "%s/Accounts/%s/Calls/%s.json" % (
                    API_ROOT, quote(account_sid), quote(call_sid)
                ), auth=(provider_context.get("api_key_sid") or account_sid, token),
                timeout=self.timeout, data={"Status": "completed"},
            )
        except requests.RequestException as exc:
            raise ProviderNetworkError("twilio call termination network failure") from exc
        if not 200 <= response.status_code < 300:
            raise TwilioAPIError(response.status_code, "call termination")
        return {"provider": "twilio", "provider_id": call_sid, "status": "completed"}

    @staticmethod
    def _voice_payload(payload):
        required = ("to", "from", "status_callback", "twiml_url", "definition_hash")
        if any(not isinstance(payload.get(key), str) or not payload[key] for key in required):
            raise ValueError("voice destination, sender, TwiML URL, callback and definition hash are required")
        duration = payload.get("maximum_duration_seconds")
        timeout = payload.get("ring_timeout_seconds", 20)
        if type(duration) is not int or not 15 <= duration <= 7200:
            raise ValueError("maximum_duration_seconds is invalid")
        if type(timeout) is not int or not 5 <= timeout <= 600:
            raise ValueError("ring_timeout_seconds is invalid")
        if type(payload.get("recording")) is not bool:
            raise ValueError("recording must be boolean")
        return {
            "To": payload["to"], "From": payload["from"], "Url": payload["twiml_url"],
            "StatusCallback": payload["status_callback"],
            "StatusCallbackEvent": ["initiated", "ringing", "answered", "completed"],
            "Timeout": str(timeout), "TimeLimit": str(duration),
            "Record": "true" if payload["recording"] else "false",
        }

    @staticmethod
    def _message_payload(capability_id, payload):
        required = ("to", "from", "status_callback")
        if any(not isinstance(payload.get(key), str) or not payload[key] for key in required):
            raise ValueError("message destination, sender and callback are required")
        data = {
            "To": payload["to"], "From": payload["from"],
            "StatusCallback": payload["status_callback"],
        }
        if capability_id == "twilio.whatsapp.template.send":
            if not payload.get("content_sid"):
                raise ValueError("a template send requires content_sid")
            data["ContentSid"] = payload["content_sid"]
            if payload.get("content_variables") is not None:
                import json
                data["ContentVariables"] = json.dumps(
                    payload["content_variables"], sort_keys=True, separators=(",", ":")
                )
        else:
            if not isinstance(payload.get("body"), str) or not payload["body"]:
                raise ValueError("a free-form message requires body")
            data["Body"] = payload["body"]
        if capability_id.startswith("twilio.whatsapp"):
            for key in ("To", "From"):
                if not data[key].startswith("whatsapp:"):
                    data[key] = "whatsapp:" + data[key]
        return data
