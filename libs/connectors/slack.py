"""Slack OAuth v2 connector with bot-only, rotating authority."""

from urllib.parse import urlencode
from urllib.parse import urlsplit
import ipaddress
import socket
from contextlib import nullcontext

import requests

from libs.connectors.base import (
    CredentialConnector,
    ProviderAuthority,
    ProviderError,
    ProviderHTTPError,
    ProviderNetworkError,
)


AUTHORIZATION_URL = "https://slack.com/oauth/v2/authorize"
TOKEN_URL = "https://slack.com/api/oauth.v2.access"
UNINSTALL_URL = "https://slack.com/api/apps.uninstall"

SLACK_SCOPE_CATALOG = {
    "slack.channels.list": "channels:read",
    "slack.conversation.read": "channels:history",
    "slack.thread.read": "channels:history",
    "slack.private_channels.list": "groups:read",
    "slack.private_conversation.read": "groups:history",
    "slack.private_thread.read": "groups:history",
    "slack.message.send": "chat:write",
    "slack.thread.reply": "chat:write",
    "slack.reaction.add": "reactions:write",
    "slack.file.upload": "files:write",
}

SLACK_API = "https://slack.com/api"


class SlackAPIError(ProviderError):
    def __init__(self, method, code, category="provider"):
        super().__init__("slack %s failed: %s" % (method, code))
        self.method = method
        self.code = code
        self.category = category


class SlackRateLimitError(ProviderError):
    def __init__(self, connection_id, method, retry_after):
        super().__init__("slack %s is rate limited" % method)
        self.connection_id = connection_id
        self.method = method
        self.retry_after = retry_after


class SlackCredentialConnector(CredentialConnector):
    def __init__(self, client_id, client_secret, redirect_uri, http=None,
                 timeout=10.0):
        if not client_id or not client_secret or not redirect_uri:
            raise ValueError("Slack client_id, client_secret and redirect_uri are required")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.http = http or requests
        self.timeout = timeout

    def authorization_url(self, state, code_challenge, scopes):
        del code_challenge  # Slack confidential-server V1 intentionally has no PKCE.
        if not state or not scopes:
            raise ValueError("state and bot scopes are required")
        return "%s?%s" % (AUTHORIZATION_URL, urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": ",".join(sorted(set(scopes))),
            "state": state,
        }))

    def exchange_code(self, code, code_verifier):
        del code_verifier
        return self._token_request({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "code": code,
        }, "code exchange")

    def refresh(self, refresh_token):
        return self._token_request({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }, "token refresh")

    def revoke(self, token):
        payload = self._request("POST", UNINSTALL_URL, "app uninstall", data={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "token": token,
        })
        return payload.get("ok") is True

    def scope_catalog(self):
        return dict(SLACK_SCOPE_CATALOG)

    def _token_request(self, data, operation):
        payload = self._request("POST", TOKEN_URL, operation, data=data)
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        expires_in = payload.get("expires_in")
        token_type = payload.get("token_type")
        if (
            not isinstance(access_token, str)
            or not access_token.startswith(("xoxb-", "xoxe.xoxb-"))
            or not isinstance(refresh_token, str)
            or not refresh_token
            or not isinstance(expires_in, int)
            or expires_in <= 0
            or token_type not in ("bot", "Bearer")
        ):
            raise ProviderHTTPError("slack", 200, operation)
        team = payload.get("team") if isinstance(payload.get("team"), dict) else {}
        enterprise = (
            payload.get("enterprise")
            if isinstance(payload.get("enterprise"), dict)
            else {}
        )
        return ProviderAuthority(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            granted_scopes=frozenset(
                scope for scope in payload.get("scope", "").split(",") if scope
            ),
            token_type="bot",
            provider_metadata={
                "app_id": payload.get("app_id"),
                "team_id": team.get("id"),
                "team_name": team.get("name"),
                "enterprise_id": enterprise.get("id"),
                "enterprise_name": enterprise.get("name"),
                "bot_user_id": payload.get("bot_user_id"),
            },
        )

    def _request(self, method, url, operation, **kwargs):
        try:
            response = self.http.request(
                method, url, timeout=self.timeout, **kwargs
            )
        except requests.RequestException as exc:
            raise ProviderNetworkError(
                "slack %s network failure" % operation
            ) from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderHTTPError("slack", response.status_code, operation)
        try:
            payload = response.json()
        except (AttributeError, TypeError, ValueError) as exc:
            raise ProviderHTTPError("slack", response.status_code, operation) from exc
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise ProviderHTTPError("slack", response.status_code, operation)
        return payload


class SlackActionExecutor:
    """Closed, filtered Slack Web API capability adapter."""

    def __init__(self, http=None, timeout=10.0, rate_policy=None,
                 host_resolver=None):
        self.http = http or requests
        self.timeout = timeout
        self.rate_policy = rate_policy
        self.host_resolver = host_resolver or _resolve_host

    def read(self, capability_id, payload, provider_context):
        routes = {
            "slack.channels.list": self._list_public_channels,
            "slack.conversation.read": self._read_conversation,
            "slack.thread.read": self._read_thread,
            "slack.private_channels.list": self._list_private_channels,
            "slack.private_conversation.read": self._read_conversation,
            "slack.private_thread.read": self._read_thread,
        }
        handler = routes.get(capability_id)
        if handler is None:
            raise SlackAPIError(capability_id, "unsupported_capability", "validation")
        return handler(payload, provider_context)

    def execute(self, capability_id, payload, provider_context):
        routes = {
            "slack.message.send": self._send_message,
            "slack.thread.reply": self._reply_thread,
            "slack.reaction.add": self._add_reaction,
            "slack.file.upload": self._upload_file,
        }
        handler = routes.get(capability_id)
        if handler is None:
            raise SlackAPIError(capability_id, "unsupported_capability", "validation")
        channel_id = payload.get("channel_id")
        guard = (
            self.rate_policy.write_guard(
                provider_context.get("connection_id"), channel_id
            )
            if self.rate_policy is not None
            else nullcontext()
        )
        with guard:
            return handler(payload, provider_context)

    def _list_public_channels(self, payload, context):
        return self._list_channels(payload, context, "public_channel")

    def _list_private_channels(self, payload, context):
        return self._list_channels(payload, context, "private_channel")

    def _list_channels(self, payload, context, channel_type):
        data = self._api("conversations.list", context, params={
            "limit": min(int(payload.get("limit", 100)), 200),
            "exclude_archived": "true",
            "types": channel_type,
        })
        channels = []
        for channel in data.get("channels", []):
            if not isinstance(channel, dict) or channel.get("is_ext_shared"):
                continue
            channels.append({
                "id": channel.get("id"),
                "name": channel.get("name"),
                "is_private": bool(channel.get("is_private")),
            })
        return {"channels": channels}

    def _read_conversation(self, payload, context):
        self._reject_shared(payload)
        channel_id = _required_str(payload, "channel_id")
        data = self._api("conversations.history", context, params={
            "channel": channel_id,
            "limit": min(int(payload.get("limit", 50)), 100),
        })
        return {"messages": _filtered_messages(data.get("messages", []))}

    def _read_thread(self, payload, context):
        self._reject_shared(payload)
        data = self._api("conversations.replies", context, params={
            "channel": _required_str(payload, "channel_id"),
            "ts": _required_str(payload, "thread_ts"),
            "limit": min(int(payload.get("limit", 50)), 100),
        })
        return {"messages": _filtered_messages(data.get("messages", []))}

    def _send_message(self, payload, context):
        channel_id = _required_str(payload, "channel_id")
        data = self._api("chat.postMessage", context, json={
            "channel": channel_id,
            "text": _required_str(payload, "text"),
            "unfurl_links": False,
            "unfurl_media": False,
        })
        return self._message_receipt(
            "slack.message.send", channel_id, data, context
        )

    def _reply_thread(self, payload, context):
        channel_id = _required_str(payload, "channel_id")
        data = self._api("chat.postMessage", context, json={
            "channel": channel_id,
            "thread_ts": _required_str(payload, "thread_ts"),
            "text": _required_str(payload, "text"),
            "unfurl_links": False,
            "unfurl_media": False,
        })
        return self._message_receipt(
            "slack.thread.reply", channel_id, data, context
        )

    def _add_reaction(self, payload, context):
        channel_id = _required_str(payload, "channel_id")
        name = _required_str(payload, "reaction")
        try:
            data = self._api("reactions.add", context, json={
                "channel": channel_id,
                "timestamp": _required_str(payload, "message_ts"),
                "name": name,
            })
        except SlackAPIError as exc:
            if exc.code != "already_reacted":
                raise
            data = {"ok": True}
        return {
            "provider": "slack",
            "capability_id": "slack.reaction.add",
            "provider_id": "%s:%s:%s" % (
                channel_id, payload["message_ts"], name
            ),
            "team_id": context.get("team_id"),
            "channel_id": channel_id,
            "message_ts": payload["message_ts"],
            "reaction": name,
        }

    def _upload_file(self, payload, context):
        channel_id = _required_str(payload, "channel_id")
        filename = _required_str(payload, "filename")
        content = payload.get("content")
        if not isinstance(content, (bytes, bytearray)) or not content:
            raise ValueError("file content is required")
        upload = self._api("files.getUploadURLExternal", context, params={
            "filename": filename,
            "length": len(content),
        })
        upload_url = upload.get("upload_url")
        file_id = upload.get("file_id")
        self._validate_upload_url(upload_url)
        response = self._raw_request(
            "POST", upload_url, context, data=bytes(content),
            headers={"Content-Type": "application/octet-stream"},
            allow_redirects=False,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise SlackAPIError("files.uploadExternal", "upload_failed")
        completed = self._api("files.completeUploadExternal", context, json={
            "files": [{"id": file_id, "title": payload.get("title", filename)}],
            "channel_id": channel_id,
            "initial_comment": payload.get("initial_comment", ""),
        })
        files = completed.get("files") if isinstance(completed.get("files"), list) else []
        returned_id = files[0].get("id") if files and isinstance(files[0], dict) else file_id
        return {
            "provider": "slack",
            "capability_id": "slack.file.upload",
            "provider_id": returned_id,
            "team_id": context.get("team_id"),
            "channel_id": channel_id,
            "file_id": returned_id,
        }

    def _api(self, method, context, **kwargs):
        response = self._raw_request(
            "POST" if "json" in kwargs else "GET",
            "%s/%s" % (SLACK_API, method), context, **kwargs
        )
        connection_id = context.get("connection_id")
        if response.status_code == 429:
            try:
                retry_after = int(response.headers.get("Retry-After", "1"))
            except (TypeError, ValueError):
                retry_after = 1
            if self.rate_policy is not None:
                self.rate_policy.block(connection_id, method, retry_after)
            raise SlackRateLimitError(connection_id, method, retry_after)
        if response.status_code < 200 or response.status_code >= 300:
            raise SlackAPIError(method, "http_%s" % response.status_code, "transient")
        try:
            data = response.json()
        except (AttributeError, TypeError, ValueError) as exc:
            raise SlackAPIError(method, "invalid_json") from exc
        if not isinstance(data, dict) or data.get("ok") is not True:
            code = data.get("error", "unknown_error") if isinstance(data, dict) else "invalid_response"
            categories = {
                "missing_scope": "scope",
                "invalid_auth": "auth",
                "token_revoked": "auth",
                "not_in_channel": "permission",
                "channel_not_found": "validation",
            }
            raise SlackAPIError(method, code, categories.get(code, "provider"))
        return data

    def _raw_request(self, method, url, context, **kwargs):
        token = context.get("access_token") if isinstance(context, dict) else None
        if not isinstance(token, str) or not token:
            raise SlackAPIError("authorization", "missing_broker_authority", "auth")
        if self.rate_policy is not None:
            self.rate_policy.check(context.get("connection_id"), url.rsplit("/", 1)[-1])
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = "Bearer %s" % token
        try:
            return self.http.request(
                method, url, timeout=self.timeout, headers=headers, **kwargs
            )
        except requests.RequestException as exc:
            raise ProviderNetworkError("slack provider dispatch outcome is unknown") from exc

    def _validate_upload_url(self, value):
        if not isinstance(value, str):
            raise ValueError("Slack upload host is invalid")
        parsed = urlsplit(value)
        host = parsed.hostname
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username
            or parsed.password
            or not (host == "slack.com" or host.endswith(".slack.com"))
        ):
            raise ValueError("Slack upload host is invalid")
        addresses = self.host_resolver(host)
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise ValueError("Slack upload host resolves to a private address")

    @staticmethod
    def _reject_shared(payload):
        if payload.get("is_ext_shared") is True:
            raise ValueError("Slack Connect channels are disabled")

    @staticmethod
    def _message_receipt(capability_id, channel_id, data, context):
        ts = data.get("ts")
        if not isinstance(ts, str) or not ts:
            raise SlackAPIError("chat.postMessage", "missing_message_id")
        return {
            "provider": "slack",
            "capability_id": capability_id,
            "provider_id": ts,
            "team_id": context.get("team_id"),
            "channel_id": channel_id,
            "message_ts": ts,
        }


def _required_str(payload, field):
    value = payload.get(field) if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s is required" % field)
    return value


def _filtered_messages(messages):
    return [{
        "ts": message.get("ts"),
        "text": message.get("text", ""),
        "user": message.get("user"),
        "thread_ts": message.get("thread_ts"),
    } for message in messages if isinstance(message, dict)]


def _resolve_host(host):
    return sorted({item[4][0] for item in socket.getaddrinfo(host, 443)})
