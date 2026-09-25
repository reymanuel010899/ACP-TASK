"""Consent, suppression, and address usability -- three axes, three ledgers.

`migrations/0018_contact_consent.sql` argues for the shape; this is the only
way in to it. Three things it does that a thinner wrapper would not:

**It refuses to collapse the axes.** There is no `is_contactable` here and no
single state to read. `axes()` returns four separate readings and
`evaluate_eligibility()` returns the first one that says no along with a reason
code naming *which* axis said it. A caller that wants "can we send" gets an
answer plus the reason, because "blocked" and "blocked because they told us to
stop" are different facts to an operator and to a regulator.

**It enforces the permissive/restrictive asymmetry rather than describing
it** (KTD13). This is where the two origin requirements actually collide: one
says every consent change needs an authorised human, the other says an inbound
opt-out must take effect immediately. Both are right, in opposite directions,
and the resolution is directional. Restrictive moves -- opt-out, suppression,
bounce, retirement -- self-execute from whatever actor is at hand, including
the contact and including the provider's webhook, because a delayed opt-out is
a violation and a human in that loop is latency with no upside. Permissive
moves -- granting, un-suppressing, activating a proposed address -- take a
named human with a named authority, and un-suppressing takes an administrator
specifically. The database holds the same rules as check constraints; the
errors here exist so the caller gets a sentence instead of a constraint name.

**It keeps provider reachability out of consent.** Twilio answers STOP and
START on its own, and a START restores carrier delivery before ACP-TASK hears
about it. `record_provider_restart()` therefore writes exactly one row, to the
reachability ledger, and touching consent from it is not an option this module
offers. A subscriber who opted out of marketing and later texted START to
reopen a support thread stays opted out of marketing.
"""

import hashlib
from datetime import datetime, timedelta, timezone

from psycopg.rows import dict_row

from libs.tenancy import TenantScopeRequired
from libs.ulid import generate_ulid


__all__ = [
    "Actor",
    "AddressNotFound",
    "AdministratorRequired",
    "ConsentEvidence",
    "ConsentEvidenceRequired",
    "ContactsConsentRepository",
    "EligibilityDecision",
    "HumanDecisionRequired",
    "TenantScopeRequired",
    "resolve_revocation_scope",
]


CHANNELS = ("sms", "whatsapp", "voice", "email")

#: The three WhatsApp template categories plus the two purposes that exist
#: without WhatsApp. Purpose scoping is the part most often dropped, and
#: dropping it is what makes a marketing unsubscribe swallow a password reset.
PURPOSES = (
    "marketing", "utility", "authentication", "transactional", "service",
)

#: Which purposes a 'topic'-scoped revocation reaches. Narrower than
#: cross-topic and wider than the single program that sent the message.
PURPOSE_TOPICS = {
    "marketing": "promotional",
    "utility": "operational",
    "transactional": "operational",
    "service": "operational",
    "authentication": "security",
}

CONSENT_STATES = (
    "unknown", "pending_evidence", "granted", "expired", "withdrawn",
)

SUPPRESSION_STATES = (
    "none",
    "suppressed_by_optout",
    "suppressed_by_bounce",
    "suppressed_by_admin",
    "suppressed_by_provider",
)

USABILITY_STATES = ("proposed", "active", "retired")

REACHABILITY_STATES = ("reachable", "blocked_by_provider")

ACTOR_KINDS = ("human", "agent", "system", "provider", "contact")

REVOCATION_SCOPES = ("program", "topic", "cross_topic")

#: The date a cross-topic revocation duty takes effect. Modelled now and gated
#: by date, so widening is a configuration change plus this constant, never a
#: migration written the week it becomes mandatory.
CROSS_TOPIC_REVOCATION_EFFECTIVE = datetime(2027, 1, 31, tzinfo=timezone.utc)

AUTHORITY_MANAGE_CONTACTS = "manage_contacts"
AUTHORITY_ADMINISTER = "administer"

#: Authorities that may activate a proposed address or grant consent.
GRANT_AUTHORITIES = (AUTHORITY_MANAGE_CONTACTS, AUTHORITY_ADMINISTER)

#: Capture methods that put a checkbox in front of somebody. For these the
#: default-unchecked proof is mandatory rather than merely expected.
FORM_CAPTURE_METHODS = ("web_form", "embedded_form", "import_form")

#: Capture methods whose evidence *is* a recording, and therefore outlives the
#: ordinary floor -- the recording is the proof, and a five-year-old dispute
#: about a recorded call is answered by the recording or not at all.
RECORDING_CAPTURE_METHODS = (
    "voice_recording", "call_recording", "verbal_recorded", "ivr_recording",
)

#: The floor, not the setting. Jurisdictions layer longer requirements on top;
#: nothing in this module may shorten it.
RETENTION_FLOOR_YEARS = 5
RECORDING_RETENTION_FLOOR_YEARS = 10

#: How long the verbatim inbound message that carried an opt-out is kept.
#: Mirrors the orchestrator's workflow-content window. The decision itself is
#: held for `RETENTION_FLOOR_YEARS`; only the body expires on this clock.
DEFAULT_CONTENT_TTL_SECONDS = 30 * 24 * 60 * 60


_CONSENT_COLUMNS = (
    "consent_record_id", "tenant_id", "contact_id", "address_id", "channel",
    "purpose", "state", "transition_kind", "capture_method", "captured_at",
    "captured_at_local", "capture_timezone", "jurisdiction", "disclosure_text",
    "disclosure_hash", "default_unchecked", "legal_basis", "source",
    "actor_kind", "actor_principal_id", "decided_by_principal_id",
    "decided_by_authority", "expires_at", "revocation_scope",
    "inbound_message_body", "content_expires_at", "content_purged_at",
    "retained_until", "recorded_at",
)

_SUPPRESSION_COLUMNS = (
    "suppression_id", "tenant_id", "address_id", "channel", "sender_id",
    "state", "transition_kind", "reason_code", "source", "actor_kind",
    "actor_principal_id", "decided_by_principal_id", "decided_by_authority",
    "retained_until", "recorded_at",
)

_USABILITY_COLUMNS = (
    "usability_decision_id", "tenant_id", "address_id", "state",
    "transition_kind", "proposed_by_actor_kind", "proposed_by_principal_id",
    "decided_by_principal_id", "decided_by_authority", "reason",
    "retained_until", "recorded_at",
)

_REACHABILITY_COLUMNS = (
    "reachability_event_id", "tenant_id", "address_id", "channel", "sender_id",
    "state", "provider_keyword", "source", "retained_until", "recorded_at",
)

_ADDRESS_COLUMNS = ("address_id", "tenant_id", "contact_id", "channel")

#: 0018's per-ledger `bigint generated always as identity`. Read on every
#: ledger query because it is what "newest row" means once `recorded_at` ties,
#: and left out of the column tuples above because it is the store's bookkeeping
#: rather than part of any decision a caller was handed. It is never written:
#: the insert statements do not name it, and the database would refuse them if
#: they did.
_LEDGER_SEQUENCE = "ledger_sequence"

_CONSENT_SELECT = ", ".join(_CONSENT_COLUMNS + (_LEDGER_SEQUENCE,))
_SUPPRESSION_SELECT = ", ".join(_SUPPRESSION_COLUMNS + (_LEDGER_SEQUENCE,))
_USABILITY_SELECT = ", ".join(_USABILITY_COLUMNS + (_LEDGER_SEQUENCE,))
_REACHABILITY_SELECT = ", ".join(_REACHABILITY_COLUMNS + (_LEDGER_SEQUENCE,))
_ADDRESS_SELECT = ", ".join(_ADDRESS_COLUMNS)


class AddressNotFound(LookupError):
    """No such address in this account.

    Same answer for "never existed" and "belongs to another account", for the
    same reason `ContactsRepository` gives: a distinguishable refusal confirms
    the row is real, which is most of what an enumerating attacker wants.
    """

    def __init__(self, message="address not found"):
        super(AddressNotFound, self).__init__(message)


class HumanDecisionRequired(PermissionError):
    """A permissive transition attempted without an authorised human.

    Raised for an agent granting consent, for a service account activating a
    proposed number, and for a human who holds no authority over contacts. The
    restrictive direction never raises this -- that asymmetry is the point.
    """


class AdministratorRequired(PermissionError):
    """Un-suppressing, attempted by anyone short of an administrator.

    Separate from `HumanDecisionRequired` because the bar is genuinely
    different: a contact manager may grant consent and approve an address and
    still may not resume sending to somebody who was blocked.
    """


class ConsentEvidenceRequired(ValueError):
    """A grant that cannot be defended later, refused now.

    Names the fields that are missing, because the caller assembling a consent
    record from a form submission needs to know which part of the form was not
    captured -- and because a grant recorded without them is worse than no
    grant at all: it looks like permission.
    """

    def __init__(self, missing):
        self.missing = tuple(missing)
        super(ConsentEvidenceRequired, self).__init__(
            "consent evidence is incomplete: %s" % ", ".join(self.missing)
        )


class ConsentEvidence(object):
    """What the regulatory envelope asks for, gathered in one place.

    Two timestamps for one moment is not redundancy. The UTC one orders
    events; `captured_at_local` is the wall clock where the person actually
    was, which is what a quiet-hours or time-of-capture question is about.

    `disclosure_text` is the verbatim words shown, not an identifier for the
    template that produced them, because templates get edited and the edit is
    invisible afterwards. `default_unchecked` is the proof the box started
    empty: `None` where the capture had no box (a recorded call, an inbound
    keyword), never `False` under a grant.
    """

    def __init__(
        self, capture_method, captured_at, captured_at_local, jurisdiction,
        disclosure_text, legal_basis, source=None, capture_timezone=None,
        default_unchecked=None, expires_at=None,
    ):
        self.capture_method = capture_method
        self.captured_at = captured_at
        self.captured_at_local = captured_at_local
        self.capture_timezone = capture_timezone
        self.jurisdiction = jurisdiction
        self.disclosure_text = disclosure_text
        self.legal_basis = legal_basis
        self.source = source
        self.default_unchecked = default_unchecked
        self.expires_at = expires_at

    @property
    def disclosure_hash(self):
        text = self.disclosure_text or ""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def missing_fields(self):
        """Which required fields are absent, in a stable order."""
        missing = [
            name for name in (
                "capture_method", "captured_at", "captured_at_local",
                "jurisdiction", "disclosure_text", "legal_basis",
            )
            if not getattr(self, name)
        ]
        # A pre-ticked box is not consent in any jurisdiction that has an
        # opinion, so an explicit `False` fails the same way an absent
        # required field does.
        if self.default_unchecked is False:
            missing.append("default_unchecked")
        elif (
            self.capture_method in FORM_CAPTURE_METHODS
            and self.default_unchecked is not True
        ):
            missing.append("default_unchecked")
        return missing

    def retention_floor(self, moment):
        """Five years, or ten where the evidence is a recording."""
        years = (
            RECORDING_RETENTION_FLOOR_YEARS
            if self.capture_method in RECORDING_CAPTURE_METHODS
            else RETENTION_FLOOR_YEARS
        )
        return _plus_years(moment, years)


class Actor(object):
    """Who is asking, and what they are allowed to decide.

    `kind` is load-bearing on its own: only 'human' may take a permissive
    transition, so an agent holding every authority in the set still cannot
    grant consent. That is R12 -- an agent may propose, a human decides.
    """

    def __init__(self, kind, principal_id=None, authorities=()):
        if kind not in ACTOR_KINDS:
            raise ValueError("unknown actor kind: %r" % (kind,))
        self.kind = kind
        self.principal_id = principal_id
        self.authorities = frozenset(authorities or ())

    def holds(self, *authorities):
        return any(name in self.authorities for name in authorities)

    @classmethod
    def human(cls, principal_id, authorities=()):
        return cls("human", principal_id, authorities)

    @classmethod
    def agent(cls, principal_id=None, authorities=()):
        return cls("agent", principal_id, authorities)

    @classmethod
    def system(cls, principal_id=None):
        return cls("system", principal_id)

    @classmethod
    def provider(cls, principal_id=None):
        return cls("provider", principal_id)

    @classmethod
    def contact(cls, principal_id=None):
        return cls("contact", principal_id)


class EligibilityDecision(object):
    """The answer plus the axis that produced it.

    A bare boolean is unusable here. "Not eligible" gets shown to an operator
    who has to decide whether to fix something, and a bounce, an opt-out, and
    an unapproved number call for three different actions. `reason` names the
    axis; `axes` carries all four readings so nothing has to be re-queried to
    explain the verdict.
    """

    def __init__(self, eligible, reason, axes):
        self.eligible = bool(eligible)
        self.reason = reason
        self.axes = axes

    def __bool__(self):
        return self.eligible

    def __repr__(self):
        return "EligibilityDecision(eligible=%r, reason=%r)" % (
            self.eligible, self.reason,
        )


def resolve_revocation_scope(now=None, configured=None):
    """How wide a withdrawal reaches, today.

    The cross-topic duty lands on a known date. Until then the configured
    scope wins and defaults to per-program; from that date the floor becomes
    cross-topic regardless of configuration, because the deadline is not
    something an operator gets to opt out of by forgetting to change a
    setting. All three values are already legal in the column, so widening
    early is a configuration flip and never a migration.
    """
    if configured is not None and configured not in REVOCATION_SCOPES:
        raise ValueError("unknown revocation scope: %r" % (configured,))
    moment = now or _utcnow()
    if moment >= CROSS_TOPIC_REVOCATION_EFFECTIVE:
        return "cross_topic"
    return configured or "program"


def purposes_reached_by(purpose, scope):
    """Which purposes a revocation of `purpose` at `scope` withdraws."""
    if scope == "cross_topic":
        return tuple(PURPOSES)
    if scope == "topic":
        topic = PURPOSE_TOPICS.get(purpose)
        return tuple(
            name for name in PURPOSES if PURPOSE_TOPICS.get(name) == topic
        )
    return (purpose,)


class ContactsConsentRepository(object):
    """The three axes, bound to one account per call.

    ``db`` is a :class:`libs.db.Database`. Every method takes the tenant
    first, binds `app.current_org_id` on the connection it opens, and carries
    the same value into the predicate -- the same three habits
    `ContactsRepository` keeps, for the same reason.
    """

    def __init__(self, db, revocation_scope=None):
        self.db = db
        #: The configured scope, overridden upward by the date gate above.
        self.revocation_scope = revocation_scope

    # -- tenant binding ----------------------------------------------------

    @staticmethod
    def _require_tenant(tenant_id):
        if not tenant_id or not isinstance(tenant_id, str):
            raise TenantScopeRequired()
        return tenant_id

    def _read(self, tenant_id):
        return _BoundConnection(self.db, tenant_id, write=False)

    def _write(self, tenant_id):
        return _BoundConnection(self.db, tenant_id, write=True)

    # -- consent -----------------------------------------------------------

    def grant_consent(
        self, tenant_id, address_id, purpose, evidence, actor,
        revocation_scope=None, now=None,
    ):
        """Record a legal grant. Permissive, so it takes a human (KTD13).

        Refused three ways, in this order: the actor is not a human, the human
        holds no authority over contacts, or the evidence is incomplete. The
        order matters only for the message -- an agent with a perfect evidence
        bundle still gets `HumanDecisionRequired`, because R12 makes the agent
        a proposer and never a decider.
        """
        self._require_tenant(tenant_id)
        _require_purpose(purpose)
        if actor.kind != "human" or not actor.holds(*GRANT_AUTHORITIES):
            raise HumanDecisionRequired(
                "granting consent requires an authorized human decision"
            )
        missing = evidence.missing_fields()
        if missing:
            raise ConsentEvidenceRequired(missing)
        moment = now or _utcnow()
        with self._write(tenant_id) as conn:
            address = self._address(conn, tenant_id, address_id)
            row = self._insert_consent(
                conn, tenant_id, address, purpose,
                state="granted",
                transition_kind="permissive",
                actor=actor,
                decided_by_principal_id=actor.principal_id,
                decided_by_authority=_granting_authority(actor),
                evidence=evidence,
                expires_at=evidence.expires_at,
                revocation_scope=resolve_revocation_scope(
                    moment, revocation_scope or self.revocation_scope,
                ),
                retained_until=evidence.retention_floor(moment),
                recorded_at=moment,
            )
        return _record(row, _CONSENT_COLUMNS)

    def propose_consent(
        self, tenant_id, address_id, purpose, actor, source=None, now=None,
    ):
        """An agent's claim that consent exists, recorded as unproven.

        Lands in 'pending_evidence', which is not consent and never becomes
        consent on its own. It exists so a conversational proposal is visible
        in the review queue instead of being discarded or, worse, written as a
        grant nobody authorised.
        """
        self._require_tenant(tenant_id)
        _require_purpose(purpose)
        moment = now or _utcnow()
        with self._write(tenant_id) as conn:
            address = self._address(conn, tenant_id, address_id)
            row = self._insert_consent(
                conn, tenant_id, address, purpose,
                state="pending_evidence",
                transition_kind="proposed",
                actor=actor,
                decided_by_principal_id=None,
                decided_by_authority=None,
                evidence=None,
                expires_at=None,
                revocation_scope=resolve_revocation_scope(
                    moment, self.revocation_scope,
                ),
                retained_until=_plus_years(moment, RETENTION_FLOOR_YEARS),
                recorded_at=moment,
                source=source or "agent_proposal",
            )
        return _record(row, _CONSENT_COLUMNS)

    def record_opt_out(
        self, tenant_id, address_id, purpose, actor=None, source=None,
        reason=None, revocation_scope=None, now=None,
    ):
        """Withdraw consent. Restrictive, so it self-executes.

        This is the preference-centre shape: somebody unsubscribes from
        marketing and keeps receiving their delivery notifications. It writes
        consent withdrawals and nothing else -- no suppression -- because
        suppression is the other axis and blocking the whole channel here is
        precisely the bug purpose scoping exists to prevent.

        How many purposes it reaches is `revocation_scope`: one program today,
        every topic once the cross-topic duty is in force.
        """
        self._require_tenant(tenant_id)
        _require_purpose(purpose)
        moment = now or _utcnow()
        scope = resolve_revocation_scope(
            moment, revocation_scope or self.revocation_scope,
        )
        deciding_actor = actor or Actor.contact()
        written = []
        with self._write(tenant_id) as conn:
            address = self._address(conn, tenant_id, address_id)
            for reached in purposes_reached_by(purpose, scope):
                written.append(self._insert_consent(
                    conn, tenant_id, address, reached,
                    state="withdrawn",
                    transition_kind="restrictive",
                    actor=deciding_actor,
                    decided_by_principal_id=None,
                    decided_by_authority=None,
                    evidence=None,
                    expires_at=None,
                    revocation_scope=scope,
                    retained_until=_plus_years(moment, RETENTION_FLOOR_YEARS),
                    recorded_at=moment,
                    source=source or "preference_centre",
                    reason=reason,
                ))
        return [_record(row, _CONSENT_COLUMNS) for row in written]

    def record_inbound_opt_out(
        self, tenant_id, address_id, keyword="STOP", sender_id=None,
        message_body=None, source="provider_webhook", actor=None,
        content_ttl_seconds=DEFAULT_CONTENT_TTL_SECONDS, now=None,
    ):
        """A subscriber texted STOP. All three axes move, immediately.

        No human step, by design and against the letter of R12: an opt-out
        held in a review queue is an opt-out not honoured, and the requirement
        that consent changes need approval is about permissive changes (KTD13).

        Unlike `record_opt_out`, this is not purpose-scoped. A keyword sent to
        the number is a statement about the channel, so every purpose is
        withdrawn, the channel is suppressed, and the provider's own block is
        recorded alongside. The verbatim message is kept on the short content
        clock; the decision and its provenance are kept for years.
        """
        self._require_tenant(tenant_id)
        moment = now or _utcnow()
        deciding_actor = actor or Actor.contact()
        retained_until = _plus_years(moment, RETENTION_FLOOR_YEARS)
        content_expires_at = moment + timedelta(seconds=content_ttl_seconds)
        with self._write(tenant_id) as conn:
            address = self._address(conn, tenant_id, address_id)
            withdrawals = [
                self._insert_consent(
                    conn, tenant_id, address, purpose,
                    state="withdrawn",
                    transition_kind="restrictive",
                    actor=deciding_actor,
                    decided_by_principal_id=None,
                    decided_by_authority=None,
                    evidence=None,
                    expires_at=None,
                    revocation_scope="cross_topic",
                    retained_until=retained_until,
                    recorded_at=moment,
                    source=source,
                    reason=keyword,
                    inbound_message_body=message_body,
                    content_expires_at=(
                        content_expires_at if message_body else None
                    ),
                )
                for purpose in PURPOSES
            ]
            suppression = self._insert_suppression(
                conn, tenant_id, address,
                state="suppressed_by_optout",
                transition_kind="restrictive",
                reason_code=keyword,
                source=source,
                actor=deciding_actor,
                sender_id=sender_id,
                retained_until=retained_until,
                recorded_at=moment,
            )
            # The carrier blocked it too, and that is a separate fact from our
            # suppression -- it is the one a START will undo.
            self._insert_reachability(
                conn, tenant_id, address,
                state="blocked_by_provider",
                keyword=keyword,
                sender_id=sender_id,
                source=source,
                retained_until=retained_until,
                recorded_at=moment,
            )
        return {
            "consent": [_record(row, _CONSENT_COLUMNS) for row in withdrawals],
            "suppression": _record(suppression, _SUPPRESSION_COLUMNS),
        }

    def consent_state(
        self, tenant_id, address_id, channel, purpose, now=None,
    ):
        """The current reading for one (address, channel, purpose).

        Expiry is applied here rather than by a sweep. A grant whose
        `expires_at` has passed reads as 'expired' the moment it passes,
        because the alternative is a window in which a lapsed grant is
        indistinguishable from a live one and the width of that window is
        whatever the batch job's schedule happens to be.
        """
        self._require_tenant(tenant_id)
        _require_purpose(purpose)
        moment = now or _utcnow()
        with self._read(tenant_id) as conn:
            rows = conn.execute(
                "select " + _CONSENT_SELECT + " from contacts.consent_records "
                "where tenant_id = %s and address_id = %s and channel = %s "
                "and purpose = %s",
                (tenant_id, address_id, channel, purpose),
            ).fetchall()
        latest = _latest(rows, "recorded_at")
        if latest is None:
            return {
                "state": "unknown", "recorded_state": None,
                "purpose": purpose, "channel": channel,
                "consent_record_id": None, "expires_at": None,
            }
        reading = _record(latest, _CONSENT_COLUMNS)
        reading["recorded_state"] = reading["state"]
        expires_at = reading.get("expires_at")
        if (
            reading["state"] == "granted"
            and expires_at is not None
            and expires_at <= moment
        ):
            reading["state"] = "expired"
        return reading

    def consent_by_purpose(self, tenant_id, address_id, channel, now=None):
        """Every purpose's reading at once, for a review surface."""
        return {
            purpose: self.consent_state(
                tenant_id, address_id, channel, purpose, now=now,
            )
            for purpose in PURPOSES
        }

    # -- suppression -------------------------------------------------------

    def suppress(
        self, tenant_id, address_id, state, reason_code=None, source="system",
        actor=None, sender_id=None, now=None,
    ):
        """Block an address operationally. Restrictive, so it self-executes.

        A bounce handler, a provider complaint webhook, and an administrator
        all take this path with no approval step. Nothing here touches
        consent: a suppressed address may still hold a perfectly valid grant,
        and when the suppression is lifted that grant is still the one in
        force. Collapsing the two would either destroy a grant on a transient
        bounce or resurrect sending on a lift.
        """
        self._require_tenant(tenant_id)
        if state not in SUPPRESSION_STATES or state == "none":
            raise ValueError("not a suppressing state: %r" % (state,))
        moment = now or _utcnow()
        with self._write(tenant_id) as conn:
            address = self._address(conn, tenant_id, address_id)
            row = self._insert_suppression(
                conn, tenant_id, address,
                state=state,
                transition_kind="restrictive",
                reason_code=reason_code,
                source=source,
                actor=actor or Actor.system(),
                sender_id=sender_id,
                retained_until=_plus_years(moment, RETENTION_FLOOR_YEARS),
                recorded_at=moment,
            )
        return _record(row, _SUPPRESSION_COLUMNS)

    def lift_suppression(
        self, tenant_id, address_id, actor, reason_code=None, sender_id=None,
        source="operator", now=None,
    ):
        """Un-suppress. Administrator only, and only a human one.

        The narrowest authority gate in this module, and deliberately narrower
        than granting consent. Un-suppressing resumes sending to somebody who
        was blocked -- often because they asked to be -- so it is not
        delegated to the agent that observed the bounce clear, and it is not
        delegated to a contact manager who may otherwise edit the entire
        record.
        """
        self._require_tenant(tenant_id)
        if actor.kind != "human" or not actor.holds(AUTHORITY_ADMINISTER):
            raise AdministratorRequired(
                "lifting a suppression requires an administrator"
            )
        moment = now or _utcnow()
        with self._write(tenant_id) as conn:
            address = self._address(conn, tenant_id, address_id)
            row = self._insert_suppression(
                conn, tenant_id, address,
                state="none",
                transition_kind="permissive",
                reason_code=reason_code,
                source=source,
                actor=actor,
                sender_id=sender_id,
                decided_by_principal_id=actor.principal_id,
                decided_by_authority=AUTHORITY_ADMINISTER,
                retained_until=_plus_years(moment, RETENTION_FLOOR_YEARS),
                recorded_at=moment,
            )
        return _record(row, _SUPPRESSION_COLUMNS)

    def suppression_state(
        self, tenant_id, address_id, channel, sender_id=None,
    ):
        """The current block on this address and channel, if any.

        Account-wide rows (`sender_id is null`) and rows scoped to the sender
        being asked about are both in scope; a block recorded against some
        other sender is not, because Twilio's STOP is scoped to the number the
        subscriber replied to.
        """
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            rows = conn.execute(
                "select " + _SUPPRESSION_SELECT
                + " from contacts.address_suppressions "
                "where tenant_id = %s and address_id = %s and channel = %s",
                (tenant_id, address_id, channel),
            ).fetchall()
        scoped = [
            row for row in rows
            if row.get("sender_id") is None or row.get("sender_id") == sender_id
        ]
        latest = _latest(scoped, "recorded_at")
        if latest is None:
            return {"state": "none", "suppression_id": None, "reason_code": None}
        return _record(latest, _SUPPRESSION_COLUMNS)

    # -- address usability -------------------------------------------------

    def propose_address(
        self, tenant_id, address_id, actor, reason=None, now=None,
    ):
        """Mark a destination as claimed but unconfirmed.

        R12's agent-proposed number. Recorded on the address rather than on
        the person, because the fact is about the digits: a signed marketing
        grant proves the person agreed, not that the agent transcribed their
        number correctly.
        """
        self._require_tenant(tenant_id)
        moment = now or _utcnow()
        with self._write(tenant_id) as conn:
            address = self._address(conn, tenant_id, address_id)
            row = self._insert_usability(
                conn, tenant_id, address,
                state="proposed",
                transition_kind="proposed",
                proposed_by_actor_kind=actor.kind,
                proposed_by_principal_id=actor.principal_id,
                decided_by_principal_id=None,
                decided_by_authority=None,
                reason=reason,
                retained_until=_plus_years(moment, RETENTION_FLOOR_YEARS),
                recorded_at=moment,
            )
        return _record(row, _USABILITY_COLUMNS)

    def activate_address(
        self, tenant_id, address_id, actor, reason=None, now=None,
    ):
        """Make a proposed destination usable. Permissive, so it takes a human."""
        self._require_tenant(tenant_id)
        if actor.kind != "human" or not actor.holds(*GRANT_AUTHORITIES):
            raise HumanDecisionRequired(
                "activating an address requires an authorized human decision"
            )
        moment = now or _utcnow()
        with self._write(tenant_id) as conn:
            address = self._address(conn, tenant_id, address_id)
            row = self._insert_usability(
                conn, tenant_id, address,
                state="active",
                transition_kind="permissive",
                proposed_by_actor_kind=None,
                proposed_by_principal_id=None,
                decided_by_principal_id=actor.principal_id,
                decided_by_authority=_granting_authority(actor),
                reason=reason,
                retained_until=_plus_years(moment, RETENTION_FLOOR_YEARS),
                recorded_at=moment,
            )
        return _record(row, _USABILITY_COLUMNS)

    def retire_address(
        self, tenant_id, address_id, actor=None, reason=None, now=None,
    ):
        """Take a destination out of service. Restrictive, so it self-executes."""
        self._require_tenant(tenant_id)
        moment = now or _utcnow()
        with self._write(tenant_id) as conn:
            address = self._address(conn, tenant_id, address_id)
            row = self._insert_usability(
                conn, tenant_id, address,
                state="retired",
                transition_kind="restrictive",
                proposed_by_actor_kind=None,
                proposed_by_principal_id=None,
                decided_by_principal_id=(actor.principal_id if actor else None),
                decided_by_authority=None,
                reason=reason,
                retained_until=_plus_years(moment, RETENTION_FLOOR_YEARS),
                recorded_at=moment,
            )
        return _record(row, _USABILITY_COLUMNS)

    def usability_state(self, tenant_id, address_id):
        """Whether this destination may be used. Absent means 'proposed'.

        Fail-closed on purpose. An address written by some future import path
        that forgot to record a decision is unusable until a human looks at
        it, rather than usable because nobody thought about it.
        """
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            rows = conn.execute(
                "select " + _USABILITY_SELECT
                + " from contacts.address_usability_decisions "
                "where tenant_id = %s and address_id = %s",
                (tenant_id, address_id),
            ).fetchall()
        latest = _latest(rows, "recorded_at")
        if latest is None:
            return {"state": "proposed", "usability_decision_id": None}
        return _record(latest, _USABILITY_COLUMNS)

    # -- provider reachability (not an axis, and not consent) --------------

    def record_provider_restart(
        self, tenant_id, address_id, keyword="START", sender_id=None,
        source="provider_webhook", now=None,
    ):
        """The carrier will carry messages again. Nothing else changed.

        Twilio answers START and UNSTOP itself and delivery resumes at the
        carrier before we are told. This method writes one row, to one ledger.
        It cannot grant consent and it cannot lift a suppression -- those take
        `grant_consent` with fresh evidence and `lift_suppression` with an
        administrator, and a provider keyword is neither.
        """
        self._require_tenant(tenant_id)
        moment = now or _utcnow()
        with self._write(tenant_id) as conn:
            address = self._address(conn, tenant_id, address_id)
            row = self._insert_reachability(
                conn, tenant_id, address,
                state="reachable",
                keyword=keyword,
                sender_id=sender_id,
                source=source,
                retained_until=_plus_years(moment, RETENTION_FLOOR_YEARS),
                recorded_at=moment,
            )
        return _record(row, _REACHABILITY_COLUMNS)

    def provider_reachability(
        self, tenant_id, address_id, channel, sender_id=None,
    ):
        """What the carrier will currently carry. Absent means reachable."""
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            rows = conn.execute(
                "select " + _REACHABILITY_SELECT
                + " from contacts.provider_reachability_events "
                "where tenant_id = %s and address_id = %s and channel = %s",
                (tenant_id, address_id, channel),
            ).fetchall()
        scoped = [
            row for row in rows
            if row.get("sender_id") is None or row.get("sender_id") == sender_id
        ]
        latest = _latest(scoped, "recorded_at")
        if latest is None:
            return {"state": "reachable", "reachability_event_id": None}
        return _record(latest, _REACHABILITY_COLUMNS)

    # -- reading them together ---------------------------------------------

    def axes(
        self, tenant_id, address_id, channel, purpose, sender_id=None,
        now=None,
    ):
        """All four readings, separately, in one call.

        Returned as four keys rather than reduced to one verdict, because the
        whole argument of KTD12 is that they do not reduce: a valid grant and
        a bounce suppression are both true at once, and a surface that shows
        an operator only the losing one gives them no way to act.
        """
        return {
            "consent": self.consent_state(
                tenant_id, address_id, channel, purpose, now=now,
            ),
            "suppression": self.suppression_state(
                tenant_id, address_id, channel, sender_id=sender_id,
            ),
            "usability": self.usability_state(tenant_id, address_id),
            "provider_reachability": self.provider_reachability(
                tenant_id, address_id, channel, sender_id=sender_id,
            ),
        }

    def evaluate_eligibility(
        self, tenant_id, address_id, channel, purpose, sender_id=None,
        now=None,
    ):
        """Re-evaluated before every effect (R16, R25), never cached.

        Order is usability, then suppression, then carrier reachability, then
        consent. It runs most-fundamental first so the reason code names the
        thing an operator would have to fix first: telling them consent is
        missing on a number that was never approved sends them to the wrong
        screen.

        The reason code is deliberately not folded into any approval hash
        (KTD3). Every one of these changes lawfully between plan time and
        dispatch, and a lawful suppression must not be indistinguishable from
        tampering.
        """
        readings = self.axes(
            tenant_id, address_id, channel, purpose,
            sender_id=sender_id, now=now,
        )
        usability = readings["usability"]["state"]
        if usability != "active":
            return EligibilityDecision(
                False,
                "address_retired" if usability == "retired"
                else "address_not_usable",
                readings,
            )
        suppression = readings["suppression"]["state"]
        if suppression != "none":
            return EligibilityDecision(False, suppression, readings)
        if readings["provider_reachability"]["state"] != "reachable":
            return EligibilityDecision(False, "provider_unreachable", readings)
        consent = readings["consent"]["state"]
        if consent != "granted":
            return EligibilityDecision(
                False,
                {
                    "expired": "consent_expired",
                    "withdrawn": "consent_withdrawn",
                }.get(consent, "consent_missing"),
                readings,
            )
        return EligibilityDecision(True, "eligible", readings)

    # -- retention ---------------------------------------------------------

    def purge_expired_content(self, tenant_id, now=None):
        """Redact due message bodies. The decision stays.

        The verbatim text somebody sent is content and expires on the content
        clock. The fact that they opted out, when, through which channel, and
        on whose authority is audit, and it is held for the retention floor --
        five years, ten where the evidence is a recording. An opt-out we
        cannot prove we honoured is indistinguishable from one we did not, so
        this method is written so that it can only ever remove the body: the
        database trigger refuses an update that changes anything else.
        """
        self._require_tenant(tenant_id)
        moment = now or _utcnow()
        purged = []
        with self._write(tenant_id) as conn:
            due = conn.execute(
                "select " + _CONSENT_SELECT + " from contacts.consent_records "
                "where tenant_id = %s and content_purged_at is null "
                "and inbound_message_body is not null "
                "and content_expires_at <= %s",
                (tenant_id, moment),
            ).fetchall()
            for row in due:
                conn.execute(
                    "update contacts.consent_records "
                    "set inbound_message_body = %s, content_purged_at = %s "
                    "where tenant_id = %s and consent_record_id = %s "
                    "returning consent_record_id",
                    (None, moment, tenant_id, row["consent_record_id"]),
                )
                purged.append(row["consent_record_id"])
        return purged

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _address(conn, tenant_id, address_id):
        row = conn.execute(
            "select " + _ADDRESS_SELECT
            + " from contacts.contact_addresses "
            "where tenant_id = %s and address_id = %s",
            (tenant_id, address_id),
        ).fetchone()
        if row is None:
            raise AddressNotFound()
        return row

    @staticmethod
    def _insert_consent(
        conn, tenant_id, address, purpose, state, transition_kind, actor,
        decided_by_principal_id, decided_by_authority, evidence, expires_at,
        revocation_scope, retained_until, recorded_at, source=None,
        reason=None, inbound_message_body=None, content_expires_at=None,
    ):
        return conn.execute(
            """
            insert into contacts.consent_records(
                consent_record_id, tenant_id, contact_id, address_id, channel,
                purpose, state, transition_kind, capture_method, captured_at,
                captured_at_local, capture_timezone, jurisdiction,
                disclosure_text, disclosure_hash, default_unchecked,
                legal_basis, source, actor_kind, actor_principal_id,
                decided_by_principal_id, decided_by_authority, expires_at,
                revocation_scope, inbound_message_body, content_expires_at,
                content_purged_at, retained_until, recorded_at
            ) values (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            returning """ + _CONSENT_SELECT,
            (
                "consent:%s" % generate_ulid(),
                tenant_id,
                address["contact_id"],
                address["address_id"],
                address["channel"],
                purpose,
                state,
                transition_kind,
                evidence.capture_method if evidence else None,
                evidence.captured_at if evidence else None,
                evidence.captured_at_local if evidence else None,
                evidence.capture_timezone if evidence else None,
                evidence.jurisdiction if evidence else None,
                evidence.disclosure_text if evidence else None,
                evidence.disclosure_hash if evidence else None,
                evidence.default_unchecked if evidence else None,
                evidence.legal_basis if evidence else None,
                (evidence.source if evidence else None) or source or reason,
                actor.kind,
                actor.principal_id,
                decided_by_principal_id,
                decided_by_authority,
                expires_at,
                revocation_scope,
                inbound_message_body,
                content_expires_at,
                None,
                retained_until,
                recorded_at,
            ),
        ).fetchone()

    @staticmethod
    def _insert_suppression(
        conn, tenant_id, address, state, transition_kind, reason_code, source,
        actor, sender_id, retained_until, recorded_at,
        decided_by_principal_id=None, decided_by_authority=None,
    ):
        return conn.execute(
            """
            insert into contacts.address_suppressions(
                suppression_id, tenant_id, address_id, channel, sender_id,
                state, transition_kind, reason_code, source, actor_kind,
                actor_principal_id, decided_by_principal_id,
                decided_by_authority, retained_until, recorded_at
            ) values (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            returning """ + _SUPPRESSION_SELECT,
            (
                "suppression:%s" % generate_ulid(),
                tenant_id,
                address["address_id"],
                address["channel"],
                sender_id,
                state,
                transition_kind,
                reason_code,
                source,
                actor.kind,
                actor.principal_id,
                decided_by_principal_id,
                decided_by_authority,
                retained_until,
                recorded_at,
            ),
        ).fetchone()

    @staticmethod
    def _insert_usability(
        conn, tenant_id, address, state, transition_kind,
        proposed_by_actor_kind, proposed_by_principal_id,
        decided_by_principal_id, decided_by_authority, reason, retained_until,
        recorded_at,
    ):
        return conn.execute(
            """
            insert into contacts.address_usability_decisions(
                usability_decision_id, tenant_id, address_id, state,
                transition_kind, proposed_by_actor_kind,
                proposed_by_principal_id, decided_by_principal_id,
                decided_by_authority, reason, retained_until, recorded_at
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning """ + _USABILITY_SELECT,
            (
                "usability:%s" % generate_ulid(),
                tenant_id,
                address["address_id"],
                state,
                transition_kind,
                proposed_by_actor_kind,
                proposed_by_principal_id,
                decided_by_principal_id,
                decided_by_authority,
                reason,
                retained_until,
                recorded_at,
            ),
        ).fetchone()

    @staticmethod
    def _insert_reachability(
        conn, tenant_id, address, state, keyword, sender_id, source,
        retained_until, recorded_at,
    ):
        return conn.execute(
            """
            insert into contacts.provider_reachability_events(
                reachability_event_id, tenant_id, address_id, channel,
                sender_id, state, provider_keyword, source, retained_until,
                recorded_at
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning """ + _REACHABILITY_SELECT,
            (
                "reachability:%s" % generate_ulid(),
                tenant_id,
                address["address_id"],
                address["channel"],
                sender_id,
                state,
                keyword,
                source,
                retained_until,
                recorded_at,
            ),
        ).fetchone()


class _BoundConnection(object):
    """`app.current_org_id` set before anything runs on the connection.

    The same object `ContactsRepository` uses, for the same reason: a pooled
    connection outlives the request that checked it out, and binding the
    context from the same argument the `where` clause uses is what stops the
    policy and the predicate disagreeing.
    """

    def __init__(self, db, tenant_id, write):
        self.db = db
        self.tenant_id = tenant_id
        self._context = db.transaction() if write else db.connection()

    def __enter__(self):
        conn = self._context.__enter__()
        self._connection = conn
        self._previous_row_factory = getattr(conn, "row_factory", None)
        if self._previous_row_factory is not None:
            conn.row_factory = dict_row
        self.db.set_org_context(conn, self.tenant_id)
        return conn

    def __exit__(self, *exc_info):
        if self._previous_row_factory is not None:
            self._connection.row_factory = self._previous_row_factory
        return self._context.__exit__(*exc_info)


def _utcnow():
    return datetime.now(timezone.utc)


def _plus_years(moment, years):
    try:
        return moment.replace(year=moment.year + years)
    except ValueError:
        # 29 February. The floor moves forward to 1 March rather than back to
        # the 28th, because a retention floor may lengthen and never shorten.
        return moment.replace(year=moment.year + years, month=3, day=1)


def _require_purpose(purpose):
    if purpose not in PURPOSES:
        raise ValueError("unknown consent purpose: %r" % (purpose,))
    return purpose


def _granting_authority(actor):
    return (
        AUTHORITY_ADMINISTER if actor.holds(AUTHORITY_ADMINISTER)
        else AUTHORITY_MANAGE_CONTACTS
    )


def _latest(rows, time_column, sequence_column=_LEDGER_SEQUENCE):
    """Newest row wins, with the ledger sequence breaking ties.

    Ties are the ordinary case, not the edge one: an inbound opt-out writes one
    withdrawal per purpose inside a single transaction, all stamped with the
    same instant, and `record_opt_out` does the same for every purpose a
    cross-topic revocation reaches. So the tiebreak decides real readings.

    It is not the identifier, though it reads as if it could be. The
    identifiers here are ULIDs, and a ULID is only ordered across millisecond
    boundaries -- inside one millisecond its low 80 bits are random, so
    ordering five withdrawals written in one transaction by identifier is a
    coin flip, and the coin picks which purpose the address reads as withdrawn
    for. `ledger_sequence` is 0018's identity column: assigned by the database
    in insertion order, never supplied by a caller, and frozen by the same
    append-only triggers that hold the rest of the row.
    """
    ordered = sorted(
        rows, key=lambda row: (row.get(time_column), row.get(sequence_column)),
    )
    return ordered[-1] if ordered else None


def _record(row, columns):
    if row is None:
        return None
    if isinstance(row, dict):
        return {name: row.get(name) for name in columns}
    return dict(zip(columns, row))
