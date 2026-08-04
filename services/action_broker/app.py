"""Action broker: validates leases/approvals and executes provider calls."""

import argparse
import hmac
import importlib
import json
import logging
import os
import time
import jsonschema
from dataclasses import asdict, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from agents.orchestrator.approval import requires_action_approval
from libs.connectors.base import ProviderError, ProviderNetworkError
from libs.connectors.slack import SlackAPIError, SlackRateLimitError
from libs.integrations.catalog import (
    CapabilityUnavailable,
    ConnectionCapabilitySnapshot,
)
from runner.trust_challenge import prove_identity
from services.session.app import session_cookie_value
from vault.managed_oauth_crypto import ManagedOAuthError

logger = logging.getLogger(__name__)


BROKER_IDENTITY = "service:credential-broker"

_FORBIDDEN_RECEIPT_KEYS = frozenset({
    "access_token", "refresh_token", "authorization", "token",
})
_MAX_RECEIPT_DEPTH = 8
_MAX_RECEIPT_ITEMS = 1_000
_MAX_RECEIPT_SERIALIZED_BYTES = 64 * 1_024


def _safe_receipt(value):
    if is_dataclass(value):
        value = asdict(value)
    if not isinstance(value, dict):
        raise ValueError("provider result must be a filtered object or receipt")

    item_count = [0]

    def inspect(node, depth):
        if depth > _MAX_RECEIPT_DEPTH:
            raise ValueError("provider result exceeds receipt depth limit")
        if isinstance(node, dict):
            item_count[0] += len(node)
            if item_count[0] > _MAX_RECEIPT_ITEMS:
                raise ValueError("provider result exceeds receipt item limit")
            for key, nested in node.items():
                if str(key).casefold() in _FORBIDDEN_RECEIPT_KEYS:
                    raise ValueError(
                        "provider result contains forbidden authority material"
                    )
                inspect(nested, depth + 1)
        elif isinstance(node, (list, tuple)):
            item_count[0] += len(node)
            if item_count[0] > _MAX_RECEIPT_ITEMS:
                raise ValueError("provider result exceeds receipt item limit")
            for nested in node:
                inspect(nested, depth + 1)

    inspect(value, 0)
    try:
        serialized = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("provider result must be JSON-safe") from exc
    if len(serialized) > _MAX_RECEIPT_SERIALIZED_BYTES:
        raise ValueError("provider result exceeds receipt size limit")
    return value


def _safe_provider_error(exc):
    body = {"error": "provider operation failed safely", "outcome_certainty": "safe"}
    if isinstance(exc, SlackRateLimitError):
        body["error"] = "rate_limited"
        body["category"] = "rate_limit"
        body["retry_after"] = int(exc.retry_after)
        return 429, body
    if isinstance(exc, SlackAPIError):
        body["error"] = exc.code
        body["category"] = exc.category
        statuses = {
            "auth": 403,
            "scope": 403,
            "permission": 403,
            "membership": 403,
            "validation": 422,
            "provider": 409,
            "transient": 503,
        }
        return statuses.get(exc.category, 409), body
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is not None:
        body["retry_after"] = int(retry_after)
    if isinstance(exc, PermissionError):
        return 403, body
    if isinstance(exc, ProviderNetworkError):
        return 503, body
    if isinstance(exc, KeyError):
        # The connection still calls itself healthy, but its credential is
        # gone from the vault. Retrying cannot fix that; only reconnecting
        # can, so say which one this is instead of reporting a provider fault.
        body["error"] = "credential_unavailable"
        body["category"] = "auth"
        body["recovery"] = "reconnect_integration"
        return 403, body
    # Anything reaching here is unclassified, so the response alone says
    # nothing about what went wrong. Name the exception type in the body and
    # log it with a traceback: a silent 502 turns a one-line configuration
    # fault into an afternoon of bisecting the dispatch path.
    body["error_class"] = type(exc).__name__
    logger.exception("unclassified provider failure: %s", type(exc).__name__)
    return 502, body


class ActionBroker(object):
    def __init__(
        self,
        action_repository,
        session_repository,
        vault_service,
        executor,
        clock=None,
        broker_identity=BROKER_IDENTITY,
        identity_verifier=prove_identity,
        agent_url_resolver=None,
        credential_authorizer=None,
        credential_connector=None,
        attestor=None,
        evidence_submitter=None,
        runtime_registry=None,
        rollout_version="production-v1",
        credential_rotators=None,
        dispatch_policy=None,
        policy_evaluator=None,
        connection_resolver=None,
    ):
        self.actions = action_repository
        self.sessions = session_repository
        self.vault = vault_service
        self.executor = executor
        self.clock = clock or time.time
        self.broker_identity = broker_identity
        self.identity_verifier = identity_verifier
        self.agent_url_resolver = agent_url_resolver
        self.credential_authorizer = credential_authorizer
        self.credential_connector = credential_connector
        self.attestor = attestor
        self.evidence_submitter = evidence_submitter
        self.runtime_registry = runtime_registry
        self.rollout_version = rollout_version
        self.credential_rotators = credential_rotators or {}
        self.dispatch_policy = dispatch_policy or (lambda _binding: True)
        self.policy_evaluator = policy_evaluator
        self.connection_resolver = connection_resolver

    def decide(self, session_id, csrf_token, proposal_id, body):
        current = self.sessions.resolve(session_id, self.clock(), touch=True)
        if current is None:
            return 401, {"error": "authentication required"}
        if not self.sessions.csrf_matches(session_id, csrf_token):
            return 403, {"error": "invalid CSRF token"}
        if not isinstance(body, dict) or not isinstance(body.get("version"), int):
            return 422, {"error": "proposal version is required"}
        approved = body.get("approved")
        if not isinstance(approved, bool):
            return 422, {"error": "approved must be boolean"}
        changed = self.actions.decide(
            proposal_id,
            body["version"],
            current["principal_id"],
            approved,
            self.clock(),
        )
        if not changed:
            return 409, {"error": "proposal is expired, changed, or already decided"}
        return 200, {"status": "approved" if approved else "rejected"}

    def execute(self, lease, binding, payload):
        """Execute without ever returning the provider token to the caller."""
        if not self.actions.validate_lease(lease, binding, self.clock()):
            return 403, {"error": "missing, expired, or mismatched capability lease"}
        if not self.dispatch_policy(binding):
            return 403, {"error": "capability rollout is disabled"}
        capability_id = binding["capability_id"]
        runtime_binding = None
        if self.runtime_registry is not None:
            try:
                snapshot = ConnectionCapabilitySnapshot.from_mapping(
                    binding.get("connection_snapshot")
                )
                if snapshot.connection_id != binding.get("connection_id"):
                    raise CapabilityUnavailable("connection binding changed")
                if snapshot.tenant_id != binding.get("tenant_id"):
                    raise CapabilityUnavailable("tenant binding changed")
                runtime_binding = self.runtime_registry.resolve(
                    snapshot, self.rollout_version
                )
            except (CapabilityUnavailable, TypeError):
                return 403, {"error": "capability snapshot is unavailable or stale"}
        side_effecting = (
            runtime_binding.definition.effect == "write"
            if runtime_binding is not None
            else requires_action_approval(capability_id)
        )
        if runtime_binding is not None:
            try:
                jsonschema.validate(payload, runtime_binding.definition.input_schema)
            except jsonschema.ValidationError:
                return 422, {"error": "payload does not match capability schema"}
        if (
            self.credential_authorizer is None
            or not self.credential_authorizer(binding)
        ):
            return 403, {
                "error": "credential is not active for this user and capability"
            }
        dynamic = binding.get("workflow_revision_id") not in (None, "legacy")
        if self.credential_connector is None and self.runtime_registry is None:
            return 503, {"error": "credential refresh is not configured"}
        proposal = None
        if side_effecting:
            agent_url = (
                self.agent_url_resolver(binding["agent_principal_id"])
                if self.agent_url_resolver is not None
                else None
            )
            if not agent_url:
                return 403, {"error": "agent endpoint is not trusted"}
            if not self.identity_verifier(
                agent_url,
                binding.get("agent_principal_id"),
            ):
                return 403, {"error": "agent identity could not be re-verified"}
            existing = self.actions.get_by_idempotency_key(
                binding["idempotency_key"]
            )
            if not _binding_matches(existing, binding):
                return 403, {"error": "action binding does not match proposal"}
            if existing["status"] == "completed":
                if existing.get("broker_response") is not None:
                    return 200, dict(existing["broker_response"])
                return 200, {"receipt": existing["receipt"]}
            if existing["status"] in ("executing", "execution_unknown"):
                return 202, {"status": existing["status"]}
            if canonical_hash(payload) != existing["payload_hash"]:
                return 403, {"error": "payload does not match approved proposal"}
        if dynamic:
            if self.policy_evaluator is None or self.connection_resolver is None:
                return 403, {
                    "error": "dynamic policy decision is stale or denied"
                }
            live_connection = self.connection_resolver(
                binding.get("connection_id"), binding.get("tenant_id")
            )
            current_decision = self.policy_evaluator.evaluate(
                binding, live_connection, self.clock()
            )
            if (
                not current_decision["allowed"]
                or binding.get("policy_decision") != current_decision
            ):
                return 403, {
                    "error": "dynamic policy decision is stale or denied"
                }
        if side_effecting:
            proposal = self.actions.consume_approval(binding, self.clock())
            if proposal is None:
                return 403, {"error": "exact action approval is required"}
        if not self.actions.consume_lease(lease, binding, self.clock()):
            if proposal is not None:
                self.actions.recover_pre_dispatch_claim(
                    proposal["proposal_id"], proposal["version"]
                )
            return 403, {"error": "capability lease was already consumed"}
        provider_dispatch_started = False
        try:
            connector = (
                runtime_binding.connector
                if runtime_binding is not None
                else self.credential_connector
            )
            executor = (
                runtime_binding.executor
                if runtime_binding is not None
                else self.executor
            )
            provider = (
                runtime_binding.definition.provider
                if runtime_binding is not None else "google"
            )
            rotator = self.credential_rotators.get(provider)
            if rotator is not None:
                rotator.rotate(
                    binding.get("connection_id"),
                    binding["credential_id"],
                    self.broker_identity,
                )

            def provider_operation(refresh_token):
                nonlocal provider_dispatch_started
                if provider == "slack":
                    try:
                        document = json.loads(refresh_token.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError) as exc:
                        raise PermissionError("Slack credential document is invalid") from exc
                    access_token = document.get("access_token")
                    if not isinstance(access_token, str) or not access_token:
                        raise PermissionError("Slack access authority is unavailable")
                    authority_scopes = frozenset(document.get("granted_scopes", ()))
                else:
                    authority = connector.refresh(refresh_token.decode("utf-8"))
                    access_token = authority.access_token
                    authority_scopes = authority.granted_scopes
                required_scope = (
                    next(iter(runtime_binding.definition.required_scopes), None)
                    if runtime_binding is not None
                    else connector.scope_catalog().get(capability_id)
                )
                if required_scope is None:
                    raise PermissionError("capability has no provider scope")
                if (
                    authority_scopes
                    and required_scope not in authority_scopes
                ):
                    raise PermissionError(
                        "provider did not grant the required scope"
                    )
                context = {
                    "access_token": access_token,
                    "connection_id": binding.get("connection_id"),
                    "team_id": binding.get("team_id"),
                    "bot_user_id": binding.get("bot_user_id"),
                }
                if side_effecting:
                    if proposal is None or not self.actions.mark_dispatched(
                        proposal["proposal_id"], proposal["version"], self.clock()
                    ):
                        raise PermissionError(
                            "provider dispatch claim is no longer valid"
                        )
                    provider_dispatch_started = True
                    value = executor.execute(capability_id, payload, context)
                else:
                    value = executor.read(capability_id, payload, context)
                return _safe_receipt(value)

            receipt = self.vault.use_managed_oauth(
                binding["credential_id"],
                self.broker_identity,
                provider_operation,
            )
        except (
            ManagedOAuthError,
            ProviderError,
            PermissionError,
            KeyError,
            UnicodeDecodeError,
            ValueError,
        ) as exc:
            outcome_unknown = bool(
                side_effecting
                and provider_dispatch_started
                and isinstance(exc, ProviderNetworkError)
            )
            if proposal is not None:
                self.actions.fail_execution(
                    proposal["proposal_id"],
                    proposal["version"],
                    exc,
                    self.clock(),
                    unknown=outcome_unknown,
                )
            if outcome_unknown:
                return 202, {"status": "execution_unknown"}
            return _safe_provider_error(exc)

        if side_effecting and proposal is not None and self.attestor is not None:
            response = self._evidence_response(binding, payload, receipt)
            self.actions.complete_execution(
                proposal["proposal_id"],
                proposal["version"],
                receipt,
                self.clock(),
                broker_response=response,
            )
            return 200, response
        if proposal is not None:
            self.actions.complete_execution(
                proposal["proposal_id"],
                proposal["version"],
                receipt,
                self.clock(),
            )
        return 200, {"receipt": receipt}

    def _evidence_response(self, binding, payload, receipt):
        capability_id = binding["capability_id"]
        attestation = self.attestor.create(
            task_id=binding["task_id"],
            user_principal_id=binding["user_principal_id"],
            agent_principal_id=binding["agent_principal_id"],
            credential_id=binding["credential_id"],
            capability_id=capability_id,
            approved_payload_hash=binding["payload_hash"],
            provider_receipt=receipt,
            idempotency_key=binding["idempotency_key"],
            executed_at=self.clock(),
            outcome="succeeded",
            approved_payload=payload,
        )
        evidence = {
            "evidence_id": attestation["attestation_id"],
            "capability_id": capability_id,
            "execution_attestation": attestation,
        }
        response = {
            "receipt": receipt,
            "execution_attestation": attestation,
            "evidence_status": "pending",
        }
        if self.evidence_submitter is None:
            return response
        try:
            submitted = self.evidence_submitter(evidence)
            if (
                isinstance(submitted, tuple)
                and len(submitted) == 2
                and isinstance(submitted[1], dict)
            ):
                submit_status, submit_body = submitted
            elif isinstance(submitted, dict):
                submit_status, submit_body = 200, submitted
            else:
                submit_status, submit_body = 502, {}
            if 200 <= int(submit_status) < 300:
                response["evidence_status"] = submit_body.get(
                    "evidence_status", "pending"
                )
                if isinstance(
                    submit_body.get("verification_result"), dict
                ):
                    response["verification_result"] = submit_body[
                        "verification_result"
                    ]
        except Exception:
            # Provider execution already succeeded. Verification can be
            # retried independently; never claim it happened.
            response["evidence_status"] = "pending"
        return response


def canonical_hash(payload):
    from agents.orchestrator.action_repository import canonical_payload_hash
    return canonical_payload_hash(payload)


def _binding_matches(proposal, binding):
    if proposal is None:
        return False
    fields = (
        "proposal_id",
        "version",
        "user_principal_id",
        "agent_principal_id",
        "credential_id",
        "capability_id",
        "payload_hash",
        "idempotency_key",
    )
    if proposal.get("workflow_revision_id") != "legacy":
        fields += (
            "workflow_revision_id", "step_id", "plan_graph_hash",
            "connection_id", "attempt",
        )
    return all(proposal.get(field) == binding.get(field) for field in fields)


def oauth_connection_authorizer(repository, provider="google"):
    """Bind broker authority to the user's current provider connection."""
    def authorize(binding):
        if binding.get("connection_id") and binding.get("tenant_id"):
            connection = repository.get_installation(
                binding["connection_id"], binding["tenant_id"]
            )
            return bool(
                connection
                and connection.get("status") == "connected"
                and connection.get("credential_id") == binding.get("credential_id")
                and binding.get("capability_id") in connection.get("enabled_capabilities", ())
            )
        connection = repository.get_connection(
            binding.get("user_principal_id"), provider
        )
        return bool(
            connection
            and connection.get("status") == "connected"
            and connection.get("credential_id") == binding.get("credential_id")
            and binding.get("capability_id")
            in connection.get("enabled_capabilities", ())
        )

    return authorize


class ActionBrokerHandler(BaseHTTPRequestHandler):
    server_version = "TesseraActionBroker/1.0"

    def _respond(self, status, body):
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        segments = [
            segment for segment in urlsplit(self.path).path.split("/") if segment
        ]
        if segments == ["internal", "execute"]:
            self._execute_internal()
            return
        if (
            len(segments) != 3
            or segments[0] != "actions"
            or segments[2] != "approve"
        ):
            self._respond(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError):
            body = None
        status, response = self.server.broker.decide(
            session_cookie_value(self.headers.get("Cookie")),
            self.headers.get("X-CSRF-Token"),
            segments[1],
            body,
        )
        self._respond(status, response)

    def _execute_internal(self):
        expected = getattr(self.server, "internal_token", None)
        supplied = self.headers.get("Authorization", "")
        supplied = (
            supplied[len("Bearer "):]
            if supplied.startswith("Bearer ")
            else ""
        )
        if (
            not expected
            or not supplied
            or not hmac.compare_digest(supplied, expected)
        ):
            self._respond(401, {"error": "service authentication required"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError):
            body = None
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("lease"), str)
            or not isinstance(body.get("binding"), dict)
            or not isinstance(body.get("payload"), dict)
        ):
            self._respond(422, {"error": "invalid execution request"})
            return
        status, response = self.server.broker.execute(
            body["lease"], body["binding"], body["payload"]
        )
        self._respond(status, response)

    def log_message(self, _format, *_args):
        return


def make_server(
    broker, host="127.0.0.1", port=8122, internal_token=None
):
    server = ThreadingHTTPServer((host, port), ActionBrokerHandler)
    server.broker = broker
    server.internal_token = internal_token
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8122)
    args = parser.parse_args()
    factory_path = os.environ.get(
        "TESSERA_ACTION_BROKER_FACTORY",
        "services.action_broker.composition:build_broker",
    )
    if ":" not in factory_path:
        raise RuntimeError(
            "TESSERA_ACTION_BROKER_FACTORY must name module:function"
        )
    module_name, factory_name = factory_path.split(":", 1)
    factory = getattr(importlib.import_module(module_name), factory_name)
    broker = factory()
    if not isinstance(broker, ActionBroker):
        raise TypeError("action broker factory must return ActionBroker")
    internal_token = os.environ.get(
        "TESSERA_ACTION_BROKER_INTERNAL_TOKEN"
    )
    if not internal_token:
        raise RuntimeError(
            "TESSERA_ACTION_BROKER_INTERNAL_TOKEN is required"
        )
    server = make_server(
        broker,
        host=args.host,
        port=args.port,
        internal_token=internal_token,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
