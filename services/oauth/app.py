"""First-party, session-bound Google OAuth service (U3)."""

import argparse
import base64
import hashlib
import json
import os
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from libs.aws_kms import AWSKMSClient
from libs.config import get_google_oauth_config
from libs.config import ConfigurationError, get_slack_oauth_config
from libs.connectors.base import ProviderError
from libs.connectors.google import GoogleCredentialConnector
from libs.connectors.slack import SlackCredentialConnector
from services.oauth.repository import ConnectionConflict, OAuthRepository
from services.session.app import session_cookie_value
from services.session.repository import SessionRepository
from vault.app import VaultService
from vault.managed_oauth_crypto import ManagedOAuthCrypto, ManagedOAuthError
from vault.repository import VaultRepository


PROVIDER = "google"
DEFAULT_PORT = 8121
DEFAULT_INGESTION_IDENTITY = "service:oauth-ingestion"
DEFAULT_BROKER_IDENTITY = "service:credential-broker"


def _pkce_challenge(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _safe_return_to(value):
    if not isinstance(value, str) or not value.startswith("/"):
        return False
    if value.startswith("//") or "\\" in value:
        return False
    parsed = urlsplit(value)
    return not parsed.scheme and not parsed.netloc


class OAuthService(object):
    def __init__(
        self,
        repository,
        session_repository,
        connector,
        managed_oauth_crypto,
        vault_service,
        clock=None,
        ingestion_identity=DEFAULT_INGESTION_IDENTITY,
        broker_identity=DEFAULT_BROKER_IDENTITY,
        slack_connector=None,
        slack_app_id=None,
        tenant_resolver=None,
    ):
        self.repository = repository
        self.session_repository = session_repository
        self.connector = connector
        self.managed_oauth_crypto = managed_oauth_crypto
        self.vault_service = vault_service
        self.clock = clock or time.time
        self.ingestion_identity = ingestion_identity
        self.broker_identity = broker_identity
        self.slack_connector = slack_connector
        self.slack_app_id = slack_app_id
        self.tenant_resolver = tenant_resolver or (lambda _principal_id: None)

    def _tenant_id(self, current):
        return current.get("tenant_id") or self.tenant_resolver(
            current["principal_id"]
        )

    def slack_status(self, session_id):
        current = self.session_repository.resolve(
            session_id, self.clock(), touch=True
        )
        if current is None:
            return 401, {"error": "authentication required"}
        tenant_id = self._tenant_id(current)
        if not tenant_id:
            return 409, {"error": "tenant membership is required"}
        connections = self.repository.list_tenant_installations(
            tenant_id, "slack"
        )
        return 200, {"provider": "slack", "connections": [
            {
                "connection_id": item["connection_id"],
                "team_id": item["team_id"],
                "team_name": item.get("team_name") or item["team_id"],
                "enterprise_id": item["enterprise_id"],
                "bot_user_id": item["bot_user_id"],
                "status": item["status"],
                "enabled_capabilities": item["enabled_capabilities"],
                "owner": item["principal_id"] == current["principal_id"],
                # The server owns which families exist and what each needs, so
                # the UI can offer an upgrade without keeping its own copy of
                # the capability-to-scope map to drift out of date.
                "missing_families": self._slack_missing_families(item),
            }
            for item in connections
        ]}

    def _slack_missing_families(self, installation):
        registry = self._slack_registry()
        if registry is None:
            return []
        return [
            {
                "family": bundle["family"],
                "missing_scopes": bundle["missing_scopes"],
                "operations": bundle["operations"],
            }
            for bundle in registry.missing_scope_bundles(
                registry.definitions, installation.get("granted_scopes") or (),
            )
        ]

    def _slack_family_request(self, families, target):
        """Turn requested families into the smallest grant that enables them.

        A caller asks for what it wants to do — pin messages — not for the
        capability ids that happen to implement it. When the connection
        already holds some of the scopes, only the absent ones are requested,
        so an upgrade prompt shows what it actually adds.
        """
        if not isinstance(families, list) or not families:
            return None
        registry = self._slack_registry()
        if registry is None:
            return None
        definitions = registry.definitions
        bundles = registry.scope_bundles(definitions)
        if any(family not in bundles for family in families):
            return None
        granted = frozenset((target or {}).get("granted_scopes") or ())
        capabilities, scopes = set(), set()
        for family in sorted(set(families)):
            capabilities |= set(bundles[family]["capabilities"])
            scopes |= set(bundles[family]["scopes"])
        return sorted(capabilities), sorted(scopes - granted)

    def _slack_registry(self):
        if getattr(self, "_slack_operations", None) is None:
            try:
                from agents.orchestrator.slack_operations import (
                    load_slack_operations,
                )
                from libs.integrations.catalog import slack_definitions

                registry = load_slack_operations(slack_definitions())
                registry.definitions = slack_definitions()
                self._slack_operations = registry
            except Exception:
                self._slack_operations = False
        return self._slack_operations or None

    def initiate_slack(self, session_id, csrf_token, body):
        current = self.session_repository.resolve(
            session_id, self.clock(), touch=True
        )
        if current is None:
            return 401, {"error": "authentication required"}
        if not self.session_repository.csrf_matches(session_id, csrf_token):
            return 403, {"error": "invalid CSRF token"}
        if self.slack_connector is None or not self.slack_app_id:
            return 503, {"error": "Slack integration is not configured"}
        if not isinstance(body, dict):
            return 422, {"error": "request body must be an object"}
        tenant_id = self._tenant_id(current)
        if not tenant_id:
            return 409, {"error": "tenant membership is required"}
        target_connection_id = body.get("target_connection_id")
        if target_connection_id:
            target = self.repository.get_installation(
                target_connection_id, tenant_id
            )
            if target is None or target["principal_id"] != current["principal_id"]:
                return 404, {"error": "Slack connection not found"}
        return_to = body.get("return_to", "/integrations")
        if not _safe_return_to(return_to):
            return 422, {"error": "unsafe return target"}
        catalog = self.slack_connector.scope_catalog()
        families = body.get("families")
        if families is not None:
            resolved = self._slack_family_request(
                families, target if target_connection_id else None,
            )
            if resolved is None:
                return 422, {"error": "unsupported or missing families"}
            capabilities, scopes = resolved
            if not scopes:
                return 409, {"error": "requested families are already granted"}
        else:
            capabilities = body.get("capabilities")
            if (
                not isinstance(capabilities, list)
                or not capabilities
                or any(capability not in catalog for capability in capabilities)
            ):
                return 422, {"error": "unsupported or missing capabilities"}
            capabilities = sorted(set(capabilities))
            # A capability can need several scopes; asking for one of them
            # authorises a connection that cannot run what it advertises.
            scopes = sorted(set().union(*(catalog[item] for item in capabilities)))
        state = secrets.token_urlsafe(32)
        self.repository.create_transaction(
            transaction_id=secrets.token_urlsafe(24),
            session_id=session_id,
            principal_id=current["principal_id"],
            provider="slack",
            requested_scopes=scopes,
            requested_capabilities=capabilities,
            state=state,
            pkce_verifier="",
            return_to=return_to,
            now_ts=self.clock(),
            tenant_id=tenant_id,
            app_id=self.slack_app_id,
            intended_team_id=body.get("intended_team_id"),
            target_connection_id=target_connection_id,
        )
        return 200, {"authorization_url": self.slack_connector.authorization_url(
            state, None, scopes
        )}

    def complete_slack(self, session_id, code, state, provider_error=None):
        current = self.session_repository.resolve(
            session_id, self.clock(), touch=True
        )
        if current is None:
            return 401, {"error": "authentication required"}
        transaction = self.repository.consume_transaction(
            state, session_id, current["principal_id"], self.clock()
        )
        if transaction is None or transaction.get("provider") != "slack":
            return 400, {"error": "invalid or consumed OAuth transaction"}
        if provider_error:
            return 200, {"result": "denied", "provider": "slack",
                         "return_to": transaction["return_to"]}
        if not code:
            return 400, {"error": "authorization code is required"}
        try:
            authority = self.slack_connector.exchange_code(code, None)
        except ProviderError:
            return 502, {"error": "Slack token exchange failed"}
        metadata = dict(authority.provider_metadata)
        team_id = metadata.get("team_id")
        if (
            not team_id
            or metadata.get("app_id") != transaction.get("app_id")
            or (
                transaction.get("intended_team_id")
                and transaction["intended_team_id"] != team_id
            )
        ):
            return 409, {"error": "Slack installation identity changed"}
        tenant_id = self._tenant_id(current)
        if not tenant_id or tenant_id != transaction.get("tenant_id"):
            return 409, {"error": "tenant binding changed"}
        previous_installation = next((
            item for item in self.repository.list_tenant_installations(
                tenant_id, "slack", usable_only=False
            )
            if item.get("app_id") == self.slack_app_id
            and item.get("team_id") == team_id
        ), None)
        existing = None
        target_id = transaction.get("target_connection_id")
        if target_id:
            existing = self.repository.get_installation(target_id, tenant_id)
            if (
                existing is None
                or existing["principal_id"] != current["principal_id"]
                or existing["app_id"] != self.slack_app_id
                or existing["team_id"] != team_id
            ):
                return 409, {"error": "scope upgrade target changed"}
        enabled = sorted(
            capability
            for capability, required in self.slack_connector.scope_catalog().items()
            if required.issubset(authority.granted_scopes)
        )
        document = {
            "access_token": authority.access_token,
            "refresh_token": authority.refresh_token,
            "expires_at": int(self.clock()) + authority.expires_in,
            "token_type": authority.token_type,
            "provider_metadata": metadata,
            "granted_scopes": sorted(authority.granted_scopes),
        }
        context = {
            "oauth_transaction_id": transaction["transaction_id"],
            "provider": "slack",
            "tenant_id": tenant_id,
            "user_principal_id": current["principal_id"],
            "team_id": team_id,
            "credential_version": "1",
        }
        try:
            envelope = self.managed_oauth_crypto.seal(
                json.dumps(document, sort_keys=True, separators=(",", ":")),
                context,
                caller_identity=self.ingestion_identity,
            )
            vault_status, vault_response = self.vault_service.store_managed_oauth({
                "user_principal_id": current["principal_id"],
                "provider": "slack",
                "granted_scopes": sorted(authority.granted_scopes),
                "envelope": envelope,
            }, signer=current["principal_id"])
        except ManagedOAuthError:
            return 502, {"error": "credential custody unavailable"}
        if vault_status != 200:
            return 502, {"error": "credential custody unavailable"}
        credential_id = vault_response["credential_id"]
        try:
            connection = self.repository.upsert_installation(
                tenant_id=tenant_id,
                principal_id=current["principal_id"],
                provider="slack",
                app_id=self.slack_app_id,
                team_id=team_id,
                team_name=metadata.get("team_name"),
                enterprise_id=metadata.get("enterprise_id"),
                bot_user_id=metadata.get("bot_user_id"),
                credential_id=credential_id,
                credential_version=1,
                granted_scopes=authority.granted_scopes,
                enabled_capabilities=enabled,
                now_ts=self.clock(),
                connection_id=target_id,
            )
        except ConnectionConflict:
            self.vault_service.delete_managed_oauth_credential(
                credential_id, current["principal_id"]
            )
            return 409, {"error": "Slack workspace is already connected"}
        if (
            previous_installation
            and previous_installation.get("credential_id")
            and previous_installation["credential_id"] != credential_id
        ):
            self.vault_service.delete_managed_oauth_credential(
                previous_installation["credential_id"],
                previous_installation["principal_id"],
            )
        del authority, document
        return 200, {
            "result": "connected",
            "provider": "slack",
            "return_to": transaction["return_to"],
            "connection_id": connection["connection_id"],
            "team_id": team_id,
            "enabled_capabilities": enabled,
        }

    def disconnect_slack(self, session_id, csrf_token, connection_id):
        current = self.session_repository.resolve(
            session_id, self.clock(), touch=True
        )
        if current is None:
            return 401, {"error": "authentication required"}
        if not self.session_repository.csrf_matches(session_id, csrf_token):
            return 403, {"error": "invalid CSRF token"}
        tenant_id = self._tenant_id(current)
        connection = self.repository.get_installation(connection_id, tenant_id)
        if connection is None or connection["principal_id"] != current["principal_id"]:
            return 404, {"error": "Slack connection not found"}
        self.repository.mark_installation_status(
            connection_id, tenant_id, "disconnect_pending", self.clock()
        )
        credential_id = connection["credential_id"]
        status, _ = self.vault_service.begin_managed_oauth_revocation(
            credential_id, current["principal_id"]
        )
        if status != 200:
            return 202, {"status": "disconnect_pending", "provider": "slack"}
        try:
            result = self.vault_service.revoke_managed_oauth(
                credential_id,
                self.broker_identity,
                operation=lambda raw: self.slack_connector.revoke(
                    json.loads(raw.decode("utf-8"))["access_token"]
                ),
            )
        except (ProviderError, KeyError, ValueError, UnicodeDecodeError):
            return 202, {"status": "disconnect_pending", "provider": "slack"}
        if result is not True:
            return 202, {"status": "disconnect_pending", "provider": "slack"}
        if self.vault_service.delete_managed_oauth_credential(
            credential_id, current["principal_id"]
        ) != 200:
            return 202, {"status": "disconnect_pending", "provider": "slack"}
        self.repository.tombstone_installation(connection_id, tenant_id, self.clock())
        return 200, {"status": "disconnected", "provider": "slack",
                     "connection_id": connection_id}

    def google_status(self, session_id):
        current = self.session_repository.resolve(
            session_id, self.clock(), touch=True
        )
        if current is None:
            return 401, {"error": "authentication required"}
        connection = self.repository.get_connection(
            current["principal_id"], PROVIDER
        )
        if connection is None:
            return 200, {"status": "disconnected", "provider": PROVIDER}
        return 200, {
            "status": connection.get("status", "connected"),
            "provider": PROVIDER,
            "enabled_capabilities": connection["enabled_capabilities"],
        }

    def disconnect_google(self, session_id, csrf_token):
        current = self.session_repository.resolve(
            session_id, self.clock(), touch=True
        )
        if current is None:
            return 401, {"error": "authentication required"}
        if not self.session_repository.csrf_matches(session_id, csrf_token):
            return 403, {"error": "invalid CSRF token"}
        connection = self.repository.get_connection(
            current["principal_id"], PROVIDER
        )
        if connection is None:
            return 200, {"status": "disconnected", "provider": PROVIDER}

        credential_id = connection["credential_id"]
        status, _ = self.vault_service.begin_managed_oauth_revocation(
            credential_id, current["principal_id"]
        )
        if status not in (200,):
            return status, {"error": "could not block Google credential"}
        self.repository.mark_pending_revocation(
            current["principal_id"], PROVIDER, self.clock()
        )
        try:
            result = self.vault_service.revoke_managed_oauth(
                credential_id,
                self.broker_identity,
                operation=lambda token: self.connector.revoke(
                    token.decode("utf-8")
                ),
            )
        except ProviderError:
            return 202, {
                "status": "pending_revocation",
                "provider": PROVIDER,
            }
        if result is not True and result != "invalid_token":
            return 202, {
                "status": "pending_revocation",
                "provider": PROVIDER,
            }
        if (
            self.vault_service.delete_managed_oauth_credential(
                credential_id, current["principal_id"]
            )
            != 200
        ):
            return 202, {
                "status": "pending_revocation",
                "provider": PROVIDER,
            }
        self.repository.delete_connection(
            current["principal_id"], PROVIDER, credential_id
        )
        return 200, {"status": "disconnected", "provider": PROVIDER}

    def initiate_google(self, session_id, csrf_token, body):
        current = self.session_repository.resolve(
            session_id, self.clock(), touch=True
        )
        if current is None:
            return 401, {"error": "authentication required"}
        if not self.session_repository.csrf_matches(session_id, csrf_token):
            return 403, {"error": "invalid CSRF token"}
        if not isinstance(body, dict):
            return 422, {"error": "request body must be an object"}

        return_to = body.get("return_to", "/integrations")
        if not _safe_return_to(return_to):
            return 422, {"error": "unsafe return target"}

        capabilities = body.get("capabilities")
        catalog = self.connector.scope_catalog()
        if (
            not isinstance(capabilities, list)
            or not capabilities
            or any(
                not isinstance(capability, str)
                or capability not in catalog
                for capability in capabilities
            )
        ):
            return 422, {"error": "unsupported or missing capabilities"}

        capabilities = sorted(set(capabilities))
        scopes = sorted({catalog[capability] for capability in capabilities})
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        transaction_id = secrets.token_urlsafe(24)
        self.repository.create_transaction(
            transaction_id=transaction_id,
            session_id=session_id,
            principal_id=current["principal_id"],
            provider=PROVIDER,
            requested_scopes=scopes,
            requested_capabilities=capabilities,
            state=state,
            pkce_verifier=verifier,
            return_to=return_to,
            now_ts=self.clock(),
        )
        authorization_url = self.connector.authorization_url(
            state=state,
            code_challenge=_pkce_challenge(verifier),
            scopes=scopes,
        )
        return 200, {"authorization_url": authorization_url}

    def complete_google(
        self, session_id, code, state, provider_error=None
    ):
        current = self.session_repository.resolve(
            session_id, self.clock(), touch=True
        )
        if current is None:
            return 401, {"error": "authentication required"}
        if not isinstance(state, str) or not state:
            return 400, {"error": "invalid or consumed OAuth transaction"}

        transaction = self.repository.consume_transaction(
            state,
            session_id,
            current["principal_id"],
            self.clock(),
        )
        if transaction is None:
            return 400, {"error": "invalid or consumed OAuth transaction"}

        if provider_error:
            return 200, {
                "result": "denied",
                "provider": PROVIDER,
                "return_to": transaction["return_to"],
                "enabled_capabilities": [],
            }
        if not isinstance(code, str) or not code:
            return 400, {"error": "authorization code is required"}

        try:
            authority = self.connector.exchange_code(
                code, transaction["pkce_verifier"]
            )
        except ProviderError:
            return 502, {"error": "Google token exchange failed"}

        granted_scopes = sorted(authority.granted_scopes)
        catalog = self.connector.scope_catalog()
        enabled_capabilities = sorted(
            capability
            for capability, scope in catalog.items()
            if scope in authority.granted_scopes
        )
        existing = self.repository.get_connection(
            current["principal_id"], PROVIDER
        )

        refresh_token = authority.refresh_token
        if refresh_token is not None and (
            not isinstance(refresh_token, str) or not refresh_token
        ):
            return 502, {"error": "Google token exchange failed"}

        if refresh_token:
            encryption_context = {
                "oauth_transaction_id": transaction["transaction_id"],
                "provider": PROVIDER,
                "user_principal_id": current["principal_id"],
            }
            try:
                envelope = self.managed_oauth_crypto.seal(
                    refresh_token,
                    encryption_context,
                    caller_identity=self.ingestion_identity,
                )
                vault_status, vault_response = (
                    self.vault_service.store_managed_oauth(
                        {
                            "user_principal_id": current["principal_id"],
                            "provider": PROVIDER,
                            "granted_scopes": granted_scopes,
                            "envelope": envelope,
                        },
                        signer=current["principal_id"],
                    )
                )
            except ManagedOAuthError:
                return 502, {"error": "credential custody unavailable"}
            if vault_status != 200:
                return 502, {"error": "credential custody unavailable"}
            credential_id = vault_response["credential_id"]
        elif existing is not None:
            # Google commonly omits a replacement refresh token on reconnect.
            # Keep the already-encrypted credential and update only consent
            # metadata/capability availability.
            credential_id = existing["credential_id"]
        else:
            return 502, {"error": "Google did not grant offline access"}

        self.repository.upsert_connection(
            current["principal_id"],
            PROVIDER,
            credential_id,
            granted_scopes,
            enabled_capabilities,
            self.clock(),
        )
        if (
            existing is not None
            and existing["credential_id"] != credential_id
        ):
            retired = self.vault_service.delete_managed_oauth_credential(
                existing["credential_id"], current["principal_id"]
            )
            if retired != 200:
                return 502, {
                    "error": "previous credential custody cleanup failed"
                }
        # Drop the internal authority reference before constructing the
        # browser-safe response; neither bearer token is serialized or logged.
        del authority
        return 200, {
            "result": "connected",
            "provider": PROVIDER,
            "return_to": transaction["return_to"],
            "enabled_capabilities": enabled_capabilities,
        }


class OAuthRequestHandler(BaseHTTPRequestHandler):
    server_version = "TesseraOAuth/1.0"

    def _respond(self, status, body):
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/oauth/slack/connect":
            status, body = self.server.service.initiate_slack(
                session_cookie_value(self.headers.get("Cookie")),
                self.headers.get("X-CSRF-Token"),
                self._json_body(),
            )
            self._respond(status, body)
            return
        if path != "/oauth/google/connect":
            self._respond(404, {"error": "not found"})
            return
        status, body = self.server.service.initiate_google(
            session_cookie_value(self.headers.get("Cookie")),
            self.headers.get("X-CSRF-Token"),
            self._json_body(),
        )
        self._respond(status, body)

    def do_GET(self):
        parts = urlsplit(self.path)
        if parts.path == "/oauth/slack":
            status, body = self.server.service.slack_status(
                session_cookie_value(self.headers.get("Cookie"))
            )
            self._respond(status, body)
            return
        if parts.path == "/oauth/slack/callback":
            query = parse_qs(parts.query)
            status, body = self.server.service.complete_slack(
                session_cookie_value(self.headers.get("Cookie")),
                query.get("code", [None])[0],
                query.get("state", [None])[0],
                provider_error=query.get("error", [None])[0],
            )
            self._respond(status, body)
            return
        if parts.path == "/oauth/google":
            status, body = self.server.service.google_status(
                session_cookie_value(self.headers.get("Cookie"))
            )
            self._respond(status, body)
            return
        if parts.path != "/oauth/google/callback":
            self._respond(404, {"error": "not found"})
            return
        query = parse_qs(parts.query)
        status, body = self.server.service.complete_google(
            session_cookie_value(self.headers.get("Cookie")),
            query.get("code", [None])[0],
            query.get("state", [None])[0],
            provider_error=query.get("error", [None])[0],
        )
        self._respond(status, body)

    def do_DELETE(self):
        path = urlsplit(self.path).path
        if path.startswith("/oauth/slack/"):
            connection_id = path[len("/oauth/slack/"):]
            status, body = self.server.service.disconnect_slack(
                session_cookie_value(self.headers.get("Cookie")),
                self.headers.get("X-CSRF-Token"),
                connection_id,
            )
            self._respond(status, body)
            return
        if path != "/oauth/google":
            self._respond(404, {"error": "not found"})
            return
        status, body = self.server.service.disconnect_google(
            session_cookie_value(self.headers.get("Cookie")),
            self.headers.get("X-CSRF-Token"),
        )
        self._respond(status, body)

    def log_message(self, _format, *_args):
        # OAuth query strings can contain authorization codes and state.
        # Suppress the stdlib's default request-line logging entirely.
        return


def make_server(
    host="127.0.0.1",
    port=DEFAULT_PORT,
    service=None,
    clock=None,
):
    if service is None:
        google = get_google_oauth_config()
        try:
            slack = get_slack_oauth_config()
        except ConfigurationError:
            if any(key.startswith("SLACK_OAUTH_") for key in os.environ):
                raise
            slack = None
        ingestion_identity = os.environ.get(
            "OAUTH_INGESTION_IDENTITY", DEFAULT_INGESTION_IDENTITY
        )
        broker_identity = os.environ.get(
            "CREDENTIAL_BROKER_IDENTITY", DEFAULT_BROKER_IDENTITY
        )
        kms_key_id = os.environ.get("MANAGED_OAUTH_KMS_KEY_ID")
        if not kms_key_id:
            raise RuntimeError("MANAGED_OAUTH_KMS_KEY_ID is required")
        managed_oauth_crypto = ManagedOAuthCrypto(
            AWSKMSClient(),
            kms_key_id,
            ingestion_identities={ingestion_identity},
            broker_identity=broker_identity,
        )
        service = OAuthService(
            repository=OAuthRepository(
                os.environ.get("OAUTH_DATABASE", "tessera-oauth.db")
            ),
            session_repository=SessionRepository(
                os.environ.get("SESSION_DATABASE", "tessera-sessions.db"),
                idle_ttl_seconds=int(
                    os.environ.get("SESSION_IDLE_TTL_SECONDS", "1800")
                ),
                absolute_ttl_seconds=int(
                    os.environ.get("SESSION_ABSOLUTE_TTL_SECONDS", "43200")
                ),
            ),
            connector=GoogleCredentialConnector(
                google.client_id,
                google.client_secret,
                google.redirect_uri,
            ),
            managed_oauth_crypto=managed_oauth_crypto,
            vault_service=VaultService(
                repository=VaultRepository(),
                managed_oauth_crypto=managed_oauth_crypto,
            ),
            clock=clock,
            ingestion_identity=ingestion_identity,
            broker_identity=broker_identity,
            slack_connector=(
                SlackCredentialConnector(
                    slack.client_id, slack.client_secret, slack.redirect_uri
                )
                if slack is not None else None
            ),
            slack_app_id=slack.app_id if slack is not None else None,
            tenant_resolver=_configured_tenant_resolver(),
        )
    server = ThreadingHTTPServer((host, port), OAuthRequestHandler)
    server.service = service
    return server


def _configured_tenant_resolver():
    raw = os.environ.get("TESSERA_PRINCIPAL_TENANTS_JSON", "{}")
    try:
        mapping = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError(
            "TESSERA_PRINCIPAL_TENANTS_JSON must be a JSON object"
        ) from exc
    if not isinstance(mapping, dict):
        raise RuntimeError("TESSERA_PRINCIPAL_TENANTS_JSON must be a JSON object")
    local_tenant = os.environ.get("TESSERA_LOCAL_TENANT_ID")
    local_tenant = (
        local_tenant if isinstance(local_tenant, str) and local_tenant else None
    )

    def resolve(principal_id):
        value = mapping.get(principal_id)
        return value if isinstance(value, str) and value else local_tenant

    return resolve


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    make_server(args.host, args.port).serve_forever()


if __name__ == "__main__":
    main()
