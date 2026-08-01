"""Deterministic fail-closed policy decisions for dynamic provider work."""

import hashlib
import json
from collections.abc import Mapping

from agents.orchestrator.planner import descriptor_hash
from libs.integrations.catalog import TrustedCapabilityDefinition


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def _hash(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class PolicyEvaluator(object):
    """Evaluate one immutable dynamic binding against live bot authority."""

    VERSION = "policy-v1"

    def __init__(self, definitions, rollout_version, version=None):
        self.version = version or self.VERSION
        self.rollout_version = rollout_version
        self._definitions = {
            (item.capability_id, item.version): item
            for item in definitions
            if isinstance(item, TrustedCapabilityDefinition)
        }

    def evaluate(self, binding, live_connection, now_ts):
        binding = binding if isinstance(binding, Mapping) else {}
        snapshot = binding.get("connection_snapshot")
        snapshot = snapshot if isinstance(snapshot, Mapping) else {}
        live = live_connection if isinstance(live_connection, Mapping) else {}
        capability_id = binding.get("capability_id")
        capability_version = binding.get("capability_version")
        definition = self._definitions.get((capability_id, capability_version))
        profile = binding.get("authority_profile", "bot")
        snapshot_profile = snapshot.get("authority_profile", "bot")
        live_profile = live.get("authority_profile", "bot")
        effective_scopes = sorted(set(live.get("granted_scopes") or ()))
        normalized = {
            "tenant_id": binding.get("tenant_id"),
            "principal_id": binding.get("user_principal_id"),
            "connection_id": binding.get("connection_id"),
            "authority_profile": profile,
            "capability_id": capability_id,
            "capability_version": capability_version,
            "descriptor_snapshot_hash": binding.get(
                "descriptor_snapshot_hash"
            ),
            "effect": binding.get("effect"),
            "credential_id": binding.get("credential_id"),
            "credential_version": binding.get("credential_version"),
            "effective_scopes": effective_scopes,
            "rollout_version": self.rollout_version,
            "plan_graph_hash": binding.get("plan_graph_hash"),
            "workflow_revision_id": binding.get("workflow_revision_id"),
            "step_id": binding.get("step_id"),
            "attempt": binding.get("attempt"),
            "approval_payload_hash": binding.get("approval_payload_hash"),
            "approval_expires_at": binding.get("approval_expires_at"),
            "slack_connect": binding.get("slack_connect", False),
            "data_egress": binding.get("data_egress", False),
        }
        input_hash = _hash(normalized)
        reason = self._denial_reason(
            binding, snapshot, live, definition, profile,
            snapshot_profile, live_profile, effective_scopes, now_ts,
        )
        decision = {
            "allowed": reason is None,
            "reason": reason or "allowed",
            "version": self.version,
            "input_hash": input_hash,
        }
        decision["decision_hash"] = _hash(decision)
        return decision

    def _denial_reason(
        self, binding, snapshot, live, definition, profile,
        snapshot_profile, live_profile, effective_scopes, now_ts,
    ):
        required = (
            "tenant_id", "user_principal_id", "connection_id",
            "capability_id", "capability_version",
            "descriptor_snapshot_hash", "effect", "credential_id",
            "credential_version", "plan_graph_hash",
            "workflow_revision_id", "step_id", "attempt",
        )
        if any(binding.get(field) in (None, "") for field in required):
            return "incomplete_dynamic_binding"
        if not snapshot or not live:
            return "connection_snapshot_missing"
        if definition is None:
            return "capability_unavailable"
        if binding["tenant_id"] != snapshot.get("tenant_id"):
            return "tenant_mismatch"
        if binding["tenant_id"] != live.get("tenant_id"):
            return "tenant_mismatch"
        if binding["connection_id"] != snapshot.get("connection_id"):
            return "connection_mismatch"
        if binding["connection_id"] != live.get("connection_id"):
            return "connection_mismatch"
        if profile != "bot" or snapshot_profile != "bot" or live_profile != "bot":
            return "unsupported_authority_profile"
        if snapshot.get("health") != "healthy" or live.get("status") != "connected":
            return "connection_unhealthy"
        if snapshot.get("rollout_version") != self.rollout_version:
            return "rollout_drift"
        if snapshot.get("capability_id") != binding["capability_id"]:
            return "capability_mismatch"
        if snapshot.get("capability_version") != binding["capability_version"]:
            return "capability_mismatch"
        if binding["capability_id"] not in set(
            live.get("enabled_capabilities") or ()
        ):
            return "capability_mismatch"
        if definition.effect != binding["effect"]:
            return "capability_mismatch"
        if descriptor_hash(definition) != binding["descriptor_snapshot_hash"]:
            return "descriptor_mismatch"
        try:
            credential_version = int(binding["credential_version"])
            snapshot_version = int(snapshot.get("credential_version"))
            live_version = int(live.get("credential_version"))
        except (TypeError, ValueError):
            return "credential_mismatch"
        if credential_version <= 0 or not (
            credential_version == snapshot_version == live_version
        ):
            return "credential_mismatch"
        if binding["credential_id"] != live.get("credential_id"):
            return "credential_mismatch"
        snapshot_scopes = set(snapshot.get("effective_scopes") or ())
        if not definition.required_scopes.issubset(snapshot_scopes):
            return "missing_required_scopes"
        if not definition.required_scopes.issubset(set(effective_scopes)):
            return "missing_required_scopes"
        if binding.get("slack_connect") is not False:
            return "slack_connect_denied"
        if binding.get("data_egress") is not False:
            return "data_egress_denied"
        if definition.effect == "write":
            if not binding.get("approval_payload_hash"):
                return "approval_binding_missing"
            if binding.get("approval_payload_hash") != binding.get("payload_hash"):
                return "approval_binding_mismatch"
            try:
                if int(binding.get("approval_expires_at")) < int(now_ts):
                    return "approval_expired"
            except (TypeError, ValueError):
                return "approval_binding_missing"
        return None
