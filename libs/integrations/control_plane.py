"""Durable, tenant-scoped control plane for families, senders, and stop.

Every kill switch in this system used to be a process-wide environment
variable. That shape cannot express "this account disabled WhatsApp" or "this
account is stopped", and changing one required a restart, so the fastest an
administrator could act was a deploy. This module is the replacement: one
provider-neutral read model over durable per-tenant state, and one gate that
every dispatch path consults.

Two carve-outs are load-bearing and neither is optional.

A **family disable gates writes only.** A family whose reads were also cut
would strand its own unknown outcomes forever, because reconciliation needs
the very API the disable removed.

**Emergency stop carries the same carve-out**, and it matters more there
because a stop is broader. A stop that blocked reconciliation and provider
event ingestion would freeze every in-flight effect at exactly the moment an
administrator needs a truthful dispatched-versus-prevented count, and no
campaign could ever drain. So a stop blocks new dispatch and degrades inbound
handling; it never blocks a read, a reconciliation, or a status callback.

Denials are reasons, not booleans, and every reason is prefixed
``control_plane:`` so the workflow resume path can recognise a pause that a
later control-plane change can lift, and distinguish it from a pause that
needs a human to replan.
"""

from collections.abc import Mapping


#: Why the gate is being asked. ``dispatch`` is new outbound work,
#: ``inbound`` is handling something a person or provider sent us, and
#: ``recovery`` is reconciliation and provider-event ingestion, which no
#: control-plane state may ever block.
DISPATCH = "dispatch"
INBOUND = "inbound"
RECOVERY = "recovery"

#: Every control-plane denial starts with this. ``resume_policy_paused``
#: matches on it, so a stop lifted at 09:00 drains at 09:00 rather than
#: waiting for someone to replan every parked step by hand.
REASON_PREFIX = "control_plane:"

EMERGENCY_STOP = REASON_PREFIX + "emergency_stop"
FAMILY_DISABLED = REASON_PREFIX + "family_disabled"
SENDER_DISABLED = REASON_PREFIX + "sender_disabled"
#: The control plane itself could not be read. Fail closed, but as a pause a
#: later tick lifts, never as a failure that consumes the retry budget.
UNAVAILABLE = REASON_PREFIX + "unavailable"


class ControlDecision(object):
    """An allow or a deny that carries why, so the pause reason is truthful."""

    __slots__ = ("allowed", "reason")

    def __init__(self, allowed, reason=None):
        self.allowed = bool(allowed)
        self.reason = reason

    def __bool__(self):
        return self.allowed

    __nonzero__ = __bool__

    def __eq__(self, other):
        if isinstance(other, ControlDecision):
            return (self.allowed, self.reason) == (other.allowed, other.reason)
        if isinstance(other, bool):
            return self.allowed is other
        return NotImplemented

    def __hash__(self):
        return hash((self.allowed, self.reason))

    def __repr__(self):
        return "ControlDecision(allowed=%r, reason=%r)" % (
            self.allowed, self.reason
        )


ALLOWED = ControlDecision(True)


def _denied(reason, detail=None):
    return ControlDecision(
        False, reason if detail is None else "%s:%s" % (reason, detail)
    )


class ControlPlaneState(object):
    """What one tenant's administrators have currently switched on.

    A family with no row is off. That is deliberate and matches the migration:
    families land disabled, and enabling one is a deliberate act. Reading an
    absent row as "on" would mean a tenant nobody has configured silently
    holds every family the catalog ships.
    """

    __slots__ = (
        "tenant_id", "emergency_stop", "stop_reason", "stopped_at",
        "stopped_by_principal_id", "families", "senders",
    )

    def __init__(
        self, tenant_id, emergency_stop=False, stop_reason=None,
        stopped_at=None, stopped_by_principal_id=None, families=None,
        senders=None,
    ):
        self.tenant_id = tenant_id
        self.emergency_stop = bool(emergency_stop)
        self.stop_reason = stop_reason
        self.stopped_at = stopped_at
        self.stopped_by_principal_id = stopped_by_principal_id
        self.families = dict(families or {})
        self.senders = dict(senders or {})

    @classmethod
    def from_mapping(cls, tenant_id, value):
        value = value if isinstance(value, Mapping) else {}
        return cls(
            tenant_id,
            emergency_stop=value.get("emergency_stop", False),
            stop_reason=value.get("stop_reason"),
            stopped_at=value.get("stopped_at"),
            stopped_by_principal_id=value.get("stopped_by_principal_id"),
            families=value.get("families"),
            senders=value.get("senders"),
        )

    def family_enabled(self, family):
        return self.families.get(family) is True

    def sender_enabled(self, sender_id):
        return self.senders.get(sender_id) is True

    def as_dict(self):
        return {
            "tenant_id": self.tenant_id,
            "emergency_stop": self.emergency_stop,
            "stop_reason": self.stop_reason,
            "stopped_at": self.stopped_at,
            "stopped_by_principal_id": self.stopped_by_principal_id,
            "families": dict(sorted(self.families.items())),
            "senders": dict(sorted(self.senders.items())),
        }


class TenantControlPlane(object):
    """The one place a dispatch path asks whether a tenant may act now.

    ``store`` is anything exposing ``control_plane_state(tenant_id)``. The
    orchestrator, the worker, and the broker all hold a connection repository
    that does, so no path has to reach for an environment variable to find out
    whether it is allowed to run.

    ``family_resolver`` maps a capability id to the families that admit it, so
    the gate stays provider-neutral: Slack supplies the operation manifest's
    family flags, Twilio will supply ``sms``, ``whatsapp``, ``voice``.

    ``effect_resolver`` maps a capability id to ``read`` or ``write``, which is
    what makes the write-only carve-out enforceable at the broker, where the
    caller has not yet told us whether this is a new effect or a reconciling
    read.
    """

    def __init__(
        self, store, family_resolver=None, effect_resolver=None, clock=None,
        cache_seconds=1.0,
    ):
        self.store = store
        self.family_resolver = family_resolver
        self.effect_resolver = effect_resolver
        self.clock = clock
        self.cache_seconds = float(cache_seconds)
        self._cache = {}

    def _now(self):
        if self.clock is None:
            import time

            return time.time()
        return self.clock()

    def invalidate(self, tenant_id=None):
        """Drop the read-through cache so a change takes effect immediately."""
        if tenant_id is None:
            self._cache.clear()
        else:
            self._cache.pop(tenant_id, None)

    def state(self, tenant_id):
        """Current durable state, or None when the store could not answer."""
        if not tenant_id or self.store is None:
            return None
        now = self._now()
        cached = self._cache.get(tenant_id)
        if cached is not None and now - cached[0] < self.cache_seconds:
            return cached[1]
        try:
            raw = self.store.control_plane_state(tenant_id)
        except Exception:
            # An unreadable control plane is not an open one. Return None and
            # let the gate fail closed with a resumable reason.
            self._cache.pop(tenant_id, None)
            return None
        state = ControlPlaneState.from_mapping(tenant_id, raw)
        self._cache[tenant_id] = (now, state)
        return state

    def emergency_stop(self, tenant_id):
        state = self.state(tenant_id)
        return bool(state is not None and state.emergency_stop)

    def family_flags(self, tenant_id):
        """Family switches for this tenant, for the operation projection."""
        state = self.state(tenant_id)
        if state is None:
            return {}
        if state.emergency_stop:
            # A stopped account offers nothing. The projection is what the
            # model is allowed to see, so leaving families visible during a
            # stop would have the Concierge plan work it can never dispatch.
            return {family: False for family in state.families}
        return dict(state.families)

    def _families_for(self, capability_id):
        if self.family_resolver is None or not capability_id:
            return ()
        try:
            families = self.family_resolver(capability_id)
        except Exception:
            return ()
        if families is None:
            return ()
        if isinstance(families, str):
            return (families,)
        return tuple(families)

    def _effect_for(self, capability_id, fallback):
        if fallback in ("read", "write"):
            return fallback
        if self.effect_resolver is None or not capability_id:
            # Unknown effect is treated as a write. Guessing "read" here would
            # let an unrecognised capability walk straight through a stop.
            return "write"
        try:
            effect = self.effect_resolver(capability_id)
        except Exception:
            return "write"
        return effect if effect in ("read", "write") else "write"

    def decide(
        self, tenant_id, capability_id=None, effect=None, purpose=DISPATCH,
        family=None, sender_id=None,
    ):
        """Whether this tenant may take this action right now, and why not."""
        if purpose == RECOVERY:
            # Reconciliation and provider-event ingestion are how an effect
            # reaches a verdict. Gating them would make a stop the one thing
            # that guarantees permanent uncertainty.
            return ALLOWED
        resolved_effect = self._effect_for(capability_id, effect)
        state = self.state(tenant_id)
        if state is None:
            if resolved_effect == "write" or purpose == INBOUND:
                return ControlDecision(False, UNAVAILABLE)
            return ALLOWED
        if state.emergency_stop and (
            purpose == INBOUND or resolved_effect == "write"
        ):
            return ControlDecision(False, EMERGENCY_STOP)
        if resolved_effect != "write":
            # Reads survive both switches on purpose: this is the carve-out
            # that lets a disabled family's unknown outcomes still reconcile.
            return ALLOWED
        if sender_id is not None and not state.sender_enabled(sender_id):
            return _denied(SENDER_DISABLED, sender_id)
        families = (family,) if family else self._families_for(capability_id)
        if families and not any(
            state.family_enabled(name) for name in families
        ):
            return _denied(FAMILY_DISABLED, sorted(families)[0])
        return ALLOWED

    def decide_binding(self, binding):
        """Gate one broker binding, without needing the caller's cooperation."""
        binding = binding if isinstance(binding, Mapping) else {}
        return self.decide(
            binding.get("tenant_id"),
            capability_id=binding.get("capability_id"),
            effect=binding.get("effect"),
            purpose=binding.get("control_plane_purpose") or DISPATCH,
            sender_id=binding.get("sender_id"),
        )

    def decide_step(self, step):
        """Gate one workflow step before the executor dispatches it."""
        step = step if isinstance(step, Mapping) else {}
        return self.decide(
            step.get("tenant_id"),
            capability_id=step.get("capability_id"),
            effect=step.get("effect"),
            purpose=DISPATCH,
        )


def capability_family_resolver(registry):
    """Map a capability id to the families that admit it.

    The operation manifest already names one family per operation, and every
    operation names the capabilities it needs. Inverting that is what lets the
    broker answer "which family does this effect belong to" without the broker
    knowing anything about Slack.
    """
    index = {}
    for operation in getattr(registry, "operations", ()):
        for step in getattr(operation, "capability_recipe", ()):
            index.setdefault(step.capability_id, set()).add(
                operation.family_flag
            )

    def resolve(capability_id):
        return tuple(sorted(index.get(capability_id, ())))

    return resolve


def capability_effect_resolver(definitions):
    """Map a capability id to ``read`` or ``write`` from the trusted catalog."""
    index = {
        definition.capability_id: definition.effect
        for definition in definitions or ()
    }

    def resolve(capability_id):
        return index.get(capability_id)

    return resolve


def is_control_plane_reason(reason):
    return isinstance(reason, str) and reason.startswith(REASON_PREFIX)


def build_tenant_control_plane(store, definitions, operation_registry=None):
    """Assemble the control plane every service composes the same way.

    Three processes read these switches -- the broker, the worker, and the
    Concierge -- and if any of them assembled the resolvers differently, a
    family would be off in one and on in another. One builder is what keeps
    the answer identical wherever it is asked.
    """
    definitions = tuple(definitions or ())
    if operation_registry is None:
        from agents.orchestrator.slack_operations import load_slack_operations

        slack_definitions = tuple(
            definition for definition in definitions
            if definition.provider == "slack"
        )
        operation_registry = (
            load_slack_operations(slack_definitions)
            if slack_definitions else None
        )
    return TenantControlPlane(
        store,
        family_resolver=(
            capability_family_resolver(operation_registry)
            if operation_registry is not None else None
        ),
        effect_resolver=capability_effect_resolver(definitions),
    )
