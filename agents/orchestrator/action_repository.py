"""Durable immutable proposals, one-use approvals, and execution state."""

import hashlib
import json
import sqlite3
import threading
import time
import uuid
import secrets
from datetime import datetime, timezone

from libs.db import current_organization_id


def canonical_payload(payload):
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def canonical_payload_hash(payload):
    return hashlib.sha256(canonical_payload(payload).encode("utf-8")).hexdigest()


#: What a row written before the tenant column existed carries.
LEGACY_TENANT = "legacy"


def _tenant_scope(tenant_id):
    """The tenant predicate and its parameter, for one read or one claim.

    Two things have to be true at once. A proposal already in flight when
    this column shipped has no tenant, and refusing it would strand it
    mid-dispatch with no path to any verdict -- so 'legacy' stays reachable,
    exactly as `workflow_revision_id` and the authority fields do. And a
    proposal that does name an account must be reachable only from that
    account, which is the part that did not exist before: `action_proposals`
    holds the resolved destination and the message body, and a proposal id
    was the whole of the authorisation to read, approve, or consume one.

    A caller that names no tenant reaches the legacy rows and nothing else,
    rather than reaching everything.
    """
    return " AND tenant_id IN (?, ?)", (LEGACY_TENANT, tenant_id or LEGACY_TENANT)


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
            # Which account this effect belongs to. Absent until now, which
            # meant `action_proposals` -- the table that holds the resolved
            # destination and the message body -- had no tenant predicate on
            # any path: a proposal id was enough to read, approve, or consume
            # somebody else's pending send. 'legacy' is the pre-column
            # sentinel, matching how every other binding field here was
            # backfilled; rows written with a real tenant are reachable only
            # by that tenant.
            ("tenant_id", "TEXT NOT NULL DEFAULT 'legacy'"),
            ("workflow_revision_id", "TEXT NOT NULL DEFAULT 'legacy'"),
            ("step_id", "TEXT NOT NULL DEFAULT 'legacy'"),
            ("plan_graph_hash", "TEXT NOT NULL DEFAULT 'legacy'"),
            ("connection_id", "TEXT NOT NULL DEFAULT 'legacy'"),
            ("attempt", "INTEGER NOT NULL DEFAULT 0"),
            # Which identity the effect acts as. Part of the lease binding, so
            # the acting subject cannot be swapped between approval and
            # dispatch while the lease still validates.
            ("authority_profile", "TEXT NOT NULL DEFAULT 'bot'"),
            ("authority_profile_id", "TEXT NOT NULL DEFAULT 'none'"),
            ("slack_subject_id", "TEXT NOT NULL DEFAULT 'none'"),
        ):
            self._ensure_proposal_column(name, declaration)
            self._ensure_lease_column(name, declaration)
        # Effects whose approval must come from someone provably present.
        self._ensure_proposal_column(
            "reinforced", "INTEGER NOT NULL DEFAULT 0"
        )
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
        authority_profile="bot",
        authority_profile_id=None,
        slack_subject_id=None,
        reinforced=False,
        tenant_id=None,
    ):
        proposal_id = proposal_id or "proposal-%s" % uuid.uuid4().hex
        idempotency_key = idempotency_key or "action-%s" % uuid.uuid4().hex
        dynamic = workflow_revision_id not in (None, "legacy")
        if dynamic:
            attempt_suffix = ":attempt:%s" % int(attempt)
            if not idempotency_key.endswith(attempt_suffix):
                idempotency_key += attempt_suffix
        serialized = canonical_payload(payload)
        payload_hash = canonical_payload_hash(payload)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                if dynamic:
                    unresolved = self._connection.execute(
                        """SELECT version FROM action_proposals
                           WHERE proposal_id = ?
                             AND status IN ('executing', 'execution_unknown')
                           ORDER BY version DESC LIMIT 1""",
                        (proposal_id,),
                    ).fetchone()
                    if unresolved is not None:
                        raise ValueError(
                            "prior attempt is still executing or unresolved"
                        )
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
                        expires_at, tenant_id, workflow_revision_id, step_id,
                        plan_graph_hash, connection_id, attempt,
                        authority_profile, authority_profile_id,
                        slack_subject_id, reinforced
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        tenant_id or LEGACY_TENANT,
                        workflow_revision_id,
                        step_id,
                        plan_graph_hash,
                        connection_id,
                        int(attempt),
                        authority_profile or "bot",
                        authority_profile_id or "none",
                        slack_subject_id or "none",
                        1 if reinforced else 0,
                    ),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return self.get(proposal_id, version, tenant_id=tenant_id)

    def get(self, proposal_id, version=None, tenant_id=None):
        scope, scope_params = _tenant_scope(tenant_id)
        sql = "SELECT * FROM action_proposals WHERE proposal_id = ?" + scope
        params = [proposal_id]
        params.extend(scope_params)
        if version is None:
            sql += " ORDER BY version DESC LIMIT 1"
        else:
            sql += " AND version = ?"
            params.append(int(version))
        with self._lock:
            row = self._connection.execute(sql, params).fetchone()
        return _normalize(row)

    def get_by_idempotency_key(self, idempotency_key, tenant_id=None):
        scope, scope_params = _tenant_scope(tenant_id)
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM action_proposals WHERE idempotency_key = ?"
                + scope,
                (idempotency_key,) + scope_params,
            ).fetchone()
        return _normalize(row)

    def decide(self, proposal_id, version, user_principal_id, approved, now_ts,
               tenant_id=None):
        status = "approved" if approved else "rejected"
        timestamp_field = "approved_at" if approved else "rejected_at"
        scope, scope_params = _tenant_scope(tenant_id)
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE action_proposals
                SET status = ?, %s = ?
                WHERE proposal_id = ? AND version = ?
                  AND user_principal_id = ?
                  AND status = 'proposed' AND expires_at >= ?
                """ % timestamp_field + scope,
                (
                    status,
                    int(now_ts),
                    proposal_id,
                    int(version),
                    user_principal_id,
                    int(now_ts),
                ) + scope_params,
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
                    """ + _tenant_scope(binding.get("tenant_id"))[0] + """
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
                    ) + _tenant_scope(binding.get("tenant_id"))[1],
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
        now_ts=None,
        authority_profile="bot",
        authority_profile_id=None,
        slack_subject_id=None,
        tenant_id=None,
    ):
        lease = secrets.token_urlsafe(32)
        revoked_at = int(time.time() if now_ts is None else now_ts)
        with self._lock:
            if workflow_revision_id != "legacy":
                # A retry inherits the prior attempt's stranded lease. Revoking
                # it keeps one active lease per step while letting the retry
                # proceed; without this the insert below violates
                # capability_one_active_workflow_lease and the step is
                # misreported as an unknown provider outcome.
                self._connection.execute(
                    """
                    UPDATE capability_leases SET revoked_at = ?
                    WHERE workflow_revision_id = ? AND step_id = ?
                      AND consumed_at IS NULL AND revoked_at IS NULL
                    """,
                    (revoked_at, workflow_revision_id, step_id),
                )
            self._connection.execute(
                """
                INSERT INTO capability_leases(
                    lease_hash, user_principal_id, agent_principal_id, task_id,
                    credential_id, capabilities_json, expires_at, revoked_at,
                    consumed_at, workflow_revision_id, step_id, plan_graph_hash,
                    connection_id, attempt, authority_profile,
                    authority_profile_id, slack_subject_id, tenant_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    authority_profile or "bot",
                    authority_profile_id or "none",
                    slack_subject_id or "none",
                    tenant_id or LEGACY_TENANT,
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
                """ + _tenant_scope(binding.get("tenant_id"))[0],
                (
                    hashlib.sha256(lease.encode("utf-8")).hexdigest(),
                    binding.get("user_principal_id"),
                    binding.get("agent_principal_id"),
                    binding.get("task_id"),
                    binding.get("credential_id"),
                    int(now_ts),
                ) + _tenant_scope(binding.get("tenant_id"))[1],
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
                    """ + _tenant_scope(binding.get("tenant_id"))[0],
                    (
                        lease_hash,
                        binding.get("user_principal_id"),
                        binding.get("agent_principal_id"),
                        binding.get("task_id"),
                        binding.get("credential_id"),
                        int(now_ts),
                    ) + _tenant_scope(binding.get("tenant_id"))[1],
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
        if not all(
            row[field] == binding.get(field, 0 if field == "attempt" else "legacy")
            for field in fields
        ):
            return False
        # An approval names the identity that will act. Letting a dispatch
        # substitute another one afterwards would make the approval a
        # statement about nobody in particular.
        authority = (
            ("authority_profile", "bot"),
            ("authority_profile_id", "none"),
            ("slack_subject_id", "none"),
        )
        return all(
            row[field] == (binding.get(field) or default)
            for field, default in authority
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

    def resolve_unknown_as_absent(self, proposal_id, version, reason, now_ts):
        """Close an unknown proposal that reconciliation proved never landed.

        Until this happens the proposal id stays unresolved forever, and
        `create_proposal` refuses every later attempt on that step.
        """
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE action_proposals
                SET status = 'failed', execution_finished_at = ?,
                    failure_reason = ?
                WHERE proposal_id = ? AND version = ?
                  AND status = 'execution_unknown'
                """,
                (int(now_ts), str(reason)[:500], proposal_id, int(version)),
            )
        return cursor.rowcount == 1

    def sweep_stalled_executions(self, now_ts, limit=100):
        """Give every claimed proposal past its deadline a way out.

        A claim that never dispatched is safe to hand back. One that did
        dispatch has an outcome nobody observed, so it becomes explicitly
        unknown and enters reconciliation instead of sitting in `executing`
        with no path to any verdict at all.
        """
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT p.proposal_id, p.version, p.dispatched_at,
                       COALESCE(MAX(l.expires_at), p.expires_at) AS deadline
                  FROM action_proposals p
                  LEFT JOIN capability_leases l
                    ON l.workflow_revision_id = p.workflow_revision_id
                   AND l.step_id = p.step_id
                   AND l.attempt = p.attempt
                   AND p.workflow_revision_id != 'legacy'
                 WHERE p.status = 'executing'
                 GROUP BY p.proposal_id, p.version
                HAVING deadline < ?
                 LIMIT ?
                """,
                (int(now_ts), int(limit)),
            ).fetchall()
        swept = {"recovered": [], "unknown": []}
        for row in rows:
            if row["dispatched_at"] is None:
                if self.recover_pre_dispatch_claim(
                    row["proposal_id"], row["version"]
                ):
                    swept["recovered"].append(row["proposal_id"])
            elif self.fail_execution(
                row["proposal_id"], row["version"],
                "dispatch lease expired without an observed outcome",
                now_ts, unknown=True,
            ):
                swept["unknown"].append(row["proposal_id"])
        return swept

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


class PostgresActionRepository(object):
    """PostgreSQL authority for proposals, approvals, and capability leases."""

    def __init__(self, db):
        self.db = db

    def create_proposal(
        self, user_principal_id, agent_principal_id, credential_id,
        capability_id, payload, expires_at, proposal_id=None,
        idempotency_key=None, workflow_revision_id="legacy", step_id="legacy",
        plan_graph_hash="legacy", connection_id="legacy", attempt=0,
        authority_profile="bot", authority_profile_id=None,
        slack_subject_id=None, reinforced=False, tenant_id=None,
    ):
        tenant_id = self._tenant(tenant_id)
        proposal_id = proposal_id or "proposal-%s" % uuid.uuid4().hex
        idempotency_key = idempotency_key or "action-%s" % uuid.uuid4().hex
        dynamic = workflow_revision_id not in (None, "legacy")
        if dynamic:
            suffix = ":attempt:%s" % int(attempt)
            if not idempotency_key.endswith(suffix):
                idempotency_key += suffix
        with self.db.transaction() as conn:
            # Serialize version allocation for this logical proposal without
            # requiring a separate sequence row.
            conn.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ("%s:%s" % (tenant_id, proposal_id),),
            )
            if dynamic:
                unresolved = conn.execute(
                    """
                    select 1 from orchestrator.action_proposals
                    where tenant_id = %s and proposal_id = %s
                      and status in ('executing', 'execution_unknown')
                    limit 1
                    """,
                    (tenant_id, proposal_id),
                ).fetchone()
                if unresolved:
                    raise ValueError(
                        "prior attempt is still executing or unresolved"
                    )
            version = conn.execute(
                """
                select coalesce(max(version), 0) + 1
                from orchestrator.action_proposals
                where tenant_id = %s and proposal_id = %s
                """,
                (tenant_id, proposal_id),
            ).fetchone()[0]
            conn.execute(
                """
                update orchestrator.action_proposals set status = 'superseded'
                where tenant_id = %s and proposal_id = %s
                  and status in ('proposed', 'approved')
                """,
                (tenant_id, proposal_id),
            )
            conn.execute(
                """
                insert into orchestrator.action_proposals(
                    proposal_id, version, tenant_id, user_principal_id,
                    agent_principal_id, credential_id, capability_id,
                    payload_json, payload_hash, idempotency_key, status,
                    expires_at, workflow_revision_id, step_id,
                    plan_graph_hash, connection_id, attempt,
                    authority_profile, authority_profile_id,
                    slack_subject_id, reinforced
                ) values (
                    %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s,
                    'proposed', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    proposal_id, version, tenant_id, user_principal_id,
                    agent_principal_id, credential_id, capability_id,
                    canonical_payload(payload), canonical_payload_hash(payload),
                    idempotency_key, _utc(expires_at), workflow_revision_id,
                    step_id, plan_graph_hash, connection_id, int(attempt),
                    authority_profile or "bot", authority_profile_id or "none",
                    slack_subject_id or "none", bool(reinforced),
                ),
            )
        return self.get(proposal_id, version, tenant_id)

    def get(self, proposal_id, version=None, tenant_id=None):
        tenant_id = self._tenant(tenant_id)
        sql = """
            select to_jsonb(p) from orchestrator.action_proposals p
            where tenant_id = %s and proposal_id = %s
        """
        params = [tenant_id, proposal_id]
        if version is None:
            sql += " order by version desc limit 1"
        else:
            sql += " and version = %s"
            params.append(int(version))
        with self.db.connection() as conn:
            row = conn.execute(sql, params).fetchone()
        return _normalize_postgres(row[0] if row else None)

    def get_by_idempotency_key(self, idempotency_key, tenant_id=None):
        tenant_id = self._tenant(tenant_id)
        with self.db.connection() as conn:
            row = conn.execute(
                """
                select to_jsonb(p) from orchestrator.action_proposals p
                where tenant_id = %s and idempotency_key = %s
                """,
                (tenant_id, idempotency_key),
            ).fetchone()
        return _normalize_postgres(row[0] if row else None)

    def decide(self, proposal_id, version, user_principal_id, approved, now_ts,
               tenant_id=None):
        tenant_id = self._tenant(tenant_id)
        status = "approved" if approved else "rejected"
        field = "approved_at" if approved else "rejected_at"
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                update orchestrator.action_proposals
                set status = %s, %s = %s
                where tenant_id = %s and proposal_id = %s and version = %s
                  and user_principal_id = %s and status = 'proposed'
                  and expires_at >= %s
                """ % ("%s", field, "%s", "%s", "%s", "%s", "%s", "%s"),
                (status, _utc(now_ts), tenant_id, proposal_id, int(version),
                 user_principal_id, _utc(now_ts)),
            )
        return cursor.rowcount == 1

    def consume_approval(self, binding, now_ts):
        required = (
            "proposal_id", "version", "user_principal_id",
            "agent_principal_id", "credential_id", "capability_id",
            "payload_hash", "idempotency_key",
        )
        if any(not binding.get(field) for field in required):
            return None
        tenant_id = self._tenant(binding.get("tenant_id"))
        dynamic = binding.get("workflow_revision_id") not in (None, "legacy")
        values = (
            binding["proposal_id"], int(binding["version"]),
            binding["user_principal_id"], binding["agent_principal_id"],
            binding["credential_id"], binding["capability_id"],
            binding["payload_hash"], binding["idempotency_key"],
            binding["workflow_revision_id"] if dynamic else "legacy",
            binding.get("step_id") if dynamic else "legacy",
            binding.get("plan_graph_hash") if dynamic else "legacy",
            binding.get("connection_id") if dynamic else "legacy",
            int(binding.get("attempt", 0)) if dynamic else 0,
        )
        with self.db.transaction() as conn:
            row = conn.execute(
                """
                update orchestrator.action_proposals
                set status = 'executing', execution_started_at = %s
                where tenant_id = %s and proposal_id = %s and version = %s
                  and user_principal_id = %s and agent_principal_id = %s
                  and credential_id = %s and capability_id = %s
                  and payload_hash = %s and idempotency_key = %s
                  and workflow_revision_id = %s and step_id = %s
                  and plan_graph_hash = %s and connection_id = %s
                  and attempt = %s and status = 'approved'
                  and expires_at >= %s
                returning to_jsonb(action_proposals)
                """,
                (_utc(now_ts), tenant_id) + values + (_utc(now_ts),),
            ).fetchone()
        return _normalize_postgres(row[0] if row else None)

    def issue_lease(
        self, user_principal_id, agent_principal_id, task_id, credential_id,
        capabilities, expires_at, workflow_revision_id="legacy",
        step_id="legacy", plan_graph_hash="legacy", connection_id="legacy",
        attempt=0, now_ts=None, authority_profile="bot",
        authority_profile_id=None, slack_subject_id=None, tenant_id=None,
    ):
        tenant_id = self._tenant(tenant_id)
        lease = secrets.token_urlsafe(32)
        now_ts = time.time() if now_ts is None else now_ts
        with self.db.transaction() as conn:
            if workflow_revision_id != "legacy":
                conn.execute(
                    """
                    update orchestrator.capability_leases set revoked_at = %s
                    where tenant_id = %s and workflow_revision_id = %s
                      and step_id = %s and consumed_at is null
                      and revoked_at is null
                    """,
                    (_utc(now_ts), tenant_id, workflow_revision_id, step_id),
                )
            conn.execute(
                """
                insert into orchestrator.capability_leases(
                    lease_hash, tenant_id, user_principal_id,
                    agent_principal_id, task_id, credential_id,
                    capabilities_json, expires_at, workflow_revision_id,
                    step_id, plan_graph_hash, connection_id, attempt,
                    authority_profile, authority_profile_id, slack_subject_id
                ) values (
                    %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    hashlib.sha256(lease.encode()).hexdigest(), tenant_id,
                    user_principal_id, agent_principal_id, task_id,
                    credential_id, canonical_payload(sorted(set(capabilities))),
                    _utc(expires_at), workflow_revision_id, step_id,
                    plan_graph_hash, connection_id, int(attempt),
                    authority_profile or "bot", authority_profile_id or "none",
                    slack_subject_id or "none",
                ),
            )
        return lease

    def validate_lease(self, lease, binding, now_ts):
        return self._lease_allowed(lease, binding, now_ts, consume=False)

    def consume_lease(self, lease, binding, now_ts):
        return self._lease_allowed(lease, binding, now_ts, consume=True)

    def _lease_allowed(self, lease, binding, now_ts, consume):
        if not lease:
            return False
        tenant_id = self._tenant(binding.get("tenant_id"))
        lease_hash = hashlib.sha256(lease.encode()).hexdigest()
        context = self.db.transaction() if consume else self.db.connection()
        with context as conn:
            row = conn.execute(
                """
                select to_jsonb(l) from orchestrator.capability_leases l
                where tenant_id = %s and lease_hash = %s
                  and user_principal_id = %s and agent_principal_id = %s
                  and task_id = %s and credential_id = %s
                  and revoked_at is null and consumed_at is null
                  and expires_at >= %s
                for update
                """ if consume else """
                select to_jsonb(l) from orchestrator.capability_leases l
                where tenant_id = %s and lease_hash = %s
                  and user_principal_id = %s and agent_principal_id = %s
                  and task_id = %s and credential_id = %s
                  and revoked_at is null and consumed_at is null
                  and expires_at >= %s
                """,
                (
                    tenant_id, lease_hash, binding.get("user_principal_id"),
                    binding.get("agent_principal_id"), binding.get("task_id"),
                    binding.get("credential_id"), _utc(now_ts),
                ),
            ).fetchone()
            if row is None:
                return False
            lease_row = row[0]
            allowed = (
                binding.get("capability_id") in lease_row["capabilities_json"]
                and ActionRepository._workflow_lease_binding_matches(
                    lease_row, binding
                )
            )
            if allowed and consume:
                cursor = conn.execute(
                    """
                    update orchestrator.capability_leases set consumed_at = %s
                    where tenant_id = %s and lease_hash = %s
                      and consumed_at is null
                    """,
                    (_utc(now_ts), tenant_id, lease_hash),
                )
                allowed = cursor.rowcount == 1
            return allowed

    def complete_execution(self, proposal_id, version, receipt, now_ts,
                           broker_response=None):
        return self._finish(
            proposal_id, version, "completed", now_ts,
            receipt=receipt, broker_response=broker_response,
            from_statuses=("executing", "execution_unknown"),
        )

    def mark_dispatched(self, proposal_id, version, now_ts):
        tenant_id = self._tenant(None)
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                update orchestrator.action_proposals set dispatched_at = %s
                where tenant_id = %s and proposal_id = %s and version = %s
                  and status = 'executing' and dispatched_at is null
                """,
                (_utc(now_ts), tenant_id, proposal_id, int(version)),
            )
        return cursor.rowcount == 1

    def recover_pre_dispatch_claim(self, proposal_id, version):
        tenant_id = self._tenant(None)
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                update orchestrator.action_proposals
                set status = 'approved', execution_started_at = null
                where tenant_id = %s and proposal_id = %s and version = %s
                  and status = 'executing' and dispatched_at is null
                """,
                (tenant_id, proposal_id, int(version)),
            )
        return cursor.rowcount == 1

    def fail_execution(self, proposal_id, version, reason, now_ts,
                       unknown=False):
        return self._finish(
            proposal_id, version,
            "execution_unknown" if unknown else "failed", now_ts,
            reason=str(reason)[:500], from_statuses=("executing",),
        )

    def resolve_unknown_as_absent(self, proposal_id, version, reason, now_ts):
        return self._finish(
            proposal_id, version, "failed", now_ts,
            reason=str(reason)[:500], from_statuses=("execution_unknown",),
        )

    def _finish(self, proposal_id, version, status, now_ts, receipt=None,
                broker_response=None, reason=None, from_statuses=()):
        tenant_id = self._tenant(None)
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                update orchestrator.action_proposals set
                    status = %s, execution_finished_at = %s,
                    receipt_json = coalesce(%s::jsonb, receipt_json),
                    broker_response_json = coalesce(%s::jsonb, broker_response_json),
                    failure_reason = coalesce(%s, failure_reason)
                where tenant_id = %s and proposal_id = %s and version = %s
                  and status = any(%s)
                """,
                (
                    status, _utc(now_ts),
                    canonical_payload(receipt) if receipt is not None else None,
                    canonical_payload(broker_response)
                    if broker_response is not None else None,
                    reason, tenant_id, proposal_id, int(version),
                    list(from_statuses),
                ),
            )
        return cursor.rowcount == 1

    def sweep_stalled_executions(self, now_ts, limit=100):
        tenant_id = self._tenant(None)
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                select p.proposal_id, p.version, p.dispatched_at
                from orchestrator.action_proposals p
                left join orchestrator.capability_leases l
                  on l.tenant_id = p.tenant_id
                 and l.workflow_revision_id = p.workflow_revision_id
                 and l.step_id = p.step_id and l.attempt = p.attempt
                where p.tenant_id = %s and p.status = 'executing'
                group by p.proposal_id, p.version, p.dispatched_at, p.expires_at
                having coalesce(max(l.expires_at), p.expires_at) < %s
                order by p.proposal_id limit %s
                """,
                (tenant_id, _utc(now_ts), int(limit)),
            ).fetchall()
        swept = {"recovered": [], "unknown": []}
        for proposal_id, version, dispatched_at in rows:
            if dispatched_at is None:
                if self.recover_pre_dispatch_claim(proposal_id, version):
                    swept["recovered"].append(proposal_id)
            elif self.fail_execution(
                proposal_id, version,
                "dispatch lease expired without an observed outcome",
                now_ts, unknown=True,
            ):
                swept["unknown"].append(proposal_id)
        return swept

    def close(self):
        return None

    @staticmethod
    def _tenant(tenant_id):
        tenant_id = tenant_id or current_organization_id()
        if not tenant_id:
            raise ValueError("tenant_id is required")
        return tenant_id


def _normalize_postgres(row):
    if row is None:
        return None
    result = dict(row)
    result["payload"] = result.pop("payload_json")
    if result.get("receipt_json") is not None:
        result["receipt"] = result["receipt_json"]
    if result.get("broker_response_json") is not None:
        result["broker_response"] = result["broker_response_json"]
    for key, value in tuple(result.items()):
        if isinstance(value, datetime):
            result[key] = int(value.timestamp())
    return result


def _utc(value):
    return datetime.fromtimestamp(int(value), tz=timezone.utc)
