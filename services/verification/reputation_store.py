"""Storage for the AgentTrust Verification & Reputation Service.

Unit U5 (database architecture): reputation records and the verified-work
portfolio -- the ``_reputation``/``_portfolio`` dicts this class used to
keep in-memory -- now go through
``libs.reputation_repository.ReputationRepository`` against the SAME
Postgres ``trust.reputation_records``/``trust.reputation_portfolio`` tables
Registry's ``registry/user_index.py`` writes through. This is R2's
consolidation: a verdict recorded here is visible to a Registry search on
its very next read, with no manual sync step and no shared Python object
required (see ``libs/reputation_repository.py``'s docstring, and
``tests/registry/test_reputation_unification.py`` for a cross-service,
two-independent-connections proof).

``_results`` (Verification Results by ``evidence_id``) and ``_revoked``
(the Principal key/id revocation list) are UNCHANGED by this unit -- they
stay exactly as they were, in-memory with optional JSON-file persistence
(``path``/``revocation_path``). The plan's scope for this unit calls out
only the reputation/portfolio dicts; wiring the full Evidence/
VerificationResult submission trail into ``trust.evidence``/
``trust.verification_results`` is a larger change deferred past this unit
(see ``libs/reputation_repository.py``'s module docstring for the detailed
reasoning) -- those two tables are created by this unit's migration for
schema completeness (``trust.reputation_portfolio.evidence_id`` has a real,
enforced foreign key into ``trust.evidence``, satisfied here via a minimal
placeholder row -- see ``ReputationRepository.add_portfolio_entry``) but are
not yet the backing store for ``put_result``/``get_result``.

Unit U10 checked ``path``/``revocation_path`` against KTD9's cutover list
and kept them: unlike ``registry/index_store.py``'s and
``registry/user_index.py``'s ``path`` (dead no-ops once Postgres backed
those stores in this same unit), ``_results``/``_revoked`` never got a
Postgres table in this plan (the deferral above), so these two arguments
remain the ONLY durability ``put_result``/``revoke`` have -- removing them
would delete real persistence, not dead code (see
``tests/services/test_verification_service.py::TestStorePersistence`` for
the round-trip these arguments back).

Reputation Records are indexed by the pair ``(principal_id, capability_id)``
per RFC-0001 §3.6 and obey the neutral-reputation rule: ``verification_rate``
is ``null`` when both counts are 0, and the derived ratio otherwise.

Thread-safe for the parts still in-memory (a single lock guards ``_results``/
``_revoked`` mutation); reputation/portfolio concurrency safety now comes
from Postgres itself (see ``ReputationRepository.record_verdict``'s
docstring), not this class's lock.
"""

import datetime
import json
import os
import threading

from typing import Dict, List, Optional, Set

from libs.reputation_repository import ReputationRepository


def _utcnow_rfc3339():
    # type: () -> str
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class ReputationStore(object):
    """Store for Verification Results, Reputation Records, and revocations."""

    def __init__(self, path=None, revocation_path=None, db=None):
        # type: (Optional[str], Optional[str], Optional[object]) -> None
        self._lock = threading.RLock()
        self._path = path
        self._revocation_path = revocation_path
        self._repository = ReputationRepository(db=db)

        # evidence_id -> Verification Result (unchanged by U5, see docstring)
        self._results = {}  # type: Dict[str, dict]
        # Revoked principal_ids and/or public_keys, in one set (unchanged by
        # U5, see docstring).
        self._revoked = set()  # type: Set[str]

        if path is not None and os.path.exists(path):
            self._load_data(path)
        if revocation_path is not None and os.path.exists(revocation_path):
            self._load_revocations(revocation_path)

    # -- persistence (verification results only -- see docstring) ------------

    def _load_data(self, path):
        # type: (str) -> None
        with open(path) as f:
            data = json.load(f)
        self._results = dict(data.get("verification_results", {}))

    def _save_data(self):
        # type: () -> None
        if self._path is None:
            return
        payload = {"verification_results": self._results}
        with open(self._path, "w") as f:
            json.dump(payload, f, indent=2, sort_keys=True)

    def _load_revocations(self, path):
        # type: (str) -> None
        with open(path) as f:
            entries = json.load(f)
        if not isinstance(entries, list):
            raise ValueError(
                "revocation file must contain a JSON array of strings"
            )
        self._revoked = set(str(e) for e in entries)

    def _save_revocations(self):
        # type: () -> None
        if self._revocation_path is None:
            return
        with open(self._revocation_path, "w") as f:
            json.dump(sorted(self._revoked), f, indent=2)

    # -- verification results ------------------------------------------------

    def put_result(self, result):
        # type: (dict) -> None
        with self._lock:
            self._results[result["evidence_id"]] = result
            self._save_data()

    def get_result(self, evidence_id):
        # type: (str) -> Optional[dict]
        with self._lock:
            return self._results.get(evidence_id)

    # -- portfolio (verified-work history per subject principal) --------------

    def add_portfolio_entry(self, principal_id, capability_id, result):
        # type: (str, str, dict) -> None
        """Append one VERIFIED result to a subject principal's portfolio.

        Only 'verified' work forms a portfolio (rejected work never appears).
        The entry is a compact, re-checkable pointer, not the full result.
        """
        if result.get("verdict") != "verified":
            return
        self._repository.add_portfolio_entry(
            principal_id, capability_id, result["evidence_id"],
            verified_at=result.get("verified_at"),
        )

    def get_portfolio(self, principal_id, capability_id=None, limit=None):
        # type: (str, Optional[str], Optional[int]) -> List[dict]
        """Verified portfolio entries for a subject principal, newest first.

        Empty (never an error) for a principal with no verified history.
        """
        return self._repository.get_portfolio(
            principal_id, capability_id=capability_id, limit=limit
        )

    # -- reputation records ---------------------------------------------------

    def get_reputation(self, principal_id, capability_id=None):
        # type: (str, Optional[str]) -> List[dict]
        """All Reputation Records for a principal, optionally one capability."""
        return self._repository.get_reputation(
            principal_id, capability_id=capability_id
        )

    def record_verdict(self, principal_id, capability_id, verdict):
        # type: (str, str, str) -> dict
        """Fold one verdict into the (principal, capability) record.

        Returns the updated Reputation Record. The ONE write path for
        reputation (R2) -- shared with Registry via
        ``libs.reputation_repository.ReputationRepository`` against the
        same Postgres table.
        """
        return self._repository.record_verdict(principal_id, capability_id, verdict)

    # -- revocation list -------------------------------------------------------

    def revoke(self, value):
        # type: (str) -> None
        """Add a principal_id or public_key to the revocation list."""
        with self._lock:
            self._revoked.add(value)
            self._save_revocations()

    def is_revoked(self, *values):
        # type: (*str) -> bool
        """True if any given identifier (principal_id/public_key) is revoked."""
        with self._lock:
            return any(v in self._revoked for v in values if v is not None)

    def revoked(self):
        # type: () -> Set[str]
        with self._lock:
            return set(self._revoked)
