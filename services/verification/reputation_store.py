"""Storage for the AgentTrust Verification & Reputation Service.

In-memory by default, with optional JSON-file persistence:

* ``path`` — Verification Results and Reputation Records are loaded from and
  saved to this file after every mutation.
* ``revocation_path`` — the Principal key revocation list (a JSON array of
  strings; each entry is either a ``principal_id`` or a base64 ``public_key``)
  is loaded from this file and saved back when mutated at runtime.

Reputation Records are indexed by the pair ``(principal_id, capability_id)``
per RFC-0001 §3.6 and obey the neutral-reputation rule: ``verification_rate``
is ``null`` when both counts are 0, and the derived ratio otherwise.

Thread-safe (a single lock guards all mutation) so it can back the
``ThreadingHTTPServer`` in ``app.py``.
"""

import datetime
import json
import os
import threading

from typing import Dict, List, Optional, Set, Tuple


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

    def __init__(self, path=None, revocation_path=None):
        # type: (Optional[str], Optional[str]) -> None
        self._lock = threading.RLock()
        self._path = path
        self._revocation_path = revocation_path

        # evidence_id -> Verification Result
        self._results = {}  # type: Dict[str, dict]
        # (principal_id, capability_id) -> Reputation Record
        self._reputation = {}  # type: Dict[Tuple[str, str], dict]
        # (subject principal_id, capability_id) -> list of verified portfolio
        # entries, in insertion order. Only 'verified' work is ever appended.
        self._portfolio = {}  # type: Dict[Tuple[str, str], List[dict]]
        # Monotonic sequence for portfolio ordering. verified_at is only
        # second-resolution, so it can tie; the sequence breaks ties so
        # "newest first" is honored even within the same second.
        self._portfolio_seq = 0
        # Revoked principal_ids and/or public_keys, in one set.
        self._revoked = set()  # type: Set[str]

        if path is not None and os.path.exists(path):
            self._load_data(path)
        if revocation_path is not None and os.path.exists(revocation_path):
            self._load_revocations(revocation_path)

    # -- persistence --------------------------------------------------------

    def _load_data(self, path):
        # type: (str) -> None
        with open(path) as f:
            data = json.load(f)
        self._results = dict(data.get("verification_results", {}))
        self._reputation = {
            (rec["principal_id"], rec["capability_id"]): rec
            for rec in data.get("reputation_records", [])
        }
        self._portfolio = {
            (slot["principal_id"], slot["capability_id"]): list(slot["entries"])
            for slot in data.get("portfolios", [])
        }
        seqs = [
            e["_seq"]
            for entries in self._portfolio.values()
            for e in entries
            if isinstance(e.get("_seq"), int)
        ]
        self._portfolio_seq = max(seqs) if seqs else 0

    def _load_revocations(self, path):
        # type: (str) -> None
        with open(path) as f:
            entries = json.load(f)
        if not isinstance(entries, list):
            raise ValueError(
                "revocation file must contain a JSON array of strings"
            )
        self._revoked = set(str(e) for e in entries)

    def _save_data(self):
        # type: () -> None
        if self._path is None:
            return
        payload = {
            "verification_results": self._results,
            "reputation_records": sorted(
                self._reputation.values(),
                key=lambda r: (r["principal_id"], r["capability_id"]),
            ),
            "portfolios": [
                {
                    "principal_id": pid,
                    "capability_id": cid,
                    "entries": entries,
                }
                for (pid, cid), entries in sorted(self._portfolio.items())
            ],
        }
        with open(self._path, "w") as f:
            json.dump(payload, f, indent=2, sort_keys=True)

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
        with self._lock:
            self._portfolio_seq += 1
            entry = {
                "evidence_id": result["evidence_id"],
                "capability_id": capability_id,
                "verdict": "verified",
                "verified_at": result.get("verified_at"),
                "_seq": self._portfolio_seq,
            }
            self._portfolio.setdefault((principal_id, capability_id), []).append(
                entry
            )
            self._save_data()

    def get_portfolio(self, principal_id, capability_id=None, limit=None):
        # type: (str, Optional[str], Optional[int]) -> List[dict]
        """Verified portfolio entries for a subject principal, newest first.

        Empty (never an error) for a principal with no verified history.
        """
        with self._lock:
            items = []  # type: List[dict]
            for (pid, cid), entries in self._portfolio.items():
                if pid == principal_id and (
                    capability_id is None or cid == capability_id
                ):
                    items.extend(entries)
        # Newest first: by timestamp, then insertion sequence to break
        # same-second ties (the sequence is monotonic with append order).
        items.sort(
            key=lambda e: (e.get("verified_at") or "", e.get("_seq", 0)),
            reverse=True,
        )
        if limit is not None:
            items = items[:limit]
        # _seq is an internal ordering aid; never leak it to API consumers.
        return [{k: v for k, v in e.items() if k != "_seq"} for e in items]

    # -- reputation records ---------------------------------------------------

    def get_reputation(self, principal_id, capability_id=None):
        # type: (str, Optional[str]) -> List[dict]
        """All Reputation Records for a principal, optionally one capability."""
        with self._lock:
            return [
                rec
                for (pid, cid), rec in sorted(self._reputation.items())
                if pid == principal_id
                and (capability_id is None or cid == capability_id)
            ]

    def record_verdict(self, principal_id, capability_id, verdict):
        # type: (str, str, str) -> dict
        """Fold one verdict into the (principal, capability) record.

        Returns the updated Reputation Record (a fresh copy each call so
        previously returned records are not mutated in place).
        """
        if verdict not in ("verified", "rejected"):
            raise ValueError("verdict must be 'verified' or 'rejected'")
        with self._lock:
            key = (principal_id, capability_id)
            previous = self._reputation.get(key)
            verified = previous["tasks_verified"] if previous else 0
            rejected = previous["tasks_rejected"] if previous else 0
            if verdict == "verified":
                verified += 1
            else:
                rejected += 1
            total = verified + rejected
            record = {
                "principal_id": principal_id,
                "capability_id": capability_id,
                "tasks_verified": verified,
                "tasks_rejected": rejected,
                # Neutral-reputation rule: null when no data, never 0.0.
                "verification_rate": (verified / total) if total else None,
                "updated_at": _utcnow_rfc3339(),
            }
            self._reputation[key] = record
            self._save_data()
            return record

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
