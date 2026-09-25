"""Grounded contact resolution as a durable resolver run.

Three things this module refuses to do, and they are the whole point.

**It never returns a destination.** A candidate carries a masked destination
built by ``libs.contacts_permissions.mask_destination`` -- a country code,
trailing digits, a branch path, and a fingerprint derived from the address
identifier. That is enough for a person to answer "is this who I meant" and
not enough for anything to dial.

**It never guesses between people.** ``ambiguous`` is a first-class outcome,
not an error and not a silent pick of the first row. R13 allows preferring the
most recently human-confirmed match, and the permission is narrower than it
first reads: *only while it remains policy-compatible*. A contact somebody
confirmed last week whose consent has since expired is not a safe default, it
is a stale one, and the resolver disambiguates instead.

**It never crosses an account or a branch.** Every read starts from
``ContactsAccess``, whose searches are bounded to the branches the requester
holds view over, inside one tenant. Two people with the same name in two
accounts cannot appear in one candidate set, because the pool they are drawn
from was never larger than one account.

The outcome vocabulary is the existing one -- ``matched``, ``ambiguous``,
``not_found``, ``exhausted``, ``failed`` -- imported from
``WorkflowRepository`` rather than restated, so a resolver run over contacts
completes through the same durable path a resolver run over Slack does.
"""

import hashlib
import unicodedata
from datetime import datetime, timedelta, timezone

from agents.orchestrator.workflow_repository import WorkflowRepository
from libs.contacts_permissions import mask_destination
from libs.contacts_repository import record_version
from libs.tenancy import TenantScopeRequired


__all__ = [
    "ContactResolver",
    "DEFAULT_RESOLVER_BUDGET",
    "RESOLVER_OUTCOMES",
    "RESOLVER_TERMINAL_STATUSES",
    "ResolutionBlocked",
    "CONFIRMATION_WINDOW",
    "fold",
    "record_version",
]


#: Imported, never restated. A second copy of an outcome set is a second thing
#: to forget when one of them grows a member.
RESOLVER_OUTCOMES = WorkflowRepository.RESOLVER_OUTCOMES
RESOLVER_TERMINAL_STATUSES = WorkflowRepository.RESOLVER_TERMINAL_STATUSES
DEFAULT_RESOLVER_BUDGET = dict(WorkflowRepository.DEFAULT_RESOLVER_BUDGET)

#: How recent a human confirmation has to be before it may break a tie. Long
#: enough that a person disambiguating twice in one working session is not
#: asked a third time; short enough that a confirmation nobody remembers
#: making cannot silently choose a recipient months later.
CONFIRMATION_WINDOW = timedelta(days=14)

#: Provenance values, in the same shape Slack entity refs already carry.
MATCHED_BY_EXACT_NAME = "exact_name"
MATCHED_BY_NAME_TOKENS = "name_tokens"
MATCHED_BY_NEAR_NAME = "near_name"
MATCHED_BY_RECENT_CONFIRMATION = "recent_confirmation"

#: Why an ambiguous run refused to pick. Every one of these is a distinct
#: thing an operator would do differently, which is why they are not one
#: "ambiguous" reason.
REASON_MULTIPLE_MATCHES = "multiple_matches"
REASON_CONFIRMATION_TIE = "confirmation_tie"
REASON_CONFIRMATION_STALE = "confirmation_stale"
REASON_CONFIRMATION_NOT_POLICY_COMPATIBLE = "confirmation_not_policy_compatible"
REASON_CONFIRMATION_CONFLICT = "confirmation_conflict"
REASON_BUDGET_EXHAUSTED = "budget_exhausted"
REASON_NO_VISIBLE_BRANCH = "no_visible_branch"
REASON_NO_MATCH = "no_match"


class ResolutionBlocked(Exception):
    """This run may not be turned into an effect.

    Carries the outcome and the candidate set, because the caller's next move
    is nearly always to show the candidates rather than to report a failure.
    """

    def __init__(self, outcome, reason, candidates=()):
        self.outcome = outcome
        self.reason = reason
        self.candidates = tuple(candidates)
        super(ResolutionBlocked, self).__init__(
            "resolution is %s: %s" % (outcome, reason)
        )


def fold(value):
    """Casefold, strip accents, collapse whitespace.

    R4 asks for Spanish, English, typo-tolerant and mixed-language requests.
    Accent folding is most of that on its own: a person typing on an English
    keyboard writes "Perez" for "Pérez" and means the same colleague, and a
    store that answers "no such contact" there teaches them the directory is
    empty rather than that their keyboard is.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    stripped = "".join(
        character for character in text
        if not unicodedata.combining(character)
    )
    return " ".join(stripped.casefold().split())


def _tokens(value):
    return tuple(token for token in fold(value).split(" ") if token)


def _within_one_edit(left, right):
    """Whether two tokens differ by at most one insert, delete or substitute.

    Deliberately one, not a tuned similarity score. One edit covers the
    typing mistakes people actually make in a name; two starts merging
    different names, and merging different names is the failure this whole
    module exists to prevent.
    """
    if abs(len(left) - len(right)) > 1:
        return False
    if left == right:
        return True
    if len(left) == len(right):
        differences = sum(1 for a, b in zip(left, right) if a != b)
        return differences <= 1
    longer, shorter = (left, right) if len(left) > len(right) else (right, left)
    for index in range(len(longer)):
        if longer[:index] + longer[index + 1:] == shorter:
            return True
    return False


def _utcnow():
    return datetime.now(timezone.utc)


class ContactResolver(object):
    """Resolve a name a person said into candidates the server can bind.

    ``access`` is a :class:`libs.contacts_permissions.ContactsAccess`, which is
    the only reason this class is safe: it takes the requester's principal on
    every call and bounds every read to the branches that principal holds view
    over, inside one tenant.
    """

    def __init__(self, access=None, contacts=None, consent=None, clock=None):
        if access is None:
            raise ValueError("a branch-bounded contacts access is required")
        self.access = access
        self.contacts = contacts or access.contacts
        #: Optional. Without it the resolver still masks and still refuses to
        #: guess; it simply has no eligibility axis, and says so by leaving
        #: every candidate's consent reading empty.
        self.consent = consent if consent is not None else access.consent
        self.clock = clock or _utcnow

    # -- resolution --------------------------------------------------------

    def resolve(
        self, tenant_id, principal_id, query, channel=None, purpose=None,
        confirmations=(), budget=None, now=None,
    ):
        """One durable resolver run, terminal on return."""
        if not tenant_id:
            raise TenantScopeRequired()
        if not principal_id:
            raise TenantScopeRequired("a requester is required to resolve")
        moment = now or self.clock()
        budget = {**DEFAULT_RESOLVER_BUDGET, **dict(budget or {})}
        ceiling = int(budget.get("max_candidates") or 0)

        # An empty query is not a search, it is a directory dump. Refused
        # here rather than answered, because "resolve everyone" is exactly the
        # request an agent makes when it did not understand the turn.
        if not fold(query):
            return self._run(
                "not_found", REASON_NO_MATCH, (), budget, 0, query, moment,
            )

        pool = self.access.search(tenant_id, principal_id, "", limit=ceiling + 1)
        if not pool:
            # Silently bounded, per U7: an operator with no visible branch is
            # told nothing matched, never how many rows they may not see.
            return self._run(
                "not_found", REASON_NO_VISIBLE_BRANCH, (), budget, 0, query,
                moment,
            )
        if len(pool) > ceiling:
            return self._run(
                "exhausted", REASON_BUDGET_EXHAUSTED, (), budget, len(pool),
                query, moment,
            )

        matches = self._rank(query, pool)
        if not matches:
            return self._run(
                "not_found", REASON_NO_MATCH, (), budget, len(pool), query,
                moment,
            )
        candidates = tuple(
            self._candidate(tenant_id, contact, matched_by, channel, purpose,
                            moment)
            for contact, matched_by in matches
        )
        if len(candidates) == 1:
            return self._run(
                "matched", None, candidates, budget, len(pool), query, moment,
            )
        outcome, reason, candidates = self._disambiguate(
            candidates, confirmations, moment,
        )
        return self._run(
            outcome, reason, candidates, budget, len(pool), query, moment,
        )

    def _rank(self, query, pool):
        """Best tier only. A weaker match never joins a stronger one.

        Tiering rather than scoring, because the decision this feeds is
        binary: exactly one candidate materializes, anything else asks. A
        blended score makes "one strong and one weak match" look like a close
        call, when it is not one.
        """
        wanted = fold(query)
        wanted_tokens = _tokens(query)
        exact, tokens, near = [], [], []
        for contact in pool:
            name = fold(contact.get("display_name"))
            name_tokens = _tokens(contact.get("display_name"))
            if name == wanted:
                exact.append(contact)
            elif wanted_tokens and all(
                any(token == part for part in name_tokens)
                for token in wanted_tokens
            ):
                tokens.append(contact)
            elif wanted_tokens and all(
                any(_within_one_edit(token, part) for part in name_tokens)
                for token in wanted_tokens
            ):
                near.append(contact)
        for group, matched_by in (
            (exact, MATCHED_BY_EXACT_NAME),
            (tokens, MATCHED_BY_NAME_TOKENS),
            (near, MATCHED_BY_NEAR_NAME),
        ):
            if group:
                return tuple(
                    (contact, matched_by)
                    for contact in sorted(
                        group, key=lambda item: item["contact_id"],
                    )
                )
        return ()

    def _disambiguate(self, candidates, confirmations, moment):
        """R13's narrow permission, and the four ways it does not apply."""
        by_id = {item["contact_id"]: item for item in candidates}
        recent = {}
        stale = False
        conflict = False
        for confirmation in confirmations or ():
            contact_id = (confirmation or {}).get("contact_id")
            confirmed_at = (confirmation or {}).get("confirmed_at")
            if not contact_id or confirmed_at is None:
                continue
            if contact_id not in by_id:
                # Confirmed somebody who is not in this candidate set at all.
                # Not evidence about this question; recorded so the reason can
                # say so rather than reading as "we simply found several".
                conflict = True
                continue
            if moment - confirmed_at > CONFIRMATION_WINDOW:
                stale = True
                continue
            existing = recent.get(contact_id)
            if existing is None or confirmed_at > existing:
                recent[contact_id] = confirmed_at
        if len(recent) > 1:
            return "ambiguous", REASON_CONFIRMATION_TIE, candidates
        if len(recent) == 1:
            contact_id = next(iter(recent))
            chosen = by_id[contact_id]
            if not chosen["effect_ready"]:
                # The narrow half of R13. A recently confirmed contact whose
                # consent has since lapsed is precisely the case where the
                # confirmation is most persuasive and least safe.
                return (
                    "ambiguous",
                    REASON_CONFIRMATION_NOT_POLICY_COMPATIBLE,
                    candidates,
                )
            chosen = dict(chosen, matched_by=MATCHED_BY_RECENT_CONFIRMATION)
            return "matched", None, (chosen,)
        if stale:
            return "ambiguous", REASON_CONFIRMATION_STALE, candidates
        if conflict:
            return "ambiguous", REASON_CONFIRMATION_CONFLICT, candidates
        return "ambiguous", REASON_MULTIPLE_MATCHES, candidates

    def _candidate(self, tenant_id, contact, matched_by, channel, purpose,
                   moment):
        addresses = self.contacts.addresses(tenant_id, contact["contact_id"])
        branch = self.contacts.get_branch(
            tenant_id, contact["primary_branch_id"],
        ) or {}
        destinations, consent, effect_ready = [], {}, False
        for address in addresses:
            if channel is not None and address["channel"] != channel:
                continue
            reading = self._axes(tenant_id, address, channel, purpose, moment)
            if reading.get("usability") != "active":
                # A proposed or retired address is absent from the result, not
                # present and flagged. A destination a surface can render is a
                # destination somebody will try to use, and this one is not
                # usable until a human has decided it is.
                continue
            destinations.append(mask_destination(
                address["channel"], address["address"],
                address_id=address["address_id"], tenant_id=tenant_id,
                branch_path=branch.get("path"),
                last_contacted_at=address.get("last_contacted_at"),
            ).as_dict())
            consent[address["address_id"]] = reading
            if reading.get("eligible"):
                effect_ready = True
        return {
            "contact_id": contact["contact_id"],
            "record_version": record_version(contact, addresses),
            "display_name": contact.get("display_name"),
            "branch_path": branch.get("path"),
            "destinations": destinations,
            "consent": consent,
            "effect_ready": effect_ready,
            "matched_by": matched_by,
        }

    def _axes(self, tenant_id, address, channel, purpose, moment):
        if self.consent is None:
            # No consent repository wired: usability is unknown, and unknown
            # usability is unusable (U6's fail-closed default read the same way
            # here as it is read there).
            return {"usability": "proposed", "eligible": False, "reason": None}
        state = self.consent.usability_state(tenant_id, address["address_id"])
        reading = {
            "usability": state.get("state"),
            "eligible": False,
            "reason": None,
        }
        if reading["usability"] != "active":
            reading["reason"] = "address_not_usable"
            return reading
        if channel is None or purpose is None:
            # Nothing was asked about a channel or a purpose, so nothing can
            # be said about eligibility for one. Usable is not eligible.
            return reading
        decision = self.consent.evaluate_eligibility(
            tenant_id, address["address_id"], channel, purpose, now=moment,
        )
        reading["eligible"] = bool(decision.eligible)
        reading["reason"] = None if decision.eligible else decision.reason
        return reading

    def _run(self, outcome, reason, candidates, budget, seen, query, moment):
        if outcome not in RESOLVER_OUTCOMES:
            raise ValueError("unsupported resolver outcome")
        return {
            "outcome": outcome,
            "reason": reason,
            "candidates": tuple(candidates),
            "matched_by": (
                candidates[0]["matched_by"]
                if outcome == "matched" and candidates else None
            ),
            "budget": dict(budget),
            "candidates_seen": int(seen),
            "query_hash": hashlib.sha256(
                fold(query).encode("utf-8")
            ).hexdigest(),
            "resolved_at": moment,
            "status": "failed" if outcome == "failed" else "completed",
        }

    # -- binding -----------------------------------------------------------

    def materialize(self, run, selected_contact_id=None):
        """Turn a terminal run into a binding, or refuse to.

        An ambiguous run is not an error to be logged and stepped over: it is
        a question. It becomes a binding only when a human answers it by
        naming an identifier that was already in the candidate set -- which is
        why the selection is checked against that set rather than trusted. A
        selection nobody offered is indistinguishable from one somebody
        invented.
        """
        outcome = (run or {}).get("outcome")
        candidates = tuple((run or {}).get("candidates") or ())
        if outcome not in RESOLVER_OUTCOMES:
            raise ValueError("unsupported resolver outcome")
        if outcome in ("not_found", "exhausted", "failed"):
            raise ResolutionBlocked(outcome, run.get("reason"), candidates)
        if outcome == "ambiguous" and selected_contact_id is None:
            raise ResolutionBlocked(outcome, run.get("reason"), candidates)
        chosen = None
        if selected_contact_id is None:
            chosen = candidates[0]
        else:
            for candidate in candidates:
                if candidate["contact_id"] == selected_contact_id:
                    chosen = candidate
                    break
        if chosen is None:
            raise ResolutionBlocked(
                "ambiguous", "selection_not_in_candidate_set", candidates,
            )
        return {
            "contact_id": chosen["contact_id"],
            # The pair a later approval is checked against. The identifier
            # says who, the version says which version of who -- and KTD21 is
            # the reason the identifier travels rather than the label the
            # button happened to render.
            "record_version": chosen["record_version"],
            "matched_by": chosen["matched_by"],
            "branch_path": chosen["branch_path"],
            "destinations": tuple(chosen["destinations"]),
            "effect_ready": chosen["effect_ready"],
        }

    @staticmethod
    def binding_is_current(binding, candidate):
        """Whether the record behind an approval is still the one bound.

        Compared on identity *and* version. Identity alone would let an edit
        slip under a pending approval; version alone would let a different
        person carrying the same content hash satisfy it.
        """
        if not binding or not candidate:
            return False
        return (
            binding.get("contact_id") == candidate.get("contact_id")
            and binding.get("record_version") == candidate.get("record_version")
        )
