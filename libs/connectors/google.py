"""Google implementation of the provider-neutral connector boundaries."""

import json
import base64
from email.message import EmailMessage
from urllib.parse import urlencode

import requests

from libs.connectors.base import (
    ActionExecutor,
    OAuthCredentialConnector,
    ProviderAuthority,
    ProviderHTTPError,
    ProviderNetworkError,
    ProviderReceipt,
    UnsupportedCapabilityError,
)


AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOCATION_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"


GOOGLE_SCOPE_CATALOG = {
    "gmail.send": "https://www.googleapis.com/auth/gmail.send",
    "gmail.read": "https://www.googleapis.com/auth/gmail.readonly",
    "calendar.create": "https://www.googleapis.com/auth/calendar.events",
    "calendar.read": "https://www.googleapis.com/auth/calendar.readonly",
    "drive.upload": "https://www.googleapis.com/auth/drive.file",
    "drive.read": "https://www.googleapis.com/auth/drive.readonly",
}


def _request(http, timeout, method, url, operation, **kwargs):
    try:
        response = http.request(method, url, timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        raise ProviderNetworkError(
            "google %s network failure" % operation
        ) from exc
    if response.status_code < 200 or response.status_code >= 300:
        raise ProviderHTTPError("google", response.status_code, operation)
    return response


class GoogleCredentialConnector(OAuthCredentialConnector):
    provider = "google"

    def __init__(self, client_id, client_secret, redirect_uri, http=None,
                 timeout=10.0):
        if not client_id or not client_secret or not redirect_uri:
            raise ValueError("Google client_id, client_secret and redirect_uri are required")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.http = http or requests
        self.timeout = timeout

    def authorization_url(self, state, code_challenge, scopes):
        if not state or not code_challenge or not scopes:
            raise ValueError("state, PKCE challenge and scopes are required")
        return "%s?%s" % (
            AUTHORIZATION_URL,
            urlencode(
                {
                    "client_id": self.client_id,
                    "redirect_uri": self.redirect_uri,
                    "response_type": "code",
                    "scope": " ".join(sorted(set(scopes))),
                    "state": state,
                    "code_challenge": code_challenge,
                    "code_challenge_method": "S256",
                    "access_type": "offline",
                    "include_granted_scopes": "true",
                    "prompt": "consent",
                }
            ),
        )

    def exchange_code(self, code, code_verifier):
        return self._token_request(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
            },
            "code exchange",
        )

    def refresh(self, refresh_token):
        # Google decides the refreshed token's lifetime and authority.  Do not
        # accept requested scopes or a caller-supplied TTL here.
        return self._token_request(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            "token refresh",
        )

    def revoke(self, token):
        try:
            response = self.http.request(
                "POST",
                REVOCATION_URL,
                timeout=self.timeout,
                data={"token": token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except requests.RequestException as exc:
            raise ProviderNetworkError(
                "google token revocation network failure"
            ) from exc
        if response.status_code == 200:
            return True
        if response.status_code == 400:
            try:
                error = response.json().get("error")
            except (AttributeError, TypeError, ValueError):
                error = None
            if error == "invalid_token":
                # Google confirms there is no active authority left to revoke.
                return "invalid_token"
        raise ProviderHTTPError(
            "google", response.status_code, "token revocation"
        )

    def scope_catalog(self):
        return dict(GOOGLE_SCOPE_CATALOG)

    def _token_request(self, data, operation):
        response = self._request(
            "POST",
            TOKEN_URL,
            operation=operation,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        payload = _json_object(response, operation)
        access_token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        if not isinstance(access_token, str) or not access_token:
            raise ProviderHTTPError("google", response.status_code, operation)
        if not isinstance(expires_in, int) or expires_in <= 0:
            raise ProviderHTTPError("google", response.status_code, operation)
        scopes = payload.get("scope", "")
        return ProviderAuthority(
            access_token=access_token,
            refresh_token=payload.get("refresh_token"),
            expires_in=expires_in,
            granted_scopes=frozenset(s for s in scopes.split(" ") if s),
            token_type=payload.get("token_type", "Bearer"),
        )

    def _request(self, method, url, operation, **kwargs):
        return _request(
            self.http, self.timeout, method, url, operation, **kwargs
        )


class GoogleActionExecutor(ActionExecutor):
    """Closed routing table for Google reads and side effects.

    ``provider_context`` is broker-internal and must contain an access token.
    Results are receipts or allowlisted read fields, never a bearer token or a
    raw provider response.
    """

    def __init__(self, http=None, timeout=10.0):
        self.http = http or requests
        self.timeout = timeout

    def execute(self, capability_id, payload, provider_context):
        routes = {
            "gmail.send": self._send_gmail,
            "calendar.create": self._create_event,
            "drive.upload": self._upload_drive_file,
        }
        handler = routes.get(capability_id)
        if handler is None:
            raise UnsupportedCapabilityError(
                "unsupported Google side-effect capability: %s" % capability_id
            )
        provider_id = handler(payload, self._headers(provider_context))
        return ProviderReceipt("google", capability_id, provider_id)

    def read(self, capability_id, payload, provider_context):
        routes = {
            "gmail.read": self._read_gmail,
            "calendar.read": self._read_calendar,
            "drive.read": self._read_drive,
        }
        handler = routes.get(capability_id)
        if handler is None:
            raise UnsupportedCapabilityError(
                "unsupported Google read capability: %s" % capability_id
            )
        return handler(payload, self._headers(provider_context))

    def _headers(self, context):
        token = context.get("access_token") if isinstance(context, dict) else None
        if not isinstance(token, str) or not token:
            raise ProviderNetworkError("broker did not supply Google authority")
        return {"Authorization": "Bearer %s" % token}

    def _send_gmail(self, payload, headers):
        raw = payload.get("raw")
        if not raw:
            message = EmailMessage()
            recipients = payload.get("to")
            if isinstance(recipients, list):
                recipients = ", ".join(recipients)
            message["To"] = recipients
            message["Subject"] = payload.get("subject")
            message.set_content(payload.get("body"))
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
        response = self._request(
            "POST",
            "%s/users/me/messages/send" % GMAIL_API,
            "gmail.send",
            headers=headers,
            json={"raw": raw},
        )
        return self._provider_id(response, "gmail.send")

    def _create_event(self, payload, headers):
        calendar_id = payload.get("calendar_id", "primary")
        event = payload.get("event")
        if event is None:
            def moment(value):
                return value if isinstance(value, dict) else {"dateTime": value}
            event = {
                "summary": payload["summary"],
                "start": moment(payload["start"]),
                "end": moment(payload["end"]),
            }
            if payload.get("attendees"):
                event["attendees"] = [{"email": email} for email in payload["attendees"]]
            if payload.get("description"):
                event["description"] = payload["description"]
        response = self._request(
            "POST",
            "%s/calendars/%s/events" % (CALENDAR_API, calendar_id),
            "calendar.create",
            headers=headers,
            json=event,
        )
        return self._provider_id(response, "calendar.create")

    def _upload_drive_file(self, payload, headers):
        response = self._request(
            "POST",
            "%s/files?uploadType=multipart" % DRIVE_UPLOAD_API,
            "drive.upload",
            headers=headers,
            data={"metadata": json.dumps({"name": payload.get("name", "")})},
            files={
                "file": (
                    payload.get("name", "upload"),
                    payload.get("content", b""),
                    payload.get("mime_type", "application/octet-stream"),
                )
            },
        )
        return self._provider_id(response, "drive.upload")

    def _read_gmail(self, payload, headers):
        response = self._request(
            "GET",
            "%s/users/me/messages" % GMAIL_API,
            "gmail.read",
            headers=headers,
            params={"maxResults": payload.get("max_results", 20)},
        )
        messages = _json_object(response, "gmail.read").get("messages", [])
        return {
            "messages": [
                {key: item.get(key) for key in ("id", "threadId")}
                for item in messages
                if isinstance(item, dict)
            ]
        }

    def _read_calendar(self, payload, headers):
        calendar_id = payload.get("calendar_id", "primary")
        response = self._request(
            "GET",
            "%s/calendars/%s/events" % (CALENDAR_API, calendar_id),
            "calendar.read",
            headers=headers,
            params={
                key: payload[key]
                for key in ("timeMin", "timeMax", "maxResults")
                if key in payload
            },
        )
        items = _json_object(response, "calendar.read").get("items", [])
        return {
            "items": [
                {
                    "id": item.get("id"),
                    "summary": item.get("summary"),
                    "start": item.get("start"),
                    "end": item.get("end"),
                    "status": item.get("status"),
                }
                for item in items
                if isinstance(item, dict)
            ]
        }

    def _read_drive(self, payload, headers):
        response = self._request(
            "GET",
            "%s/files" % DRIVE_API,
            "drive.read",
            headers=headers,
            params={
                "q": payload.get("query"),
                "pageSize": payload.get("page_size", 20),
                "fields": "files(id,name,mimeType,modifiedTime)",
            },
        )
        files = _json_object(response, "drive.read").get("files", [])
        return {
            "files": [
                {
                    key: item.get(key)
                    for key in ("id", "name", "mimeType", "modifiedTime")
                }
                for item in files
                if isinstance(item, dict)
            ]
        }

    def _provider_id(self, response, operation):
        provider_id = _json_object(response, operation).get("id")
        if not isinstance(provider_id, str) or not provider_id:
            raise ProviderHTTPError("google", response.status_code, operation)
        return provider_id

    def _request(self, method, url, operation, **kwargs):
        return _request(
            self.http, self.timeout, method, url, operation, **kwargs
        )


def _json_object(response, operation):
    try:
        value = response.json()
    except (TypeError, ValueError) as exc:
        raise ProviderHTTPError("google", response.status_code, operation) from exc
    if not isinstance(value, dict):
        raise ProviderHTTPError("google", response.status_code, operation)
    return value
