"""Durable revisioned workflow state and guarded step claims."""

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import uuid


class WorkflowRepository(object):
    DEFAULT_CONTENT_TTL_SECONDS = 30 * 24 * 60 * 60

    def __init__(self, database_path, content_crypto=None):
        self.content_crypto = content_crypto
        self._connection = sqlite3.connect(
            database_path, check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._connection.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS workflow_runs (
                workflow_run_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                user_principal_id TEXT NOT NULL,
                goal_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                current_revision_id TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workflow_revisions (
                workflow_revision_id TEXT PRIMARY KEY,
                workflow_run_id TEXT NOT NULL REFERENCES workflow_runs(workflow_run_id),
                tenant_id TEXT NOT NULL,
                revision_number INTEGER NOT NULL,
                plan_graph_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at INTEGER NOT NULL,
                UNIQUE(workflow_run_id, revision_number),
                UNIQUE(workflow_run_id, workflow_revision_id, tenant_id)
            );
            CREATE TABLE IF NOT EXISTS workflow_steps (
                workflow_revision_id TEXT NOT NULL REFERENCES workflow_revisions(workflow_revision_id),
                step_id TEXT NOT NULL,
                workflow_run_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                capability_version TEXT NOT NULL,
                connection_id TEXT,
                descriptor_snapshot_hash TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                input_json TEXT NOT NULL DEFAULT '{}',
                output_json TEXT,
                content_expires_at INTEGER,
                depends_on_json TEXT NOT NULL,
                effect TEXT NOT NULL,
                execution_status TEXT NOT NULL DEFAULT 'queued',
                verification_status TEXT NOT NULL DEFAULT 'not_required',
                attempt INTEGER NOT NULL DEFAULT 0,
                claimed_by TEXT,
                claimed_at INTEGER,
                retry_at INTEGER,
                terminal_reason TEXT,
                PRIMARY KEY(workflow_revision_id, step_id),
                FOREIGN KEY(workflow_run_id, workflow_revision_id, tenant_id)
                    REFERENCES workflow_revisions(workflow_run_id, workflow_revision_id, tenant_id)
            );
            CREATE TABLE IF NOT EXISTS workflow_approvals (
                workflow_revision_id TEXT PRIMARY KEY REFERENCES workflow_revisions(workflow_revision_id),
                workflow_run_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                plan_graph_hash TEXT NOT NULL,
                approved_by TEXT NOT NULL,
                approved_at INTEGER NOT NULL,
                expires_at INTEGER,
                FOREIGN KEY(workflow_run_id, workflow_revision_id, tenant_id)
                    REFERENCES workflow_revisions(workflow_run_id, workflow_revision_id, tenant_id)
            );
            CREATE TABLE IF NOT EXISTS workflow_leases (
                lease_hash TEXT PRIMARY KEY,
                workflow_revision_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                tenant_id TEXT NOT NULL,
                worker_id TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                consumed_at INTEGER,
                revoked_at INTEGER,
                FOREIGN KEY(workflow_revision_id, step_id)
                    REFERENCES workflow_steps(workflow_revision_id, step_id),
                UNIQUE(workflow_revision_id, step_id, attempt)
            );
            CREATE TABLE IF NOT EXISTS workflow_receipts (
                receipt_id TEXT PRIMARY KEY,
                workflow_revision_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                tenant_id TEXT NOT NULL,
                receipt_json TEXT NOT NULL,
                receipt_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(workflow_revision_id, step_id)
                    REFERENCES workflow_steps(workflow_revision_id, step_id),
                UNIQUE(workflow_revision_id, step_id, attempt)
            );
            CREATE TABLE IF NOT EXISTS workflow_attestations (
                attestation_id TEXT PRIMARY KEY,
                receipt_id TEXT NOT NULL UNIQUE REFERENCES workflow_receipts(receipt_id),
                workflow_revision_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                attestation_json TEXT NOT NULL,
                attestation_hash TEXT NOT NULL,
                verification_status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                FOREIGN KEY(workflow_revision_id, step_id)
                    REFERENCES workflow_steps(workflow_revision_id, step_id)
            );
        """)
        self._ensure_step_column("input_json", "TEXT NOT NULL DEFAULT '{}'")
        self._ensure_step_column("output_json", "TEXT")
        self._ensure_step_column("retry_at", "INTEGER")
        self._ensure_step_column("content_expires_at", "INTEGER")
        self._ensure_table_column("workflow_approvals", "expires_at", "INTEGER")

    def _ensure_step_column(self, name, declaration):
        self._ensure_table_column("workflow_steps", name, declaration)

    def _ensure_table_column(self, table, name, declaration):
        columns = {
            row["name"] for row in self._connection.execute(
                "PRAGMA table_info(%s)" % table
            ).fetchall()
        }
        if name not in columns:
            self._connection.execute(
                "ALTER TABLE %s ADD COLUMN %s %s" % (table, name, declaration)
            )

    def _step_update(self, revision_id, step_id, tenant_id, status, reason=None):
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE workflow_steps SET execution_status = ?, terminal_reason = ?, "
                "claimed_by = NULL, claimed_at = NULL, retry_at = NULL "
                "WHERE workflow_revision_id = ? "
                "AND step_id = ? AND tenant_id = ?",
                (status, reason, revision_id, step_id, tenant_id),
            )
        return cursor.rowcount == 1

    @classmethod
    def from_environment(cls, database_path, service_identity):
        key_id = os.environ.get("TESSERA_WORKFLOW_KMS_KEY_ID")
        production = os.environ.get("APP_ENV", "development").lower() == "production"
        if production and not key_id:
            raise RuntimeError("TESSERA_WORKFLOW_KMS_KEY_ID is required in production")
        crypto = None
        if key_id:
            from agents.orchestrator.workflow_content_crypto import WorkflowContentCrypto
            from libs.aws_kms import AWSKMSClient
            crypto = WorkflowContentCrypto(AWSKMSClient(), key_id, service_identity)
        return cls(database_path, content_crypto=crypto)

    @staticmethod
    def _content_context(tenant_id, revision_id, step_id, field):
        return {
            "purpose": "workflow-content", "tenant_id": tenant_id,
            "workflow_revision_id": revision_id, "step_id": step_id,
            "field": field,
        }

    def _encode_content(self, value, tenant_id, revision_id, step_id, field):
        stored = (
            self.content_crypto.seal(
                value, self._content_context(tenant_id, revision_id, step_id, field)
            ) if self.content_crypto is not None else value
        )
        return json.dumps(stored, sort_keys=True, separators=(",", ":"))

    def _decode_content(self, raw, tenant_id, revision_id, step_id, field, default):
        if raw is None:
            return default
        stored = json.loads(raw)
        if self.content_crypto is None:
            return stored
        if stored == {}:
            return default
        return self.content_crypto.open(
            stored, self._content_context(tenant_id, revision_id, step_id, field)
        )

    def create_run(self, tenant_id, user_principal_id, goal_hash, now_ts):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        run_id = "workflow:%s" % uuid.uuid4().hex
        with self._lock:
            self._connection.execute(
                """INSERT INTO workflow_runs(
                    workflow_run_id, tenant_id, user_principal_id, goal_hash,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, tenant_id, user_principal_id, goal_hash,
                 int(now_ts), int(now_ts)),
            )
        return self.get_run(run_id, tenant_id)

    def get_run(self, workflow_run_id, tenant_id):
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM workflow_runs WHERE workflow_run_id = ? AND tenant_id = ?",
                (workflow_run_id, tenant_id),
            ).fetchone()
        return dict(row) if row else None

    def get_run_for_principal(self, workflow_run_id, principal_id):
        """Owner-scoped lookup used by authenticated workflow surfaces."""
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM workflow_runs WHERE workflow_run_id = ? "
                "AND user_principal_id = ?",
                (workflow_run_id, principal_id),
            ).fetchone()
        return dict(row) if row else None

    def create_revision(
        self, workflow_run_id, tenant_id, plan_graph_hash, steps, now_ts,
        content_ttl_seconds=DEFAULT_CONTENT_TTL_SECONDS,
    ):
        revision_id = "revision:%s" % uuid.uuid4().hex
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                run = self._connection.execute(
                    "SELECT * FROM workflow_runs WHERE workflow_run_id = ? AND tenant_id = ?",
                    (workflow_run_id, tenant_id),
                ).fetchone()
                if run is None:
                    raise ValueError("workflow run not found")
                row = self._connection.execute(
                    "SELECT COALESCE(MAX(revision_number), 0) AS number "
                    "FROM workflow_revisions WHERE workflow_run_id = ?",
                    (workflow_run_id,),
                ).fetchone()
                number = row["number"] + 1
                self._connection.execute(
                    "UPDATE workflow_revisions SET status = 'superseded' "
                    "WHERE workflow_run_id = ? AND status IN ('draft', 'awaiting_approval')",
                    (workflow_run_id,),
                )
                self._connection.execute(
                    """INSERT INTO workflow_revisions(
                        workflow_revision_id, workflow_run_id, tenant_id,
                        revision_number, plan_graph_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (revision_id, workflow_run_id, tenant_id, number,
                     plan_graph_hash, int(now_ts)),
                )
                for step in steps:
                    self._connection.execute(
                        """INSERT INTO workflow_steps(
                            workflow_revision_id, step_id, workflow_run_id,
                            tenant_id, capability_id, capability_version,
                            connection_id, descriptor_snapshot_hash, input_hash,
                            input_json, depends_on_json, effect, verification_status,
                            content_expires_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            revision_id, step["step_id"], workflow_run_id,
                            tenant_id, step["capability_id"],
                            step["capability_version"], step.get("connection_id"),
                            step["descriptor_snapshot_hash"], step["input_hash"],
                            self._encode_content(
                                step.get("input", {}), tenant_id, revision_id,
                                step["step_id"], "input",
                            ),
                            json.dumps(step.get("depends_on", []), separators=(",", ":")),
                            step["effect"],
                            "pending" if step["effect"] == "write" else "not_required",
                            int(now_ts) + int(content_ttl_seconds),
                        ),
                    )
                self._connection.execute(
                    "UPDATE workflow_runs SET current_revision_id = ?, updated_at = ? "
                    "WHERE workflow_run_id = ? AND tenant_id = ?",
                    (revision_id, int(now_ts), workflow_run_id, tenant_id),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return self.get_revision(workflow_run_id, revision_id, tenant_id)

    def get_revision(self, workflow_run_id, revision_id, tenant_id):
        with self._lock:
            revision = self._connection.execute(
                """SELECT * FROM workflow_revisions
                   WHERE workflow_run_id = ? AND workflow_revision_id = ? AND tenant_id = ?""",
                (workflow_run_id, revision_id, tenant_id),
            ).fetchone()
            if revision is None:
                return None
            rows = self._connection.execute(
                "SELECT * FROM workflow_steps WHERE workflow_revision_id = ? ORDER BY rowid",
                (revision_id,),
            ).fetchall()
        result = dict(revision)
        result["steps"] = [self._step(row) for row in rows]
        return result

    def _step(self, row):
        result = dict(row)
        result["depends_on"] = json.loads(result.pop("depends_on_json"))
        result["input"] = self._decode_content(
            result.pop("input_json"), result["tenant_id"],
            result["workflow_revision_id"], result["step_id"], "input", {},
        )
        result["output"] = self._decode_content(
            result.pop("output_json"), result["tenant_id"],
            result["workflow_revision_id"], result["step_id"], "output", {},
        )
        return result

    def get_step_receipt(self, revision_id, step_id, tenant_id):
        with self._lock:
            row = self._connection.execute(
                "SELECT receipt_json FROM workflow_receipts WHERE workflow_revision_id = ? "
                "AND step_id = ? AND tenant_id = ? ORDER BY attempt DESC LIMIT 1",
                (revision_id, step_id, tenant_id),
            ).fetchone()
        return json.loads(row["receipt_json"]) if row else None

    def list_approved_revisions(self, limit=100):
        with self._lock:
            rows = self._connection.execute(
                """SELECT r.workflow_run_id, r.workflow_revision_id, r.tenant_id
                   FROM workflow_revisions r
                   WHERE r.status = 'approved' AND EXISTS (
                       SELECT 1 FROM workflow_steps s
                       WHERE s.workflow_revision_id = r.workflow_revision_id
                         AND s.execution_status = 'queued'
                   ) ORDER BY r.created_at, r.workflow_revision_id LIMIT ?""",
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_approval(
        self, workflow_run_id, revision_id, tenant_id, graph_hash,
        approved_by, now_ts, ttl_seconds=900
    ):
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                cursor = self._connection.execute(
                    """INSERT INTO workflow_approvals(
                        workflow_revision_id, workflow_run_id, tenant_id,
                        plan_graph_hash, approved_by, approved_at, expires_at
                    ) SELECT workflow_revision_id, workflow_run_id, tenant_id,
                             plan_graph_hash, ?, ?, ?
                      FROM workflow_revisions
                      WHERE workflow_revision_id = ? AND workflow_run_id = ?
                        AND tenant_id = ? AND plan_graph_hash = ? AND status = 'draft'
                    """,
                    (approved_by, int(now_ts), int(now_ts) + int(ttl_seconds),
                     revision_id, workflow_run_id,
                     tenant_id, graph_hash),
                )
                if cursor.rowcount != 1:
                    raise ValueError("revision approval binding changed")
                self._connection.execute(
                    "UPDATE workflow_revisions SET status = 'approved' "
                    "WHERE workflow_revision_id = ?", (revision_id,)
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def is_revision_approved(
        self, workflow_run_id, revision_id, tenant_id, graph_hash, now_ts=None
    ):
        with self._lock:
            row = self._connection.execute(
                """SELECT expires_at FROM workflow_approvals
                   WHERE workflow_run_id = ? AND workflow_revision_id = ?
                     AND tenant_id = ? AND plan_graph_hash = ?""",
                (workflow_run_id, revision_id, tenant_id, graph_hash),
            ).fetchone()
        return bool(
            row is not None
            and (now_ts is None or row["expires_at"] is None or row["expires_at"] >= int(now_ts))
        )

    def finish_claim_lease(self, claim, tenant_id, now_ts, consumed):
        """Close the one-use scheduler lease for exactly this claimed attempt."""
        if not claim or not claim.get("lease"):
            return False
        field = "consumed_at" if consumed else "revoked_at"
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE workflow_leases SET %s = ? WHERE lease_hash = ? "
                "AND workflow_revision_id = ? AND step_id = ? AND attempt = ? "
                "AND tenant_id = ? AND consumed_at IS NULL AND revoked_at IS NULL" % field,
                (int(now_ts), hashlib.sha256(claim["lease"].encode()).hexdigest(),
                 claim["workflow_revision_id"], claim["step_id"],
                 int(claim["attempt"]), tenant_id),
            )
        return cursor.rowcount == 1

    def claim_ready_step(
        self, workflow_run_id, revision_id, tenant_id, worker_id,
        now_ts, lease_ttl_seconds, max_attempts=5
    ):
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.execute(
                    "UPDATE workflow_steps SET execution_status = 'failed', "
                    "terminal_reason = 'maximum attempts exceeded' "
                    "WHERE workflow_run_id = ? AND workflow_revision_id = ? "
                    "AND tenant_id = ? AND execution_status = 'queued' AND attempt >= ?",
                    (workflow_run_id, revision_id, tenant_id, int(max_attempts)),
                )
                rows = self._connection.execute(
                    """SELECT * FROM workflow_steps
                       WHERE workflow_run_id = ? AND workflow_revision_id = ?
                         AND tenant_id = ? AND execution_status = 'queued'
                         AND (retry_at IS NULL OR retry_at <= ?)
                       ORDER BY rowid""",
                    (workflow_run_id, revision_id, tenant_id, int(now_ts)),
                ).fetchall()
                selected = None
                for row in rows:
                    dependencies = json.loads(row["depends_on_json"])
                    if self._dependencies_completed(revision_id, dependencies):
                        selected = row
                        break
                if selected is None:
                    self._connection.execute("COMMIT")
                    return None
                attempt = selected["attempt"] + 1
                cursor = self._connection.execute(
                    """UPDATE workflow_steps SET execution_status = 'running',
                           attempt = ?, claimed_by = ?, claimed_at = ?, retry_at = NULL
                       WHERE workflow_revision_id = ? AND step_id = ?
                         AND execution_status = 'queued'""",
                    (attempt, worker_id, int(now_ts), revision_id, selected["step_id"]),
                )
                if cursor.rowcount != 1:
                    self._connection.execute("ROLLBACK")
                    return None
                lease = secrets.token_urlsafe(32)
                self._connection.execute(
                    """INSERT INTO workflow_leases(
                        lease_hash, workflow_revision_id, step_id, attempt,
                        tenant_id, worker_id, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (hashlib.sha256(lease.encode()).hexdigest(), revision_id,
                     selected["step_id"], attempt, tenant_id, worker_id,
                     int(now_ts) + int(lease_ttl_seconds)),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return {"lease": lease, "step_id": selected["step_id"],
                "attempt": attempt, "workflow_revision_id": revision_id}

    def _dependencies_completed(self, revision_id, dependencies):
        if not dependencies:
            return True
        placeholders = ",".join("?" for _ in dependencies)
        rows = self._connection.execute(
            "SELECT step_id, execution_status FROM workflow_steps "
            "WHERE workflow_revision_id = ? AND step_id IN (%s)" % placeholders,
            [revision_id] + list(dependencies),
        ).fetchall()
        return len(rows) == len(dependencies) and all(
            row["execution_status"] == "completed" for row in rows
        )

    def persist_completion(
        self, revision_id, step_id, tenant_id, attempt, receipt,
        attestation, now_ts, output=None
    ):
        receipt_json = json.dumps(
            receipt, sort_keys=True, separators=(",", ":")
        )
        attestation_json = json.dumps(
            attestation or {}, sort_keys=True, separators=(",", ":")
        )
        receipt_id = "receipt:%s" % hashlib.sha256(
            ("%s\0%s\0%s\0%s" % (
                revision_id, step_id, int(attempt), receipt_json
            )).encode("utf-8")
        ).hexdigest()
        attestation_id = (attestation or {}).get("attestation_id")
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                current = self._connection.execute(
                    "SELECT effect FROM workflow_steps WHERE workflow_revision_id = ? "
                    "AND step_id = ? AND tenant_id = ?",
                    (revision_id, step_id, tenant_id),
                ).fetchone()
                if current is None:
                    raise ValueError("workflow step not found")
                if current["effect"] == "write" and not attestation_id:
                    raise ValueError("attestation_id is required for writes")
                verification_status = "pending" if current["effect"] == "write" else "not_required"
                cursor = self._connection.execute(
                    """UPDATE workflow_steps
                       SET execution_status = 'completed',
                           verification_status = ?, terminal_reason = NULL,
                           output_json = ?
                       WHERE workflow_revision_id = ? AND step_id = ?
                         AND tenant_id = ? AND attempt = ?
                         AND execution_status IN ('running', 'execution_unknown')""",
                    (verification_status,
                     self._encode_content(
                         output or {}, tenant_id, revision_id, step_id, "output"
                     ),
                     revision_id, step_id, tenant_id, int(attempt)),
                )
                if cursor.rowcount != 1:
                    raise ValueError("workflow step completion binding changed")
                self._connection.execute(
                    """INSERT INTO workflow_receipts(
                        receipt_id, workflow_revision_id, step_id, attempt,
                        tenant_id, receipt_json, receipt_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (receipt_id, revision_id, step_id, int(attempt), tenant_id,
                     receipt_json, hashlib.sha256(receipt_json.encode()).hexdigest(),
                     int(now_ts)),
                )
                if attestation_id:
                    self._connection.execute(
                        """INSERT INTO workflow_attestations(
                            attestation_id, receipt_id, workflow_revision_id,
                            step_id, tenant_id, attestation_json,
                            attestation_hash, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (attestation_id, receipt_id, revision_id, step_id, tenant_id,
                         attestation_json,
                         hashlib.sha256(attestation_json.encode()).hexdigest(),
                         int(now_ts)),
                    )
                remaining = self._connection.execute(
                    "SELECT 1 FROM workflow_steps WHERE workflow_revision_id = ? "
                    "AND execution_status != 'completed' LIMIT 1",
                    (revision_id,),
                ).fetchone()
                if remaining is None:
                    self._connection.execute(
                        "UPDATE workflow_revisions SET status = 'completed' "
                        "WHERE workflow_revision_id = ? AND tenant_id = ?",
                        (revision_id, tenant_id),
                    )
                    self._connection.execute(
                        "UPDATE workflow_runs SET status = 'completed', updated_at = ? "
                        "WHERE current_revision_id = ? AND tenant_id = ?",
                        (int(now_ts), revision_id, tenant_id),
                    )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return {"receipt_id": receipt_id, "attestation_id": attestation_id,
                "execution_status": "completed", "verification_status": verification_status}

    def release_for_retry(self, revision_id, step_id, tenant_id, reason, retry_at):
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE workflow_steps SET execution_status = 'queued', "
                "terminal_reason = ?, claimed_by = NULL, claimed_at = NULL, retry_at = ? "
                "WHERE workflow_revision_id = ? AND step_id = ? AND tenant_id = ?",
                (reason, int(retry_at), revision_id, step_id, tenant_id),
            )
        return cursor.rowcount == 1

    def recover_expired_claims(self, now_ts):
        """Recover abandoned reads and quarantine abandoned writes for reconciliation."""
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                rows = self._connection.execute(
                    "SELECT l.lease_hash, l.workflow_revision_id, l.step_id, l.tenant_id, "
                    "s.effect FROM workflow_leases l JOIN workflow_steps s "
                    "ON s.workflow_revision_id = l.workflow_revision_id AND s.step_id = l.step_id "
                    "WHERE l.expires_at < ? AND l.consumed_at IS NULL AND l.revoked_at IS NULL "
                    "AND s.execution_status = 'running'",
                    (int(now_ts),),
                ).fetchall()
                for row in rows:
                    status = "execution_unknown" if row["effect"] == "write" else "queued"
                    self._connection.execute(
                        "UPDATE workflow_steps SET execution_status = ?, claimed_by = NULL, "
                        "claimed_at = NULL, terminal_reason = 'worker lease expired' "
                        "WHERE workflow_revision_id = ? AND step_id = ? AND tenant_id = ? "
                        "AND execution_status = 'running'",
                        (status, row["workflow_revision_id"], row["step_id"], row["tenant_id"]),
                    )
                    self._connection.execute(
                        "UPDATE workflow_leases SET revoked_at = ? WHERE lease_hash = ?",
                        (int(now_ts), row["lease_hash"]),
                    )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return len(rows)

    def purge_expired_content(self, now_ts):
        """Destroy recoverable workflow content after its tenant-bound TTL."""
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE workflow_steps SET input_json = '{}', output_json = NULL "
                "WHERE content_expires_at IS NOT NULL AND content_expires_at < ? "
                "AND execution_status IN ('completed', 'cancelled', 'failed')",
                (int(now_ts),),
            )
        return cursor.rowcount

    def mark_execution_unknown(self, revision_id, step_id, tenant_id, reason):
        return self._step_update(
            revision_id, step_id, tenant_id, "execution_unknown", reason
        )

    def pause_by_policy(self, revision_id, step_id, tenant_id, reason):
        return self._step_update(
            revision_id, step_id, tenant_id, "paused_by_policy", reason
        )

    def resume_policy_paused(self):
        """Resume only kill-switch pauses; binding changes still require replanning."""
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE workflow_steps SET execution_status = 'queued', "
                "terminal_reason = NULL WHERE execution_status = 'paused_by_policy' "
                "AND terminal_reason IN ('dispatch policy disabled', "
                "'capability rollout is disabled')"
            )
        return cursor.rowcount

    def cancel_revision(self, workflow_run_id, revision_id, tenant_id):
        with self._lock:
            self._connection.execute(
                "UPDATE workflow_steps SET execution_status = 'cancelled' "
                "WHERE workflow_run_id = ? AND workflow_revision_id = ? AND tenant_id = ? "
                "AND execution_status IN ('queued', 'paused_by_policy')",
                (workflow_run_id, revision_id, tenant_id),
            )
            cursor = self._connection.execute(
                "UPDATE workflow_revisions SET status = 'cancelled' WHERE workflow_run_id = ? "
                "AND workflow_revision_id = ? AND tenant_id = ? AND status != 'superseded'",
                (workflow_run_id, revision_id, tenant_id),
            )
            if cursor.rowcount == 1:
                self._connection.execute(
                    "UPDATE workflow_runs SET status = 'cancelled' "
                    "WHERE workflow_run_id = ? AND current_revision_id = ? AND tenant_id = ?",
                    (workflow_run_id, revision_id, tenant_id),
                )
        return cursor.rowcount == 1

    def retry_safe_read(self, workflow_run_id, revision_id, step_id, tenant_id):
        """Let an owner advance only an already queued, backoff-delayed read."""
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE workflow_steps SET retry_at = NULL, terminal_reason = NULL "
                "WHERE workflow_run_id = ? AND workflow_revision_id = ? "
                "AND step_id = ? AND tenant_id = ? AND effect = 'read' "
                "AND execution_status = 'queued' AND retry_at IS NOT NULL",
                (workflow_run_id, revision_id, step_id, tenant_id),
            )
        return cursor.rowcount == 1

    @staticmethod
    def recovery_options(revision):
        steps = revision.get("steps", []) if isinstance(revision, dict) else []
        return {
            "cancelAllowed": any(
                step.get("execution_status") in ("queued", "paused_by_policy")
                for step in steps
            ),
            "retryableStepIds": [
                step["step_id"] for step in steps
                if step.get("effect") == "read"
                and step.get("execution_status") == "queued"
                and step.get("retry_at") is not None
            ],
            "unknownStepIds": [
                step["step_id"] for step in steps
                if step.get("execution_status") == "execution_unknown"
            ],
        }

    def apply_reconciliation(
        self, revision_id, step_id, tenant_id, attempt, result
    ):
        allowed = {"completed", "queued", "execution_unknown"}
        status = result.get("execution_status")
        if status not in allowed:
            raise ValueError("invalid reconciliation transition")
        if status == "completed":
            receipt = result.get("receipt")
            attestation = result.get("attestation")
            if not isinstance(receipt, dict) or not isinstance(attestation, dict):
                raise ValueError(
                    "reconciled completion requires a receipt and signed attestation"
                )
            return bool(self.persist_completion(
                revision_id, step_id, tenant_id, attempt, receipt,
                attestation, result.get("reconciled_at", 0),
                output=result.get("output", receipt),
            ))
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE workflow_steps SET execution_status = ?,
                       verification_status = ?, claimed_by = NULL, claimed_at = NULL
                   WHERE workflow_revision_id = ? AND step_id = ?
                     AND tenant_id = ? AND attempt = ?
                     AND execution_status = 'execution_unknown'""",
                (status, result.get("verification_status", "pending"),
                 revision_id, step_id, tenant_id, int(attempt)),
            )
        return cursor.rowcount == 1

    def set_verification_status(
        self, revision_id, step_id, tenant_id, status
    ):
        if status not in ("pending", "verified", "inconclusive", "failed"):
            raise ValueError("invalid verification status")
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE workflow_steps SET verification_status = ?
                   WHERE workflow_revision_id = ? AND step_id = ?
                     AND tenant_id = ? AND execution_status = 'completed'""",
                (status, revision_id, step_id, tenant_id),
            )
        return cursor.rowcount == 1

    def close(self):
        with self._lock:
            self._connection.close()
