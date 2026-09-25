"""The review queue an agent proposal lands in, and the decision that ends it.

R12 says an agent may propose and a human decides. U6 built the ledgers that
hold both halves -- ``propose_address`` and ``propose_consent`` write claims,
``activate_address`` and ``grant_consent`` write decisions -- and this module
is the queue between them.

It exists in the same unit as the propose capability on purpose. Without it,
``contacts.propose`` writes records nobody can approve, so R12 is not merely
unimplemented but unimplementable, and the agent re-proposes the same person
every turn because nothing tells it the last proposal is still sitting there.

Two consequences of U6 that this module absorbs rather than passes on:

**An address with no usability decision reads as ``proposed``, i.e. unusable.**
So approving a proposal is never just marking a row: it has to call
``activate_address``, or the address stays exactly where it was and the queue
looks like it worked.

**Consent is not usability.** Activating an address makes it dialable in
principle; it grants nothing. A proposal that carried a consent claim is only
finished when consent is granted with U6's evidence fields, by a named human
with a named authority -- so ``approve`` refuses to close such a proposal on
an activation alone.
"""

from libs.contacts_consent import (
    AUTHORITY_ADMINISTER,
    AUTHORITY_MANAGE_CONTACTS,
    CHANNELS,
    ConsentEvidenceRequired,
    HumanDecisionRequired,
    PURPOSES,
)
from libs.contacts_permissions import mask_destination
from libs.contacts_repository import (
    normalize_channel_address,
    record_version as compute_record_version,
)
from libs.tenancy import TenantScopeRequired
from libs.ulid import generate_ulid


__all__ = [
    "AddressCaptureBook",
    "CaptureNotFound",
    "ProposalIncomplete",
    "ProposalNotFound",
    "ProposalQueue",
    "StaleRecord",
    "UnsupportedProposal",
]


GRANT_AUTHORITIES = (AUTHORITY_MANAGE_CONTACTS, AUTHORITY_ADMINISTER)


class CaptureNotFound(LookupError):
    """No such capture, or it belongs to another account."""

    def __init__(self, message="address capture not found"):
        super(CaptureNotFound, self).__init__(message)


class ProposalNotFound(LookupError):
    def __init__(self, message="proposal not found"):
        super(ProposalNotFound, self).__init__(message)


class ProposalIncomplete(ValueError):
    """The decision would leave the proposal in a state nobody asked for."""


class StaleRecord(ValueError):
    """The record moved since it was resolved, so the change is not this one."""

    def __init__(self, message="contact record changed since resolution"):
        super(StaleRecord, self).__init__(message)


class UnsupportedProposal(ValueError):
    """This mutation class has no agent-side proposal path."""


class AddressCaptureBook(object):
    """Server-side custody of the digits a person typed.

    This is the seam that makes "nothing the model emits may become a
    destination" true rather than aspirational. The turn text arrives at the
    server, the server -- not the model -- lifts the destination out of it and
    mints an opaque reference, and the propose capability accepts only the
    reference. The model never sees the digits, so it cannot repeat them,
    paraphrase them, or invent a neighbouring number.

    Backed by a plain mapping by default. A durable, tenant-bound store is a
    later unit's work; the contract that matters here -- a capture is minted
    server-side, is scoped to one tenant, and is redeemed once -- does not
    change when the backing does.
    """

    def __init__(self, store=None):
        self._store = {} if store is None else store

    def capture(self, tenant_id, channel, text, captured_from="requester_turn"):
        if not tenant_id:
            raise TenantScopeRequired()
        if channel not in CHANNELS:
            raise ValueError("unsupported channel: %r" % (channel,))
        normalized = normalize_channel_address(channel, text)
        if not normalized:
            raise ValueError("address is empty")
        reference = "capture:%s" % generate_ulid()
        self._store[(tenant_id, reference)] = {
            "channel": channel,
            "address": (text or "").strip(),
            "address_normalized": normalized,
            "captured_from": captured_from,
        }
        return reference

    def redeem(self, tenant_id, reference):
        if not tenant_id:
            raise TenantScopeRequired()
        captured = self._store.get((tenant_id, reference))
        if captured is None:
            # Same answer for "never existed" and "belongs to another
            # account", for the reason the rest of contacts gives one: a
            # distinguishable refusal confirms the row is real.
            raise CaptureNotFound()
        return dict(captured)


class ProposalQueue(object):
    """Agent claims on one side, an authorized human decision on the other."""

    def __init__(
        self, access, consent, contacts=None, captures=None, clock=None,
    ):
        self.access = access
        self.consent = consent
        self.contacts = contacts or access.contacts
        self.captures = captures or AddressCaptureBook()
        self.clock = clock

    def _now(self, now=None):
        if now is not None:
            return now
        return self.clock() if self.clock else None

    # -- proposing ---------------------------------------------------------

    def propose_contact(
        self, tenant_id, principal_id, actor, display_name, primary_branch_id,
        channel, address_capture_ref, note=None, now=None,
    ):
        """Claim that a person exists and can be reached here. Nothing more.

        Idempotent on the destination, which is the whole reason the queue
        does not fill with duplicates: an agent that proposes the same number
        twice is told about the proposal already waiting instead of creating a
        second person who shares it.
        """
        if not tenant_id:
            raise TenantScopeRequired()
        moment = self._now(now)
        captured = self.captures.redeem(tenant_id, address_capture_ref)
        if channel != captured["channel"]:
            # The channel the model named and the channel the server captured
            # disagree. Refused rather than reconciled: the capture is the
            # grounded half and the model's is the guess.
            raise UnsupportedProposal("proposal channel does not match capture")
        existing = self.contacts.contact_by_address(
            tenant_id, channel, captured["address"],
        )
        if existing is not None:
            address = self._address_for(
                tenant_id, existing["contact_id"], channel,
                captured["address_normalized"],
            )
            state = self.consent.usability_state(
                tenant_id, address["address_id"],
            )
            return {
                "proposal_id": address["address_id"],
                "contact_id": existing["contact_id"],
                "state": state.get("state"),
                "duplicate": True,
            }
        contact = self.contacts.create_contact(
            tenant_id, primary_branch_id, display_name,
            source="agent_proposal",
        )
        address = self.contacts.add_address(
            tenant_id, contact["contact_id"], channel, captured["address"],
            label=note, is_primary=True,
        )
        decision = self.consent.propose_address(
            tenant_id, address["address_id"], actor,
            reason=note or "proposed in conversation", now=moment,
        )
        return {
            "proposal_id": address["address_id"],
            "contact_id": contact["contact_id"],
            "state": decision["state"],
            "duplicate": False,
        }

    def propose_update(
        self, tenant_id, principal_id, actor, contact_id, record_version,
        changes, now=None,
    ):
        """Claim a change to a record the requester already resolved.

        The record version is checked first and refused loudly. A proposal
        raised against a record that has since moved is a proposal about a
        different record, and applying it later would silently overwrite
        whatever the move was.

        Only the two change classes the U6 ledgers can actually hold are
        accepted: another address, and a consent claim. A field edit has no
        ledger yet, so it is refused by name rather than accepted and dropped.
        """
        if not tenant_id:
            raise TenantScopeRequired()
        moment = self._now(now)
        contact = self.contacts.get_contact(tenant_id, contact_id)
        if contact is None:
            raise ProposalNotFound("contact not found")
        addresses = self.contacts.addresses(tenant_id, contact_id)
        if compute_record_version(contact, addresses) != record_version:
            raise StaleRecord()
        unknown = set(changes or {}) - {"add_address", "consent"}
        if unknown or not changes:
            raise UnsupportedProposal(
                "no proposal path for: %s" % ", ".join(sorted(unknown or {"(empty)"}))
            )
        proposals = []
        add_address = (changes or {}).get("add_address")
        if add_address:
            captured = self.captures.redeem(
                tenant_id, add_address.get("address_capture_ref"),
            )
            address = self.contacts.add_address(
                tenant_id, contact_id, captured["channel"], captured["address"],
            )
            decision = self.consent.propose_address(
                tenant_id, address["address_id"], actor,
                reason="proposed in conversation", now=moment,
            )
            proposals.append({
                "proposal_id": address["address_id"],
                "kind": "address",
                "state": decision["state"],
            })
        consent_claim = (changes or {}).get("consent")
        if consent_claim:
            address_id = consent_claim.get("address_id")
            purpose = consent_claim.get("purpose")
            if purpose not in PURPOSES:
                raise UnsupportedProposal("unsupported consent purpose")
            record = self.consent.propose_consent(
                tenant_id, address_id, purpose, actor, now=moment,
            )
            proposals.append({
                "proposal_id": record["consent_record_id"],
                "kind": "consent",
                "state": record["state"],
            })
        return {
            "contact_id": contact_id,
            "record_version": record_version,
            "proposals": tuple(proposals),
        }

    # -- reviewing ---------------------------------------------------------

    def pending(self, tenant_id, principal_id, limit=200, now=None):
        """Everything waiting on a human, bounded to what they may see.

        Assembled from the branches this principal holds view over, so an
        operator reviews their own account's queue and learns nothing about
        anyone else's -- including that anyone else's exists.
        """
        if not tenant_id:
            raise TenantScopeRequired()
        moment = self._now(now)
        entries = []
        for contact in self.access.search(
            tenant_id, principal_id, "", limit=limit,
        ):
            branch = self.contacts.get_branch(
                tenant_id, contact["primary_branch_id"],
            ) or {}
            for address in self.contacts.addresses(
                tenant_id, contact["contact_id"],
            ):
                usability = self.consent.usability_state(
                    tenant_id, address["address_id"],
                )
                if usability.get("state") != "proposed":
                    continue
                entries.append({
                    "proposal_id": address["address_id"],
                    "kind": "address",
                    "contact_id": contact["contact_id"],
                    "display_name": contact.get("display_name"),
                    "branch_path": branch.get("path"),
                    "channel": address["channel"],
                    "destination": self._masked(
                        tenant_id, address, branch.get("path"),
                    ),
                    "proposed_by_actor_kind": usability.get(
                        "proposed_by_actor_kind"
                    ),
                    "proposed_by_principal_id": usability.get(
                        "proposed_by_principal_id"
                    ),
                    "proposed_at": usability.get("recorded_at"),
                    "pending_consent": self._pending_consent(
                        tenant_id, address, moment,
                    ),
                })
        entries.sort(key=lambda item: (
            str(item.get("proposed_at") or ""), item["proposal_id"],
        ))
        return entries

    def approve(
        self, tenant_id, proposal_id, actor, evidence=None, purposes=(),
        reason=None, now=None,
    ):
        """Make a proposed destination usable, and settle its consent claim.

        Both halves, in that order, in one call. Splitting them would let an
        operator activate an address and believe they had also granted the
        consent the agent claimed -- which is how an unlawful send happens
        with an approval behind it.
        """
        if not tenant_id:
            raise TenantScopeRequired()
        if actor.kind != "human" or not actor.holds(*GRANT_AUTHORITIES):
            raise HumanDecisionRequired(
                "approving a proposal requires an authorized human decision"
            )
        moment = self._now(now)
        address = self._address(tenant_id, proposal_id)
        claimed = self._pending_consent(tenant_id, address, moment)
        purposes = tuple(purposes or ())
        if claimed and not purposes:
            raise ProposalIncomplete(
                "this proposal claims consent for %s; approve it or reject it"
                % ", ".join(claimed)
            )
        if purposes and evidence is None:
            raise ConsentEvidenceRequired(("evidence",))
        usability = self.consent.activate_address(
            tenant_id, proposal_id, actor, reason=reason, now=moment,
        )
        granted = []
        for purpose in purposes:
            granted.append(self.consent.grant_consent(
                tenant_id, proposal_id, purpose, evidence, actor, now=moment,
            ))
        return {
            "proposal_id": proposal_id,
            "usability": usability,
            "granted_purposes": tuple(purposes),
            "consent": tuple(granted),
        }

    def reject(self, tenant_id, proposal_id, actor, reason=None, now=None):
        """Take the destination out of service. Restrictive, so it just runs."""
        if not tenant_id:
            raise TenantScopeRequired()
        moment = self._now(now)
        self._address(tenant_id, proposal_id)
        return self.consent.retire_address(
            tenant_id, proposal_id, actor=actor,
            reason=reason or "rejected in review", now=moment,
        )

    # -- internals ---------------------------------------------------------

    def _address(self, tenant_id, address_id):
        address = self.contacts.get_address(tenant_id, address_id)
        if address is None:
            raise ProposalNotFound()
        return address

    def _address_for(self, tenant_id, contact_id, channel, normalized):
        for address in self.contacts.addresses(tenant_id, contact_id):
            if (
                address["channel"] == channel
                and address["address_normalized"] == normalized
            ):
                return address
        raise ProposalNotFound("address not found on this contact")

    def _pending_consent(self, tenant_id, address, moment):
        channel = address.get("channel")
        if channel is None:
            return ()
        readings = self.consent.consent_by_purpose(
            tenant_id, address["address_id"], channel, now=moment,
        )
        return tuple(sorted(
            purpose for purpose, reading in readings.items()
            if reading.get("state") == "pending_evidence"
        ))

    def _masked(self, tenant_id, address, branch_path):
        return mask_destination(
            address["channel"], address["address"],
            address_id=address["address_id"], tenant_id=tenant_id,
            branch_path=branch_path,
            last_contacted_at=address.get("last_contacted_at"),
        ).as_dict()
