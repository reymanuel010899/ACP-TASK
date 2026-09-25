"""Slack OAuth v2 connector with bot-only, rotating authority."""

from urllib.parse import urlencode
from urllib.parse import urlsplit
import ipaddress
import logging
import socket
from contextlib import nullcontext

import requests

from libs.connectors.base import (
    OAuthCredentialConnector,
    ProviderAuthority,
    ProviderError,
    ProviderHTTPError,
    ProviderNetworkError,
)


logger = logging.getLogger(__name__)

AUTHORIZATION_URL = "https://slack.com/oauth/v2/authorize"
TOKEN_URL = "https://slack.com/api/oauth.v2.access"
UNINSTALL_URL = "https://slack.com/api/apps.uninstall"

def slack_scope_catalog():
    """Derive install scopes from the trusted descriptors, never a copy.

    This used to be a hand-maintained dict of one scope per capability. It
    drifted the moment a capability needed two: the DM descriptor required
    im:write and chat:write while the install still asked for im:write alone,
    which authorises a connection that cannot run what it advertises.
    """
    from libs.integrations.catalog import slack_definitions

    return {
        definition.capability_id: frozenset(definition.required_scopes)
        for definition in slack_definitions()
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


class SlackCredentialConnector(OAuthCredentialConnector):
    provider = "slack"

    def __init__(self, client_id, client_secret, redirect_uri, http=None,
                 timeout=10.0):
        if not client_id or not client_secret or not redirect_uri:
            raise ValueError("Slack client_id, client_secret and redirect_uri are required")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.http = http or requests
        self.timeout = timeout

    def authorization_url(self, state, code_challenge, scopes,
                          user_scopes=None):
        del code_challenge  # Slack confidential-server V1 intentionally has no PKCE.
        if not state or not (scopes or user_scopes):
            raise ValueError("state and at least one scope set are required")
        query = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": ",".join(sorted(set(scopes or ()))),
            "state": state,
        }
        if user_scopes:
            # Slack keeps personal consent in a separate parameter, and returns
            # its token in a separate block. Asking for both in one round is
            # what lets one consent screen cover the bot and the person.
            query["user_scope"] = ",".join(sorted(set(user_scopes)))
        return "%s?%s" % (AUTHORIZATION_URL, urlencode(query))

    def exchange_code_with_user(self, code, require_bot=True):
        """Exchange once and separate the two authorities Slack returns.

        The personal token comes back apart from the bot's, and never inside
        provider metadata: metadata is persisted with the connection row, so a
        user token placed there would sit unencrypted beside it.

        ``require_bot`` is false when the round asked for personal scopes
        only. Slack correctly answers those with an ``authed_user`` block and
        no bot token; demanding one unconditionally rejected a valid response
        and made personal consent impossible to complete.
        """
        payload = self._request("POST", TOKEN_URL, "code exchange", data={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "code": code,
        })
        user_authority = self._user_authority(payload)
        if not require_bot:
            if user_authority is None:
                logger.warning(
                    "Slack code exchange asked for personal scopes only but "
                    "returned no usable authed_user block"
                )
                raise ProviderHTTPError("slack", 200, "code exchange")
            return None, user_authority
        return self._bot_authority(payload, "code exchange"), user_authority

    @staticmethod
    def _user_authority(payload):
        block = payload.get("authed_user")
        if not isinstance(block, dict):
            return None
        token = block.get("access_token")
        subject = block.get("id")
        if not isinstance(token, str) or not token.startswith(
            ("xoxp-", "xoxe.xoxp-")
        ) or not subject:
            return None
        return {
            "slack_subject_id": subject,
            "access_token": token,
            "refresh_token": block.get("refresh_token"),
            "expires_in": block.get("expires_in"),
            "granted_scopes": frozenset(
                scope for scope in (block.get("scope") or "").split(",") if scope
            ),
            "token_type": "user",
        }

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
        return slack_scope_catalog()

    def _token_request(self, data, operation):
        payload = self._request("POST", TOKEN_URL, operation, data=data)
        return self._bot_authority(payload, operation)

    @staticmethod
    def _bot_authority(payload, operation):
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        expires_in = payload.get("expires_in")
        token_type = payload.get("token_type")
        # Which requirement failed, by name. Six conditions reported as one
        # "HTTP 200" told an operator nothing. Names only: a value here would
        # put a bot token in the log.
        unmet = []
        if not isinstance(access_token, str):
            unmet.append("access_token missing")
        elif not access_token.startswith(("xoxb-", "xoxe.xoxb-")):
            unmet.append("access_token is not a bot token")
        if not isinstance(refresh_token, str) or not refresh_token:
            unmet.append("refresh_token missing")
        if not isinstance(expires_in, int) or expires_in <= 0:
            unmet.append("expires_in missing")
        if token_type not in ("bot", "Bearer"):
            unmet.append("token_type is %r" % (token_type,))
        if unmet:
            # Two very different causes land here, so name both rather than
            # guessing: a whole payload with nothing in it is a personal-scope
            # round answered correctly, while a payload missing only the
            # rotation fields is an app with token rotation switched off.
            if access_token is None and refresh_token is None:
                unmet.append(
                    "no bot token at all — the round may have asked for "
                    "personal scopes only"
                )
            elif isinstance(access_token, str) and refresh_token is None:
                unmet.append("token rotation may be off for this app")
            logger.warning(
                "Slack %s returned a payload we cannot accept: %s",
                operation, "; ".join(unmet),
            )
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
            "slack.users.list": self._list_users,
            "slack.message.permalink": self._message_permalink,
            "slack.private_channels.list": self._list_private_channels,
            "slack.private_conversation.read": self._read_conversation,
            "slack.private_thread.read": self._read_thread,
            "slack.search.messages": self._search_messages,
        }
        handler = routes.get(capability_id)
        if handler is None:
            raise SlackAPIError(capability_id, "unsupported_capability", "validation")
        return handler(payload, provider_context)

    def execute(self, capability_id, payload, provider_context):
        routes = {
            "slack.message.send": self._send_message,
            "slack.thread.reply": self._reply_thread,
            "slack.direct_message.send": self._send_direct_message,
            "slack.reaction.add": self._add_reaction,
            "slack.reaction.remove": self._remove_reaction,
            "slack.message.pin": self._pin_message,
            "slack.message.unpin": self._unpin_message,
            "slack.bookmark.add": self._add_bookmark,
            "slack.channel.create": self._create_channel,
            "slack.channel.rename": self._rename_channel,
            "slack.channel.set_topic": self._set_channel_topic,
            "slack.channel.archive": self._archive_channel,
            "slack.channel.invite": self._invite_to_channel,
            "slack.file.upload": self._upload_file,
        }
        handler = routes.get(capability_id)
        if handler is None:
            raise SlackAPIError(capability_id, "unsupported_capability", "validation")
        channel_id = payload.get("channel_id") or payload.get("user_id")
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
        params = {
            "limit": min(int(payload.get("limit", 100)), 200),
            "exclude_archived": "true",
            "types": channel_type,
        }
        _copy_page_params(payload, params, ("cursor",))
        data = self._api("conversations.list", context, params=params)
        channels = []
        for channel in data.get("channels", []):
            if (
                not isinstance(channel, dict)
                or channel.get("is_archived") is True
                or channel.get("is_ext_shared") is True
                or (channel_type == "public_channel" and channel.get("is_private") is True)
                or (channel_type == "private_channel" and channel.get("is_private") is not True)
            ):
                continue
            channels.append({
                "id": channel.get("id"),
                "name": channel.get("name"),
                "is_private": bool(channel.get("is_private")),
            })
        return _page(channels, "channels", data)

    def _read_conversation(self, payload, context):
        self._reject_shared(payload)
        channel_id = _required_str(payload, "channel_id")
        params = {
            "channel": channel_id,
            "limit": min(int(payload.get("limit", 50)), 100),
        }
        _copy_page_params(payload, params, ("oldest", "latest", "cursor"))
        data = self._api("conversations.history", context, params=params)
        return _page(_filtered_messages(data.get("messages", [])), "messages", data)

    def _read_thread(self, payload, context):
        self._reject_shared(payload)
        params = {
            "channel": _required_str(payload, "channel_id"),
            "ts": _required_str(payload, "thread_ts"),
            "limit": min(int(payload.get("limit", 50)), 100),
        }
        _copy_page_params(payload, params, ("oldest", "latest", "cursor"))
        data = self._api("conversations.replies", context, params=params)
        return _page(_filtered_messages(data.get("messages", [])), "messages", data)

    def _search_messages(self, payload, context):
        """Search as the consenting user, never as the installation.

        search.messages returns what one person can see. Running it with a bot
        token would answer a different question than the one asked, so the
        connector refuses unless the broker handed it user authority.
        """
        if context.get("authority_profile") != "user":
            raise SlackAPIError(
                "search.messages", "user_authority_required", "permission"
            )
        params = {
            "query": _required_str(payload, "query"),
            "count": min(int(payload.get("limit", 20)), 100),
        }
        _copy_page_params(payload, params, ("cursor",))
        data = self._api("search.messages", context, params=params)
        block = data.get("messages") if isinstance(
            data.get("messages"), dict
        ) else {}
        matches = []
        for match in block.get("matches", []) or []:
            if not isinstance(match, dict) or not match.get("ts"):
                continue
            channel = match.get("channel") if isinstance(
                match.get("channel"), dict
            ) else {}
            matches.append({
                "ts": match.get("ts"),
                "text": match.get("text", ""),
                "user": match.get("user"),
                "thread_ts": match.get("thread_ts"),
                "channel_id": channel.get("id"),
            })
        return _page(matches, "messages", data)

    def _list_users(self, payload, context):
        params = {"limit": min(int(payload.get("limit", 100)), 200)}
        _copy_page_params(payload, params, ("cursor",))
        data = self._api("users.list", context, params=params)
        users = []
        for member in data.get("members", []):
            if (
                not isinstance(member, dict)
                or member.get("deleted") is True
                or member.get("is_bot") is True
                or member.get("is_app_user") is True
                or member.get("id") == "USLACKBOT"
            ):
                continue
            profile = member.get("profile") if isinstance(member.get("profile"), dict) else {}
            user = {
                "id": member.get("id"),
                "handle": member.get("name"),
                "display_name": profile.get("display_name") or "",
                "real_name": profile.get("real_name") or member.get("real_name") or "",
            }
            image = _safe_image_url(profile.get("image_48"))
            if image:
                user["image_url"] = image
            if isinstance(user["id"], str) and user["id"]:
                users.append(user)
        return _page(users, "users", data)

    def _message_permalink(self, payload, context):
        channel_id = _required_str(payload, "channel_id")
        message_ts = _required_str(payload, "message_ts")
        data = self._api("chat.getPermalink", context, params={
            "channel": channel_id, "message_ts": message_ts,
        })
        permalink = data.get("permalink")
        if not isinstance(permalink, str) or not permalink.startswith("https://"):
            raise SlackAPIError("chat.getPermalink", "invalid_permalink")
        return {
            "channel_id": channel_id, "message_ts": message_ts,
            "permalink": permalink,
        }

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

    def _send_direct_message(self, payload, context):
        user_id = _required_str(payload, "user_id")
        opened = self._api("conversations.open", context, json={"users": user_id})
        channel = opened.get("channel") if isinstance(opened.get("channel"), dict) else {}
        channel_id = channel.get("id")
        if not isinstance(channel_id, str) or not channel_id:
            raise SlackAPIError("conversations.open", "missing_channel_id")
        sent = self._api("chat.postMessage", context, json={
            "channel": channel_id,
            "text": _required_str(payload, "text"),
            "unfurl_links": False, "unfurl_media": False,
        })
        receipt = self._message_receipt(
            "slack.direct_message.send", channel_id, sent, context
        )
        receipt["user_id"] = user_id
        return receipt

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

    def _remove_reaction(self, payload, context):
        channel_id = _required_str(payload, "channel_id")
        name = _required_str(payload, "reaction")
        try:
            self._api("reactions.remove", context, json={
                "channel": channel_id,
                "timestamp": _required_str(payload, "message_ts"),
                "name": name,
            })
        except SlackAPIError as exc:
            # The reaction is already gone, which is the state the caller
            # asked for. Treating that as a failure would make a correct
            # retry look broken.
            if exc.code not in ("no_reaction", "message_not_found"):
                raise
        return {
            "provider": "slack",
            "capability_id": "slack.reaction.remove",
            "provider_id": "%s:%s:%s" % (
                channel_id, payload["message_ts"], name
            ),
            "team_id": context.get("team_id"),
            "channel_id": channel_id,
            "message_ts": payload["message_ts"],
            "reaction": name,
        }

    def _pin_message(self, payload, context):
        return self._set_pin(payload, context, "slack.message.pin")

    def _unpin_message(self, payload, context):
        return self._set_pin(payload, context, "slack.message.unpin")

    def _set_pin(self, payload, context, capability_id):
        channel_id = _required_str(payload, "channel_id")
        message_ts = _required_str(payload, "message_ts")
        pinning = capability_id == "slack.message.pin"
        # Already pinned, or already unpinned, is the state the caller asked
        # for; only a genuine refusal should surface as a failure.
        tolerated = ("already_pinned",) if pinning else ("no_pin", "not_pinned")
        try:
            self._api(
                "pins.add" if pinning else "pins.remove", context,
                json={"channel": channel_id, "timestamp": message_ts},
            )
        except SlackAPIError as exc:
            if exc.code not in tolerated:
                raise
        return {
            "provider": "slack",
            "capability_id": capability_id,
            "provider_id": "%s:%s" % (channel_id, message_ts),
            "team_id": context.get("team_id"),
            "channel_id": channel_id,
            "message_ts": message_ts,
        }

    def _add_bookmark(self, payload, context):
        channel_id = _required_str(payload, "channel_id")
        title = _required_str(payload, "title")
        link = _required_str(payload, "link")
        if not link.startswith("https://"):
            raise SlackAPIError("bookmarks.add", "insecure_link", "validation")
        data = self._api("bookmarks.add", context, json={
            "channel_id": channel_id, "title": title,
            "type": "link", "link": link,
        })
        bookmark = data.get("bookmark") if isinstance(
            data.get("bookmark"), dict
        ) else {}
        bookmark_id = bookmark.get("id")
        if not isinstance(bookmark_id, str) or not bookmark_id:
            raise SlackAPIError("bookmarks.add", "missing_bookmark_id")
        return {
            "provider": "slack",
            "capability_id": "slack.bookmark.add",
            "provider_id": bookmark_id,
            "team_id": context.get("team_id"),
            "channel_id": channel_id,
            "bookmark_id": bookmark_id,
            "title": title,
        }

    def _create_channel(self, payload, context):
        data = self._api("conversations.create", context, json={
            "name": _required_str(payload, "name"),
            "is_private": bool(payload.get("is_private", False)),
        })
        channel = data.get("channel") if isinstance(
            data.get("channel"), dict
        ) else {}
        if not channel.get("id"):
            raise SlackAPIError("conversations.create", "missing_channel_id")
        return self._channel_receipt(
            "slack.channel.create", channel["id"], context,
            {"name": channel.get("name") or payload["name"]},
        )

    def _rename_channel(self, payload, context):
        channel_id = _required_str(payload, "channel_id")
        data = self._api("conversations.rename", context, json={
            "channel": channel_id, "name": _required_str(payload, "name"),
        })
        channel = data.get("channel") if isinstance(
            data.get("channel"), dict
        ) else {}
        return self._channel_receipt(
            "slack.channel.rename", channel_id, context,
            {"name": channel.get("name") or payload["name"]},
        )

    def _set_channel_topic(self, payload, context):
        channel_id = _required_str(payload, "channel_id")
        topic = payload.get("topic")
        if not isinstance(topic, str):
            raise SlackAPIError(
                "conversations.setTopic", "invalid_topic", "validation"
            )
        self._api("conversations.setTopic", context, json={
            "channel": channel_id, "topic": topic,
        })
        return self._channel_receipt(
            "slack.channel.set_topic", channel_id, context, {"topic": topic},
        )

    def _archive_channel(self, payload, context):
        channel_id = _required_str(payload, "channel_id")
        try:
            self._api("conversations.archive", context, json={
                "channel": channel_id,
            })
        except SlackAPIError as exc:
            # Already archived is the state the caller asked for.
            if exc.code != "already_archived":
                raise
        return self._channel_receipt(
            "slack.channel.archive", channel_id, context, {},
        )

    def _invite_to_channel(self, payload, context):
        channel_id = _required_str(payload, "channel_id")
        user_ids = payload.get("user_ids")
        if not isinstance(user_ids, list) or not all(
            isinstance(item, str) and item for item in user_ids
        ) or not user_ids:
            raise SlackAPIError(
                "conversations.invite", "invalid_user_ids", "validation"
            )
        try:
            self._api("conversations.invite", context, json={
                "channel": channel_id, "users": ",".join(user_ids),
            })
        except SlackAPIError as exc:
            # Everyone asked for is already in the channel, which is the
            # requested state; anything else is a real refusal.
            if exc.code != "already_in_channel":
                raise
        return self._channel_receipt(
            "slack.channel.invite", channel_id, context,
            {"invited": len(user_ids)},
        )

    @staticmethod
    def _channel_receipt(capability_id, channel_id, context, extra):
        receipt = {
            "provider": "slack",
            "capability_id": capability_id,
            "provider_id": channel_id,
            "team_id": context.get("team_id"),
            "channel_id": channel_id,
        }
        receipt.update(extra)
        return receipt

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
                "not_in_channel": "membership",
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


def _copy_page_params(source, target, names):
    for name in names:
        value = source.get(name)
        if isinstance(value, str) and value:
            target[name] = value


def _page(items, field, data):
    metadata = data.get("response_metadata")
    cursor = metadata.get("next_cursor") if isinstance(metadata, dict) else None
    cursor = cursor if isinstance(cursor, str) and cursor else None
    return {field: items, "next_cursor": cursor, "partial": cursor is not None}


def _safe_image_url(value):
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    return value


def _resolve_host(host):
    return sorted({item[4][0] for item in socket.getaddrinfo(host, 443)})
