"""First-party, session-bound Google OAuth service (U3)."""

import argparse
import base64
import hashlib
import json
import logging
import os
import re
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from libs.aws_kms import AWSKMSClient
from libs.config import get_google_oauth_config
from libs.config import ConfigurationError, get_slack_oauth_config
from libs.connectors.base import ProviderError
from libs.connectors.google import GoogleCredentialConnector
from libs.connectors.slack import SlackCredentialConnector
from libs.db import Database, bind_organization_id
from libs.identity_repository import IdentityRepository
from libs.tenancy import MembershipTenantResolver, UnmappedPrincipalError
from libs.integrations.catalog import (
    CapabilityUnavailable,
    account_state,
    derive_synthetic_scopes,
)
from services.oauth.repository import (
    ConnectionConflict,
    PkceCipher,
    PostgresOAuthRepository,
)
from services.session.app import session_cookie_value
from services.session.repository import PostgresSessionRepository
from vault.app import VaultService
from vault.managed_oauth_crypto import ManagedOAuthCrypto, ManagedOAuthError
from vault.repository import VaultRepository


logger = logging.getLogger(__name__)

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
        account_connectors=None,
        effect_counts=None,
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
        #: Providers whose credential is an account identifier plus an auth
        #: token, keyed by provider. Absence is a refusal, not a fallback: a
        #: provider with no configured connector cannot be account-connected.
        self.account_connectors = dict(account_connectors or {})
        #: Dispatched, prevented, in-progress and uncertain counts for one
        #: tenant. An emergency stop whose own report cannot say what was
        #: already dispatched is not a control an operator can act on.
        self.effect_counts = effect_counts

    def _tenant_id(self, current):
        """The account this session acts for, or ``None``.

        A principal the configured mapping does not name gets ``None``, and
        every caller below turns that into a refusal rather than reaching for
        a default account. The refusal is the point: the previous fallback
        would have let an unmapped principal install a provider connection
        into a tenant it was never granted, and list back every connection
        already there.
        """
        if current.get("tenant_id"):
            tenant_id = current["tenant_id"]
            bind_organization_id(tenant_id)
            return tenant_id
        try:
            tenant_id = self.tenant_resolver(current["principal_id"])
            bind_organization_id(tenant_id)
            return tenant_id
        except UnmappedPrincipalError:
            bind_organization_id(None)
            logger.warning(
                "refused a request from a principal bound to no tenant"
            )
            return None

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
                # Only this person's own grants: another member's personal
                # consent is not theirs to see.
                "personal_authority": self._slack_personal_authority(
                    tenant_id, item, current["principal_id"],
                ),
            }
            for item in connections
        ]}

    def _record_slack_user_authority(self, tenant_id, connection, principal_id,
                                     user_authority):
        """Store personal consent as its own profile, sealed like any other.

        The user token never joins the connection row. It gets its own vault
        credential and its own profile, so revoking one person's search access
        cannot mean revoking the installation.
        """
        if not user_authority or not hasattr(
            self.repository, "record_authority_profile"
        ):
            return None
        context = {
            "oauth_transaction_id": "user:%s" % connection["connection_id"],
            "provider": "slack",
            "tenant_id": tenant_id,
            "user_principal_id": principal_id,
            "slack_subject_id": user_authority["slack_subject_id"],
            "credential_version": "1",
        }
        try:
            envelope = self.managed_oauth_crypto.seal(
                json.dumps({
                    "access_token": user_authority["access_token"],
                    "refresh_token": user_authority.get("refresh_token"),
                    "expires_at": (
                        int(self.clock()) + int(user_authority["expires_in"])
                        if user_authority.get("expires_in") else None
                    ),
                    "token_type": "user",
                    "granted_scopes": sorted(user_authority["granted_scopes"]),
                }, sort_keys=True, separators=(",", ":")),
                context,
                caller_identity=self.ingestion_identity,
            )
            vault_status, vault_response = self.vault_service.store_managed_oauth({
                "user_principal_id": principal_id,
                "provider": "slack-user",
                "granted_scopes": sorted(user_authority["granted_scopes"]),
                "envelope": envelope,
            }, signer=principal_id)
        except ManagedOAuthError:
            return None
        if vault_status != 200:
            return None
        return self.repository.record_authority_profile(
            tenant_id, connection["connection_id"], "user", principal_id,
            vault_response["credential_id"],
            sorted(user_authority["granted_scopes"]), int(self.clock()),
            slack_subject_id=user_authority["slack_subject_id"],
            # Consent alone does not enable it. Enabling stays a deliberate
            # act, as the unit requires.
            enabled=False,
        )

    def _slack_personal_authority(self, tenant_id, installation, principal_id):
        if not hasattr(self.repository, "list_personal_authority"):
            return []
        return [
            {
                "profile_kind": profile["profile_kind"],
                "slack_subject_id": profile["slack_subject_id"],
                "granted_scopes": profile["granted_scopes"],
                "enabled": profile["enabled"],
            }
            for profile in self.repository.list_personal_authority(
                tenant_id, installation["connection_id"], principal_id,
            )
        ]

    def slack_personal_authority_decision(self, session_id, csrf_token,
                                          connection_id, profile_kind, body):
        """Let a person enable, disable, or withdraw their own grant."""
        current = self.session_repository.resolve(
            session_id, self.clock(), touch=True
        )
        if current is None:
            return 401, {"error": "authentication required"}
        if not self.session_repository.csrf_matches(session_id, csrf_token):
            return 403, {"error": "invalid CSRF token"}
        tenant_id = self._tenant_id(current)
        if not tenant_id:
            return 409, {"error": "tenant membership is required"}
        action = (body or {}).get("action")
        if action not in ("enable", "disable", "revoke"):
            return 422, {"error": "unsupported authority action"}
        if action == "revoke":
            changed = self.repository.revoke_authority_profile(
                tenant_id, connection_id, profile_kind,
                current["principal_id"], self.clock(),
            )
        else:
            changed = self.repository.set_authority_profile_enabled(
                tenant_id, connection_id, profile_kind,
                current["principal_id"], action == "enable", self.clock(),
            )
        if not changed:
            # Either it is not there or it is not theirs; both answer the same
            # so the endpoint cannot be used to discover other people's grants.
            return 404, {"error": "personal authority not found"}
        return 200, {"status": action, "profile_kind": profile_kind}

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

    def _slack_user_scopes(self, capabilities):
        """Scopes that must be asked of the person, not of the workspace."""
        registry = self._slack_registry()
        if registry is None:
            return []
        wanted = set(capabilities or ())
        return sorted({
            scope
            for definition in registry.definitions
            if definition.capability_id in wanted
            and definition.authority_profile == "user"
            for scope in definition.required_scopes
        })

    def _slack_personal_only_round(self, transaction):
        """True when this consent asked for personal scopes and nothing else.

        Read from the requested capabilities rather than the returned payload:
        an install that genuinely came back malformed must stay a failure, not
        be reinterpreted as a personal grant.
        """
        requested = transaction.get("requested_capabilities") or ()
        user_scopes = set(self._slack_user_scopes(requested))
        if not user_scopes:
            return False
        return not (set(transaction.get("requested_scopes") or ()) - user_scopes)

    def control_plane_status(self, session_id):
        """What this account's administrators can switch, and its current state.

        The families come from the operation manifest, so the UI never keeps
        its own copy of which families exist. The state comes from durable
        per-tenant records, so what is shown is what dispatch will actually
        do — not what an environment variable said at boot.
        """
        current = self.session_repository.resolve(
            session_id, self.clock(), touch=True
        )
        if current is None:
            return 401, {"error": "authentication required"}
        tenant_id = self._tenant_id(current)
        if not tenant_id:
            return 409, {"error": "tenant membership is required"}
        state = self.repository.control_plane_state(tenant_id)
        registry = self._slack_registry()
        known = sorted(registry.family_flags) if registry is not None else []
        for family in state["families"]:
            if family not in known:
                known.append(family)
        body = {
            "tenant_id": tenant_id,
            "emergency_stop": state["emergency_stop"],
            "stop_reason": state["stop_reason"],
            "stopped_at": state["stopped_at"],
            "stopped_by_principal_id": state["stopped_by_principal_id"],
            "families": [
                {
                    "family": family,
                    # A family with no row is off. Enabling one is deliberate.
                    "enabled": state["families"].get(family, False),
                }
                for family in sorted(known)
            ],
            "senders": [
                {"sender_id": sender_id, "enabled": enabled}
                for sender_id, enabled in sorted(state["senders"].items())
            ],
        }
        if self.effect_counts is not None:
            try:
                body["effects"] = self.effect_counts(tenant_id)
            except Exception:
                # A missing count is reported as missing. Showing zeros here
                # would tell an operator nothing was prevented when the truth
                # is that nobody counted.
                body["effects"] = None
        return 200, body

    def decide_control_plane(self, session_id, csrf_token, body):
        """Change one switch for the caller's own account, and nothing else.

        The tenant is taken from the session, never from the request body.
        That is the whole of the cross-account defence here: there is no
        argument an administrator could send that names another account.
        """
        current = self.session_repository.resolve(
            session_id, self.clock(), touch=True
        )
        if current is None:
            return 401, {"error": "authentication required"}
        if not self.session_repository.csrf_matches(session_id, csrf_token):
            return 403, {"error": "invalid CSRF token"}
        tenant_id = self._tenant_id(current)
        if not tenant_id:
            return 409, {"error": "tenant membership is required"}
        if not isinstance(body, dict):
            return 422, {"error": "request body must be an object"}
        action = body.get("action")
        enabled = body.get("enabled")
        now = self.clock()
        if action == "emergency_stop":
            if not isinstance(enabled, bool):
                return 422, {"error": "enabled must be boolean"}
            self.repository.set_emergency_stop(
                tenant_id, enabled, now,
                reason=body.get("reason"),
                acting_principal_id=current["principal_id"],
            )
        elif action == "family":
            family = body.get("family")
            if not isinstance(family, str) or not family:
                return 422, {"error": "a family is required"}
            if not isinstance(enabled, bool):
                return 422, {"error": "enabled must be boolean"}
            registry = self._slack_registry()
            if registry is not None and family not in registry.family_flags:
                return 422, {"error": "unknown capability family"}
            self.repository.set_capability_family_enabled(
                tenant_id, family, enabled, now,
                acting_principal_id=current["principal_id"],
            )
        elif action == "sender":
            sender_id = body.get("sender_id")
            if not isinstance(sender_id, str) or not sender_id:
                return 422, {"error": "a sender is required"}
            if not isinstance(enabled, bool):
                return 422, {"error": "enabled must be boolean"}
            self.repository.set_control_plane_sender_enabled(
                tenant_id, sender_id, enabled, now,
                family=body.get("family") or "",
                acting_principal_id=current["principal_id"],
            )
        else:
            return 422, {"error": "unsupported control plane action"}
        return self.control_plane_status(session_id)

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
        if (not tenant_id and getattr(
                self.repository, "requires_tenant_context", False)):
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
        user_scopes = self._slack_user_scopes(capabilities)
        # A personal scope must not be requested as the workspace's, or the
        # install would hold authority nobody consented to as themselves.
        bot_scopes = sorted(set(scopes) - set(user_scopes))
        return 200, {"authorization_url": self.slack_connector.authorization_url(
            state, None, bot_scopes, user_scopes=user_scopes or None,
        )}

    def complete_slack(self, session_id, code, state, provider_error=None):
        current = self.session_repository.resolve(
            session_id, self.clock(), touch=True
        )
        if current is None:
            return 401, {"error": "authentication required"}
        tenant_id = self._tenant_id(current)
        if (not tenant_id and getattr(
                self.repository, "requires_tenant_context", False)):
            return 409, {"error": "tenant membership is required"}
        transaction = self.repository.consume_transaction(
            state, session_id, current["principal_id"], self.clock()
        )
        if transaction is None or transaction.get("provider") != "slack":
            logger.warning(
                "Slack callback refused: OAuth transaction was invalid or "
                "already consumed"
            )
            return 400, {"error": "invalid or consumed OAuth transaction"}
        if provider_error:
            return 200, {"result": "denied", "provider": "slack",
                         "return_to": transaction["return_to"]}
        if not code:
            return 400, {"error": "authorization code is required"}
        # A round that asked only for personal scopes gets no bot token back,
        # and must not be treated as an install. Deciding this from what was
        # requested — not from what came back — keeps a genuinely malformed
        # bot response distinguishable from a correct personal one.
        personal_only = self._slack_personal_only_round(transaction)
        try:
            if hasattr(self.slack_connector, "exchange_code_with_user"):
                authority, user_authority = (
                    self.slack_connector.exchange_code_with_user(
                        code, require_bot=not personal_only,
                    )
                )
            elif personal_only:
                logger.warning(
                    "Slack callback refused: personal-scope round needs a "
                    "connector that returns the authed_user block"
                )
                return 502, {"error": "Slack token exchange failed"}
            else:
                authority, user_authority = (
                    self.slack_connector.exchange_code(code, None), None
                )
        except ProviderError:
            # A refused callback used to redirect to a bare "callback-failed"
            # and record nothing anywhere, which left an operator with a broken
            # connection and no way to learn why.
            logger.exception("Slack token exchange failed")
            return 502, {"error": "Slack token exchange failed"}
        if personal_only:
            return self._complete_slack_personal_consent(
                current, transaction, user_authority,
            )
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
            logger.warning(
                "Slack callback refused: installation identity changed "
                "(team=%s app=%s expected_app=%s intended_team=%s)",
                team_id, metadata.get("app_id"), transaction.get("app_id"),
                transaction.get("intended_team_id"),
            )
            return 409, {"error": "Slack installation identity changed"}
        tenant_id = self._tenant_id(current)
        if not tenant_id or tenant_id != transaction.get("tenant_id"):
            logger.warning(
                "Slack callback refused: tenant binding changed "
                "(session=%s transaction=%s)",
                tenant_id, transaction.get("tenant_id"),
            )
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
                logger.warning(
                    "Slack callback refused: scope upgrade target changed "
                    "(target=%s found=%s)",
                    target_id, bool(existing),
                )
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
            # Named, because a credential that vanishes should say which path
            # removed it rather than leaving the connection quietly unusable.
            logger.warning(
                "deleting managed OAuth credential: slack_connection_conflict "
                "credential=%s", credential_id,
            )
            self.vault_service.delete_managed_oauth_credential(
                credential_id, current["principal_id"]
            )
            return 409, {"error": "Slack workspace is already connected"}
        if (
            previous_installation
            and previous_installation.get("credential_id")
            and previous_installation["credential_id"] != credential_id
        ):
            logger.warning(
                "deleting managed OAuth credential: slack_previous_retired "
                "credential=%s replaced_by=%s",
                previous_installation["credential_id"], credential_id,
            )
            self.vault_service.delete_managed_oauth_credential(
                previous_installation["credential_id"],
                previous_installation["principal_id"],
            )
        self._record_slack_user_authority(
            tenant_id, connection, current["principal_id"], user_authority,
        )
        del authority, document, user_authority
        return 200, {
            "result": "connected",
            "provider": "slack",
            "return_to": transaction["return_to"],
            "connection_id": connection["connection_id"],
            "team_id": team_id,
            "enabled_capabilities": enabled,
        }

    def _complete_slack_personal_consent(self, current, transaction,
                                         user_authority):
        """Attach personal consent to an existing install, and nothing more.

        This round grants one person's own authority. It must not create,
        replace or retire the workspace installation's credential, because
        nobody consented to reinstalling the app by agreeing to search as
        themselves.
        """
        tenant_id = self._tenant_id(current)
        if not tenant_id or tenant_id != transaction.get("tenant_id"):
            logger.warning(
                "Slack personal consent refused: tenant binding changed "
                "(session=%s transaction=%s)",
                tenant_id, transaction.get("tenant_id"),
            )
            return 409, {"error": "tenant binding changed"}
        target_id = transaction.get("target_connection_id")
        connection = (
            self.repository.get_installation(target_id, tenant_id)
            if target_id else None
        )
        if (
            connection is None
            or connection["principal_id"] != current["principal_id"]
        ):
            logger.warning(
                "Slack personal consent refused: no installation to attach to "
                "(target=%s)", target_id,
            )
            return 409, {"error": "personal consent target changed"}
        profile = self._record_slack_user_authority(
            tenant_id, connection, current["principal_id"], user_authority,
        )
        del user_authority
        if profile is None:
            return 502, {"error": "credential custody unavailable"}
        return 200, {
            "result": "connected",
            "provider": "slack",
            "return_to": transaction["return_to"],
            "connection_id": connection["connection_id"],
            "team_id": connection["team_id"],
            "enabled_capabilities": connection["enabled_capabilities"],
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

    def _account_capabilities(self, connector, scopes):
        """Capabilities the derived scopes actually cover, and no others."""
        catalog = connector.scope_catalog()
        held = set(scopes)
        return sorted(
            capability for capability, required in catalog.items()
            if required and set(required).issubset(held)
        )

    def connect_provider_account(self, session_id, csrf_token, body):
        """Connect a provider whose credential is an account plus a token.

        Nothing about this path is OAuth-shaped: there is no redirect, no code
        to exchange, and no consent callback to read authority out of. The
        account is verified instead, and the scopes recorded on the connection
        are derived from what it verifiably holds. The credential version
        starts at one and means only that this is the first sealing of this
        secret.
        """
        current = self.session_repository.resolve(
            session_id, self.clock(), touch=True
        )
        if current is None:
            return 401, {"error": "authentication required"}
        if not self.session_repository.csrf_matches(session_id, csrf_token):
            return 403, {"error": "invalid CSRF token"}
        if not isinstance(body, dict):
            return 422, {"error": "request body must be an object"}
        provider = body.get("provider")
        connector = self.account_connectors.get(provider)
        if connector is None:
            return 503, {"error": "provider is not configured"}
        tenant_id = self._tenant_id(current)
        if (not tenant_id and getattr(
                self.repository, "requires_tenant_context", False)):
            return 409, {"error": "tenant membership is required"}
        account_id = body.get("account_id")
        auth_token = body.get("auth_token")
        if not isinstance(account_id, str) or not account_id:
            return 422, {"error": "an account identifier is required"}
        if not isinstance(auth_token, str) or not auth_token:
            return 422, {"error": "an account auth token is required"}
        try:
            state = account_state(connector.verify_account(account_id, auth_token))
        except (ProviderError, CapabilityUnavailable):
            return 502, {"error": "provider account could not be verified"}
        if state.account_id != account_id or state.provider != provider:
            return 409, {"error": "provider account identity does not match"}
        if state.status != "verified":
            # Unverified is not a lesser connection, it is no connection: an
            # account that cannot be checked must not hold sealed authority.
            return 409, {
                "error": "provider account is not verified",
                "account_status": state.status,
            }
        scopes = sorted(derive_synthetic_scopes(state))
        if not scopes:
            if provider == "twilio":
                return 409, {
                    "error": (
                        "Twilio account has no SMS- or Voice-capable incoming "
                        "phone numbers; add or transfer a number to this account"
                    ),
                    "provider": provider,
                    "account_status": state.status,
                }
            return 409, {"error": "provider account carries no authority"}
        capabilities = self._account_capabilities(connector, scopes)
        document = {
            "account_id": account_id,
            "auth_token": auth_token,
            "granted_scopes": scopes,
            "token_type": "account",
        }
        context = {
            "provider": provider,
            "tenant_id": tenant_id,
            "user_principal_id": current["principal_id"],
            "provider_account_id": account_id,
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
                "provider": provider,
                "granted_scopes": scopes,
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
                provider=provider,
                app_id=account_id,
                credential_id=credential_id,
                credential_version=1,
                granted_scopes=scopes,
                enabled_capabilities=capabilities,
                now_ts=self.clock(),
            )
        except ConnectionConflict:
            self.vault_service.delete_managed_oauth_credential(
                credential_id, current["principal_id"]
            )
            return 409, {"error": "provider account is already connected"}
        if hasattr(self.repository, "record_verified_account"):
            self.repository.record_verified_account(
                tenant_id, connection["connection_id"], provider, account_id,
                state,
            )
        del document, auth_token
        return 200, {
            "result": "connected",
            "provider": provider,
            "connection_id": connection["connection_id"],
            "provider_account_id": account_id,
            "effective_scopes": scopes,
            "enabled_capabilities": capabilities,
        }

    def provider_account_status(self, session_id, provider):
        current = self.session_repository.resolve(
            session_id, self.clock(), touch=True
        )
        if current is None:
            return 401, {"error": "authentication required"}
        if provider not in self.account_connectors:
            return 404, {"error": "provider is not configured"}
        tenant_id = self._tenant_id(current)
        if not tenant_id:
            return 409, {"error": "tenant membership is required"}
        connections = self.repository.list_tenant_installations(
            tenant_id, provider, usable_only=False
        )
        return 200, {
            "provider": provider,
            "status": "connected" if connections else "disconnected",
            "connections": [{
                "connection_id": item["connection_id"],
                "provider_account_id": item.get("app_id"),
                "status": item["status"],
                "enabled_capabilities": item.get("enabled_capabilities", []),
                "owner": item["principal_id"] == current["principal_id"],
            } for item in connections],
        }

    def voice_routes(self, session_id):
        current = self.session_repository.resolve(session_id, self.clock(), touch=True)
        if current is None:
            return 401, {"error": "authentication required"}
        tenant_id = self._tenant_id(current)
        if not tenant_id:
            return 409, {"error": "tenant membership is required"}
        return 200, {"routes": self.repository.voice_routes(tenant_id)}

    def save_voice_routes(self, session_id, csrf_token, body):
        current = self.session_repository.resolve(session_id, self.clock(), touch=True)
        if current is None:
            return 401, {"error": "authentication required"}
        if not self.session_repository.csrf_matches(session_id, csrf_token):
            return 403, {"error": "invalid CSRF token"}
        tenant_id = self._tenant_id(current)
        routes = body.get("routes") if isinstance(body, dict) else None
        if not tenant_id or not isinstance(routes, list) or len(routes) > 100:
            return 422, {"error": "voice routes are invalid"}
        required = {"route_id", "department", "language", "destination", "timezone", "start_hour",
                    "end_hour", "ring_seconds", "total_budget_seconds", "priority"}
        for route in routes:
            if not isinstance(route, dict) or set(route) != required:
                return 422, {"error": "voice route fields are invalid"}
            if not re.match(r"^\+[1-9][0-9]{7,14}$", str(route["destination"])):
                return 422, {"error": "voice destination must use E.164"}
            if not all(isinstance(route[name], str) and route[name] for name in ("route_id", "department", "language", "timezone")):
                return 422, {"error": "voice route labels are invalid"}
            if not all(type(route[name]) is int for name in ("start_hour", "end_hour", "ring_seconds", "total_budget_seconds", "priority")):
                return 422, {"error": "voice route timing is invalid"}
        self.repository.replace_voice_routes(tenant_id, routes)
        return 200, {"routes": self.repository.voice_routes(tenant_id)}

    def apply_verified_account_state(self, tenant_id, connection_id, state):
        """Re-derive a connection's authority from fresh account state.

        Re-verification, not a callback: account state moves when a sender is
        disabled or a family is withdrawn, and nobody visits a browser when it
        does. Scope removal is the whole mechanism — a sender that is gone
        stops appearing in the derived set, so every in-flight binding naming
        it fails the subset check the policy evaluator already runs, while
        bindings naming a different sender on the same connection are
        untouched.

        The credential version is passed through unchanged on purpose. It
        answers whether the sealed secret is still the one the binding was made
        against, and re-verifying an account does not replace a secret.
        Bumping it here would fail every queued effect on the connection, in
        every family, with a reason that reads as tampering.
        """
        installation = self.repository.get_installation(connection_id, tenant_id)
        if installation is None:
            return 404, {"error": "connection not found"}
        try:
            state = account_state(state)
        except CapabilityUnavailable:
            return 422, {"error": "verified account state is malformed"}
        if installation["provider"] != state.provider:
            return 409, {"error": "provider account identity does not match"}
        connector = self.account_connectors.get(state.provider)
        if connector is None:
            return 503, {"error": "provider is not configured"}
        scopes = sorted(derive_synthetic_scopes(state))
        capabilities = self._account_capabilities(connector, scopes)
        connection = self.repository.upsert_installation(
            tenant_id=tenant_id,
            principal_id=installation["principal_id"],
            provider=state.provider,
            app_id=installation["app_id"],
            credential_id=installation["credential_id"],
            credential_version=installation["credential_version"],
            granted_scopes=scopes,
            enabled_capabilities=capabilities,
            now_ts=self.clock(),
            connection_id=connection_id,
        )
        if hasattr(self.repository, "record_verified_account"):
            self.repository.record_verified_account(
                tenant_id, connection_id, state.provider, state.account_id,
                state,
            )
        return 200, {
            "result": "reverified",
            "provider": state.provider,
            "connection_id": connection["connection_id"],
            "account_status": state.status,
            "effective_scopes": scopes,
            "enabled_capabilities": capabilities,
            "credential_version": connection["credential_version"],
        }

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
        tenant_id = self._tenant_id(current)
        if (not tenant_id and getattr(
                self.repository, "requires_tenant_context", False)):
            return 409, {"error": "tenant membership is required"}

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
            tenant_id=tenant_id,
            app_id="google",
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
        tenant_id = self._tenant_id(current)
        if (not tenant_id and getattr(
                self.repository, "requires_tenant_context", False)):
            return 409, {"error": "tenant membership is required"}
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
        if path == "/oauth/control-plane":
            status, body = self.server.service.decide_control_plane(
                session_cookie_value(self.headers.get("Cookie")),
                self.headers.get("X-CSRF-Token"),
                self._json_body(),
            )
            self._respond(status, body)
            return
        if path == "/oauth/account/connect":
            status, body = self.server.service.connect_provider_account(
                session_cookie_value(self.headers.get("Cookie")),
                self.headers.get("X-CSRF-Token"),
                self._json_body(),
            )
            self._respond(status, body)
            return
        if path == "/oauth/voice/routes":
            status, body = self.server.service.save_voice_routes(
                session_cookie_value(self.headers.get("Cookie")),
                self.headers.get("X-CSRF-Token"), self._json_body(),
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
        if parts.path == "/oauth/control-plane":
            status, body = self.server.service.control_plane_status(
                session_cookie_value(self.headers.get("Cookie"))
            )
            self._respond(status, body)
            return
        if parts.path == "/oauth/account":
            query = parse_qs(parts.query)
            status, body = self.server.service.provider_account_status(
                session_cookie_value(self.headers.get("Cookie")),
                query.get("provider", [None])[0],
            )
            self._respond(status, body)
            return
        if parts.path == "/oauth/voice/routes":
            status, body = self.server.service.voice_routes(
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
            # Decoded, because a connection id contains a colon and every
            # caller percent-encodes it. Reading the raw segment looked up
            # "conn%3A..." and reported 404 on a connection that exists,
            # which made disconnecting impossible from the browser.
            connection_id = unquote(path[len("/oauth/slack/"):])
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
        database = Database()
        pkce_key = os.environ.get("OAUTH_TRANSACTION_ENCRYPTION_KEY")
        if not pkce_key:
            raise RuntimeError("OAUTH_TRANSACTION_ENCRYPTION_KEY is required")
        service = OAuthService(
            repository=PostgresOAuthRepository(
                database, PkceCipher(pkce_key)
            ),
            session_repository=PostgresSessionRepository(
                database,
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
            effect_counts=_effect_counts(),
            account_connectors=_default_account_connectors(),
        )
    server = ThreadingHTTPServer((host, port), OAuthRequestHandler)
    server.service = service
    return server


def _default_account_connectors():
    """Account-credential providers installed in the real OAuth process."""
    from libs.connectors.twilio import TwilioCredentialConnector

    return {
        "twilio": TwilioCredentialConnector(
            expected_callback_base=os.environ.get("TWILIO_PUBLIC_CALLBACK_BASE")
        )
    }


def _effect_counts():
    """Read-only view of what happened to this tenant's effects.

    An administrator reaching for the emergency stop is asking a question the
    switch itself cannot answer: what already went out. The workflow store
    holds that, so the control-plane surface reads it rather than inventing a
    second ledger that could disagree with the first.
    """
    from agents.orchestrator.workflow_repository import WorkflowRepository

    workflows = WorkflowRepository.from_environment(
        os.environ.get("WORKFLOW_DATABASE", "tessera-workflows.db"),
        os.environ.get("TESSERA_CONCIERGE_IDENTITY", "service:concierge"),
    )

    def counts(tenant_id):
        return workflows.effect_disposition_counts(tenant_id)

    return counts


def _configured_tenant_resolver(identity_repository=None):
    raw = os.environ.get("TESSERA_PRINCIPAL_TENANTS_JSON", "{}")
    try:
        mapping = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError(
            "TESSERA_PRINCIPAL_TENANTS_JSON must be a JSON object"
        ) from exc
    if not isinstance(mapping, dict):
        raise RuntimeError("TESSERA_PRINCIPAL_TENANTS_JSON must be a JSON object")

    return MembershipTenantResolver(
        mapping, identity_repository or IdentityRepository()
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    make_server(args.host, args.port).serve_forever()


if __name__ == "__main__":
    main()
