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

    #: Dispatch compares a stored decision hash against a freshly computed one,
    #: so any change to what the evaluator considers must change this. Bumped
    #: to v2 when the evaluator became provider-neutral, and to v3 when the
    #: provider account a dispatch acts as entered the hash — a decision made
    #: before that field existed cannot speak to which account it authorised.
    VERSION = "policy-v3"

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
            # The subject and the decision that authorised it are part of what
            # the policy hash covers, so a dispatch cannot swap whose token it
            # acts as after the decision was made.
            "authority_profile_id": binding.get("authority_profile_id"),
            "slack_subject_id": binding.get("slack_subject_id"),
            # Which provider account the effect leaves from. For an account
            # authority this is the whole identity, so leaving it out would let
            # an approved effect be redirected to a different account.
            "provider_account_id": binding.get("provider_account_id"),
            # Authority this particular effect needs beyond what its capability
            # needs: the sending identity it leaves from, the destination it
            # reaches, the template it uses. A capability descriptor cannot
            # name these — they differ per effect — so the binding carries them
            # and they are hashed with everything else.
            "bound_scopes": sorted(set(binding.get("bound_scopes") or ())),
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

    @staticmethod
    def _personal_authority_reason(binding):
        """A user-token dispatch must carry proof of whose token it is.

        The profile id, the Slack subject, and the authorization decision made
        when the requester was checked against that subject all travel in the
        binding. Missing any of them means nothing established that this
        requester may act as this person, which is exactly the case that must
        not reach Slack.
        """
        profile_id = binding.get("authority_profile_id")
        subject = binding.get("slack_subject_id")
        authorization = binding.get("authority_authorization")
        if not profile_id or not subject:
            return "personal_authority_unbound"
        if not isinstance(authorization, Mapping):
            return "personal_authority_unproven"
        if authorization.get("authority_profile_id") != profile_id:
            return "personal_authority_mismatch"
        if authorization.get("allowed") is not True:
            return "personal_authority_denied"
        if authorization.get("reason") not in ("requester_is_subject", "delegated"):
            return "personal_authority_denied"
        return None

    @staticmethod
    def _account_authority_reason(binding, snapshot, live):
        """An account-token dispatch must say which account it leaves from.

        There is no consenting person to bind to, so the binding's proof of
        identity is the provider account itself. It has to agree across the
        binding, the snapshot the decision was made against, and live state,
        or the effect could leave from an account nobody authorised. An
        account that is not currently verified holds no authority at all,
        which is the fail-closed state a provider outage lands in.
        """
        account_id = binding.get("provider_account_id")
        if not account_id:
            return "account_authority_unbound"
        if account_id != snapshot.get("provider_account_id"):
            return "account_authority_mismatch"
        if account_id != live.get("provider_account_id"):
            return "account_authority_mismatch"
        if live.get("account_status") != "verified":
            return "account_authority_unverified"
        return None

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
        if profile != snapshot_profile or profile != live_profile:
            return "authority_profile_mismatch"
        # Enterprise admin has no qualified executor and no credential custody
        # yet, so it is refused here rather than left to fail somewhere less
        # visible. This is the boundary the unit requires be explicit.
        if profile == "enterprise_admin":
            return "enterprise_authority_unavailable"
        if profile not in ("bot", "user", "account"):
            return "unsupported_authority_profile"
        # The descriptor decides which authority its executor needs. A search
        # answered with a bot token is a different answer, not a lesser one.
        if definition.authority_profile != profile:
            return "authority_profile_not_permitted"
        if profile == "user":
            personal = self._personal_authority_reason(binding)
            if personal is not None:
                return personal
        if profile == "account":
            account = self._account_authority_reason(binding, snapshot, live)
            if account is not None:
                return account
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
        bound_scopes = set(binding.get("bound_scopes") or ())
        if profile == "account" and definition.effect == "write" and not bound_scopes:
            # An effect that leaves a provider account has to say which
            # verified identity it leaves from. Nothing else in the binding
            # says it, and a paid effect from an unnamed sender is exactly the
            # thing that must not reach a provider.
            return "bound_authority_missing"
        if not bound_scopes.issubset(snapshot_scopes) or not bound_scopes.issubset(
            set(effective_scopes)
        ):
            # Distinct from a missing capability scope: the capability is still
            # granted, but the specific sender, destination or template this
            # effect was bound to is no longer authority the account holds.
            # This is the path a disabled sender takes, and it stops only the
            # effects bound to that sender.
            return "missing_bound_authority"
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
