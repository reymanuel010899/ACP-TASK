"""Durable immutable proposals, one-use approvals, and execution state."""

import hashlib
import json
import sqlite3
import threading
import uuid
import secrets


def canonical_payload(payload):
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def canonical_payload_hash(payload):
    return hashlib.sha256(canonical_payload(payload).encode("utf-8")).hexdigest()


class ActionRepository(object):
    def __init__(self, database_path):
        self._connection = sqlite3.connect(
            database_path, check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS action_proposals (
                proposal_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                user_principal_id TEXT NOT NULL,
                agent_principal_id TEXT NOT NULL,
                credential_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                approved_at INTEGER,
                rejected_at INTEGER,
                execution_started_at INTEGER,
                dispatched_at INTEGER,
                execution_finished_at INTEGER,
                receipt_json TEXT,
                broker_response_json TEXT,
                failure_reason TEXT,
                PRIMARY KEY (proposal_id, version)
            );
            CREATE TABLE IF NOT EXISTS capability_leases (
                lease_hash TEXT PRIMARY KEY,
                user_principal_id TEXT NOT NULL,
                agent_principal_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                credential_id TEXT NOT NULL,
                capabilities_json TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                revoked_at INTEGER,
                consumed_at INTEGER
            );
            """
        )
        self._ensure_proposal_column("dispatched_at", "INTEGER")
        self._ensure_proposal_column("broker_response_json", "TEXT")
        self._ensure_lease_column("consumed_at", "INTEGER")
        for name, declaration in (
            ("workflow_revision_id", "TEXT NOT NULL DEFAULT 'legacy'"),
            ("step_id", "TEXT NOT NULL DEFAULT 'legacy'"),
            ("plan_graph_hash", "TEXT NOT NULL DEFAULT 'legacy'"),
            ("connection_id", "TEXT NOT NULL DEFAULT 'legacy'"),
            ("attempt", "INTEGER NOT NULL DEFAULT 0"),
        ):
            self._ensure_proposal_column(name, declaration)
            self._ensure_lease_column(name, declaration)
        self._connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS capability_one_active_workflow_lease "
            "ON capability_leases(workflow_revision_id, step_id) "
            "WHERE workflow_revision_id != 'legacy' "
            "AND consumed_at IS NULL AND revoked_at IS NULL"
        )

    def create_proposal(
        self,
        user_principal_id,
        agent_principal_id,
        credential_id,
        capability_id,
        payload,
        expires_at,
        proposal_id=None,
        idempotency_key=None,
        workflow_revision_id="legacy",
        step_id="legacy",
        plan_graph_hash="legacy",
        connection_id="legacy",
        attempt=0,
    ):
        proposal_id = proposal_id or "proposal-%s" % uuid.uuid4().hex
        idempotency_key = idempotency_key or "action-%s" % uuid.uuid4().hex
        serialized = canonical_payload(payload)
        payload_hash = canonical_payload_hash(payload)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    "SELECT COALESCE(MAX(version), 0) AS version "
                    "FROM action_proposals WHERE proposal_id = ?",
                    (proposal_id,),
                ).fetchone()
                version = row["version"] + 1
                self._connection.execute(
                    "UPDATE action_proposals SET status = 'superseded' "
                    "WHERE proposal_id = ? AND status IN ('proposed', 'approved')",
                    (proposal_id,),
                )
                self._connection.execute(
                    """
                    INSERT INTO action_proposals(
                        proposal_id, version, user_principal_id,
                        agent_principal_id, credential_id, capability_id,
                        payload_json, payload_hash, idempotency_key, status,
                        expires_at, workflow_revision_id, step_id,
                        plan_graph_hash, connection_id, attempt
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proposal_id,
                        version,
                        user_principal_id,
                        agent_principal_id,
                        credential_id,
                        capability_id,
                        serialized,
                        payload_hash,
                        idempotency_key,
                        int(expires_at),
                        workflow_revision_id,
                        step_id,
                        plan_graph_hash,
                        connection_id,
                        int(attempt),
                    ),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return self.get(proposal_id, version)

    def get(self, proposal_id, version=None):
        sql = "SELECT * FROM action_proposals WHERE proposal_id = ?"
        params = [proposal_id]
        if version is None:
            sql += " ORDER BY version DESC LIMIT 1"
        else:
            sql += " AND version = ?"
            params.append(int(version))
        with self._lock:
            row = self._connection.execute(sql, params).fetchone()
        return _normalize(row)

    def get_by_idempotency_key(self, idempotency_key):
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM action_proposals WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return _normalize(row)

    def decide(self, proposal_id, version, user_principal_id, approved, now_ts):
        status = "approved" if approved else "rejected"
        timestamp_field = "approved_at" if approved else "rejected_at"
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE action_proposals
                SET status = ?, %s = ?
                WHERE proposal_id = ? AND version = ?
                  AND user_principal_id = ?
                  AND status = 'proposed' AND expires_at >= ?
                """ % timestamp_field,
                (
                    status,
                    int(now_ts),
                    proposal_id,
                    int(version),
                    user_principal_id,
                    int(now_ts),
                ),
            )
        return cursor.rowcount == 1

    def consume_approval(self, binding, now_ts):
        """Atomically bind and consume exactly one approved proposal."""
        required = (
            "proposal_id",
            "version",
            "user_principal_id",
            "agent_principal_id",
            "credential_id",
            "capability_id",
            "payload_hash",
            "idempotency_key",
        )
        if any(not binding.get(field) for field in required):
            return None
        dynamic = binding.get("workflow_revision_id") not in (None, "legacy")
        workflow_revision_id = binding["workflow_revision_id"] if dynamic else "legacy"
        step_id = binding.get("step_id") if dynamic else "legacy"
        plan_graph_hash = binding.get("plan_graph_hash") if dynamic else "legacy"
        connection_id = binding.get("connection_id") if dynamic else "legacy"
        attempt = int(binding.get("attempt", 0)) if dynamic else 0
        now = int(now_ts)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                cursor = self._connection.execute(
                    """
                    UPDATE action_proposals
                    SET status = 'executing', execution_started_at = ?
                    WHERE proposal_id = ? AND version = ?
                      AND user_principal_id = ?
                      AND agent_principal_id = ?
                      AND credential_id = ?
                      AND capability_id = ?
                      AND payload_hash = ?
                      AND idempotency_key = ?
                      AND workflow_revision_id = ? AND step_id = ?
                      AND plan_graph_hash = ? AND connection_id = ?
                      AND attempt = ?
                      AND status = 'approved' AND expires_at >= ?
                    RETURNING *
                    """,
                    (
                        now,
                        binding["proposal_id"],
                        int(binding["version"]),
                        binding["user_principal_id"],
                        binding["agent_principal_id"],
                        binding["credential_id"],
                        binding["capability_id"],
                        binding["payload_hash"],
                        binding["idempotency_key"],
                        workflow_revision_id,
                        step_id,
                        plan_graph_hash,
                        connection_id,
                        attempt,
                        now,
                    ),
                )
                row = cursor.fetchone()
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return _normalize(row)

    def issue_lease(
        self,
        user_principal_id,
        agent_principal_id,
        task_id,
        credential_id,
        capabilities,
        expires_at,
        workflow_revision_id="legacy",
        step_id="legacy",
        plan_graph_hash="legacy",
        connection_id="legacy",
        attempt=0,
    ):
        lease = secrets.token_urlsafe(32)
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO capability_leases(
                    lease_hash, user_principal_id, agent_principal_id, task_id,
                    credential_id, capabilities_json, expires_at, revoked_at,
                    consumed_at, workflow_revision_id, step_id, plan_graph_hash,
                    connection_id, attempt
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    hashlib.sha256(lease.encode("utf-8")).hexdigest(),
                    user_principal_id,
                    agent_principal_id,
                    task_id,
                    credential_id,
                    canonical_payload(sorted(set(capabilities))),
                    int(expires_at),
                    workflow_revision_id,
                    step_id,
                    plan_graph_hash,
                    connection_id,
                    int(attempt),
                ),
            )
        return lease

    def validate_lease(self, lease, binding, now_ts):
        if not lease:
            return False
        with self._lock:
            row = self._connection.execute(
                """
                SELECT * FROM capability_leases
                WHERE lease_hash = ? AND user_principal_id = ?
                  AND agent_principal_id = ? AND task_id = ?
                  AND credential_id = ? AND revoked_at IS NULL
                  AND expires_at >= ?
                """,
                (
                    hashlib.sha256(lease.encode("utf-8")).hexdigest(),
                    binding.get("user_principal_id"),
                    binding.get("agent_principal_id"),
                    binding.get("task_id"),
                    binding.get("credential_id"),
                    int(now_ts),
                ),
            ).fetchone()
        if row is None:
            return False
        return (
            binding.get("capability_id") in json.loads(row["capabilities_json"])
            and self._workflow_lease_binding_matches(row, binding)
        )

    def consume_lease(self, lease, binding, now_ts):
        """Atomically consume a lease after its complete binding is checked."""
        if not lease:
            return False
        lease_hash = hashlib.sha256(lease.encode("utf-8")).hexdigest()
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    """
                    SELECT * FROM capability_leases
                    WHERE lease_hash = ? AND user_principal_id = ?
                      AND agent_principal_id = ? AND task_id = ?
                      AND credential_id = ? AND revoked_at IS NULL
                      AND consumed_at IS NULL AND expires_at >= ?
                    """,
                    (
                        lease_hash,
                        binding.get("user_principal_id"),
                        binding.get("agent_principal_id"),
                        binding.get("task_id"),
                        binding.get("credential_id"),
                        int(now_ts),
                    ),
                ).fetchone()
                allowed = bool(
                    row
                    and binding.get("capability_id")
                    in json.loads(row["capabilities_json"])
                    and self._workflow_lease_binding_matches(row, binding)
                )
                if allowed:
                    cursor = self._connection.execute(
                        """
                        UPDATE capability_leases SET consumed_at = ?
                        WHERE lease_hash = ? AND consumed_at IS NULL
                        """,
                        (int(now_ts), lease_hash),
                    )
                    allowed = cursor.rowcount == 1
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return allowed

    @staticmethod
    def _workflow_lease_binding_matches(row, binding):
        if row["workflow_revision_id"] == "legacy":
            return True
        fields = (
            "workflow_revision_id", "step_id", "plan_graph_hash",
            "connection_id", "attempt",
        )
        return all(
            row[field] == binding.get(field, 0 if field == "attempt" else "legacy")
            for field in fields
        )

    def complete_execution(
        self, proposal_id, version, receipt, now_ts, broker_response=None
    ):
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE action_proposals
                SET status = 'completed', execution_finished_at = ?,
                    receipt_json = ?, broker_response_json = ?
                WHERE proposal_id = ? AND version = ?
                  AND status IN ('executing', 'execution_unknown')
                """,
                (
                    int(now_ts),
                    canonical_payload(receipt),
                    (
                        canonical_payload(broker_response)
                        if broker_response is not None
                        else None
                    ),
                    proposal_id,
                    int(version),
                ),
            )
        return cursor.rowcount == 1

    def mark_dispatched(self, proposal_id, version, now_ts):
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE action_proposals SET dispatched_at = ?
                WHERE proposal_id = ? AND version = ? AND status = 'executing'
                  AND dispatched_at IS NULL
                """,
                (int(now_ts), proposal_id, int(version)),
            )
        return cursor.rowcount == 1

    def recover_pre_dispatch_claim(self, proposal_id, version):
        """Only a claim that never reached dispatch is safe to retry."""
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE action_proposals
                SET status = 'approved', execution_started_at = NULL
                WHERE proposal_id = ? AND version = ? AND status = 'executing'
                  AND dispatched_at IS NULL
                """,
                (proposal_id, int(version)),
            )
        return cursor.rowcount == 1

    def fail_execution(self, proposal_id, version, reason, now_ts,
                       unknown=False):
        status = "execution_unknown" if unknown else "failed"
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE action_proposals
                SET status = ?, execution_finished_at = ?, failure_reason = ?
                WHERE proposal_id = ? AND version = ? AND status = 'executing'
                """,
                (
                    status,
                    int(now_ts),
                    str(reason)[:500],
                    proposal_id,
                    int(version),
                ),
            )
        return cursor.rowcount == 1

    def close(self):
        with self._lock:
            self._connection.close()

    def _ensure_proposal_column(self, name, declaration):
        columns = {
            row["name"]
            for row in self._connection.execute(
                "PRAGMA table_info(action_proposals)"
            ).fetchall()
        }
        if name not in columns:
            self._connection.execute(
                "ALTER TABLE action_proposals ADD COLUMN %s %s"
                % (name, declaration)
            )

    def _ensure_lease_column(self, name, declaration):
        columns = {
            row["name"]
            for row in self._connection.execute(
                "PRAGMA table_info(capability_leases)"
            ).fetchall()
        }
        if name not in columns:
            self._connection.execute(
                "ALTER TABLE capability_leases ADD COLUMN %s %s"
                % (name, declaration)
            )


def _normalize(row):
    if row is None:
        return None
    result = dict(row)
    result["payload"] = json.loads(result.pop("payload_json"))
    if result.get("receipt_json"):
        result["receipt"] = json.loads(result["receipt_json"])
    if result.get("broker_response_json"):
        result["broker_response"] = json.loads(
            result["broker_response_json"]
        )
    return result
