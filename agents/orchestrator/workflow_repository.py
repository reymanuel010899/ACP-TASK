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
    CONVERSATION_STATUSES = frozenset({
        "interpreting", "resolving", "needs_input", "retrieving", "answering",
        "ready", "awaiting_approval", "executing", "succeeded",
        "retryable_failure", "unknown_outcome", "cancelled", "expired", "closed",
    })
    CONVERSATION_STATE_FIELDS = frozenset({
        "locale", "operation", "operation_candidates", "active_connection",
        "active_channel", "active_person", "active_thread", "active_message",
        "active_file", "active_reaction", "read_period", "pending_draft",
        "effect_candidates", "known_inputs", "slot_state", "corrections",
        "dependencies", "blockers", "entity_refs", "blocking_need",
        "resolution_request", "read_progress",
    })
    READ_PAGE_BUDGET = 5
    READ_MESSAGE_BUDGET = 500
    SLACK_ENTITY_FIELDS = {
        "workspace": frozenset({"id", "name", "domain"}),
        "channel": frozenset({
            "id", "name", "is_private", "is_archived", "is_ext_shared",
        }),
        "user": frozenset({
            "id", "display_name", "real_name", "handle", "image_url",
            "is_bot", "deleted",
        }),
        "message": frozenset({"channel_id", "ts", "thread_ts", "user_id"}),
        "thread": frozenset({"channel_id", "thread_ts", "parent_ts"}),
        "file": frozenset({"id", "name", "mimetype", "size", "user_id"}),
        "reaction": frozenset({"channel_id", "message_ts", "name", "user_id"}),
    }
    SLACK_ENTITY_PROVENANCE_FIELDS = frozenset({
        "source", "resolver_run_id", "client_turn_id", "matched_by",
    })
    OUTCOME_EVENT_TYPES = frozenset({
        "operation_attempted", "clarification_requested", "corrected",
        "previewed", "approved", "rejected", "completed", "abandoned", "failed",
    })
    OUTCOME_METRIC_FIELDS = frozenset({
        "clarification_count", "correction_count", "turn_count",
        "page_count", "candidate_count", "duration_seconds",
        "terminal_outcome", "error_code", "locale",
    })
    RESOLVER_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
    RESOLVER_OUTCOMES = frozenset({
        "matched", "ambiguous", "not_found", "exhausted", "failed",
    })
    DEFAULT_RESOLVER_BUDGET = {"max_pages": 10, "max_candidates": 5000}

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
                credential_version INTEGER NOT NULL DEFAULT 0,
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
                authorization_mode TEXT NOT NULL DEFAULT 'explicit_write',
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
            CREATE TABLE IF NOT EXISTS concierge_conversations (
                conversation_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'interpreting',
                state_version INTEGER NOT NULL DEFAULT 1 CHECK(state_version > 0),
                state_json TEXT NOT NULL,
                presentation_json TEXT,
                presentation_hash TEXT,
                workflow_run_id TEXT,
                workflow_revision_id TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                content_expires_at INTEGER NOT NULL,
                closed_at INTEGER,
                UNIQUE(conversation_id, tenant_id, principal_id)
            );
            CREATE TABLE IF NOT EXISTS concierge_answers (
                conversation_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                field_name TEXT NOT NULL,
                answer_hash TEXT NOT NULL,
                workflow_run_id TEXT,
                workflow_revision_id TEXT,
                applied_at INTEGER NOT NULL,
                PRIMARY KEY(conversation_id, tenant_id, principal_id, idempotency_key),
                FOREIGN KEY(conversation_id, tenant_id, principal_id)
                    REFERENCES concierge_conversations(
                        conversation_id, tenant_id, principal_id
                    )
            );
            CREATE TABLE IF NOT EXISTS concierge_turns (
                conversation_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                client_turn_id TEXT NOT NULL,
                turn_version INTEGER NOT NULL CHECK(turn_version > 0),
                base_state_version INTEGER NOT NULL CHECK(base_state_version > 0),
                request_hash TEXT NOT NULL,
                request_json TEXT NOT NULL,
                response_hash TEXT,
                response_json TEXT,
                status TEXT NOT NULL CHECK(status IN (
                    'started', 'committed', 'conflicted', 'failed'
                )),
                content_expires_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                committed_at INTEGER,
                PRIMARY KEY(
                    conversation_id, tenant_id, principal_id, client_turn_id
                ),
                UNIQUE(
                    conversation_id, tenant_id, principal_id, turn_version
                ),
                FOREIGN KEY(conversation_id, tenant_id, principal_id)
                    REFERENCES concierge_conversations(
                        conversation_id, tenant_id, principal_id
                    )
            );
            CREATE UNIQUE INDEX IF NOT EXISTS concierge_turns_one_active_base
                ON concierge_turns(
                    conversation_id, tenant_id, principal_id, base_state_version
                ) WHERE status = 'started';
            CREATE TABLE IF NOT EXISTS slack_conversation_entities (
                entity_ref_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                entity_kind TEXT NOT NULL,
                connection_id TEXT NOT NULL,
                team_id TEXT NOT NULL,
                provider_entity_id TEXT NOT NULL,
                entity_version INTEGER NOT NULL CHECK(entity_version > 0),
                entity_hash TEXT NOT NULL,
                entity_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL DEFAULT '{}',
                observed_at INTEGER NOT NULL,
                stale_after INTEGER NOT NULL,
                superseded_at INTEGER,
                PRIMARY KEY(entity_ref_id, tenant_id),
                UNIQUE(
                    tenant_id, conversation_id, entity_kind, connection_id,
                    provider_entity_id, entity_version
                ),
                FOREIGN KEY(conversation_id, tenant_id, principal_id)
                    REFERENCES concierge_conversations(
                        conversation_id, tenant_id, principal_id
                    )
            );
            CREATE TABLE IF NOT EXISTS slack_resolver_runs (
                resolver_run_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                connection_id TEXT NOT NULL,
                entity_kind TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                requested_state_version INTEGER NOT NULL,
                status TEXT NOT NULL,
                cursor_json TEXT NOT NULL DEFAULT '{}',
                budget_json TEXT NOT NULL DEFAULT '{}',
                pages_processed INTEGER NOT NULL DEFAULT 0,
                candidates_seen INTEGER NOT NULL DEFAULT 0,
                retry_at INTEGER,
                last_error_code TEXT,
                workflow_run_id TEXT,
                workflow_revision_id TEXT,
                outcome_json TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                completed_at INTEGER,
                PRIMARY KEY(resolver_run_id, tenant_id),
                UNIQUE(tenant_id, conversation_id, resolver_run_id),
                FOREIGN KEY(conversation_id, tenant_id, principal_id)
                    REFERENCES concierge_conversations(
                        conversation_id, tenant_id, principal_id
                    )
            );
            CREATE TABLE IF NOT EXISTS concierge_outcome_events (
                event_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                event_sequence INTEGER NOT NULL CHECK(event_sequence > 0),
                event_type TEXT NOT NULL,
                operation_family TEXT,
                metrics_json TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL,
                PRIMARY KEY(event_id, tenant_id),
                UNIQUE(tenant_id, conversation_id, event_sequence),
                FOREIGN KEY(conversation_id, tenant_id, principal_id)
                    REFERENCES concierge_conversations(
                        conversation_id, tenant_id, principal_id
                    )
            );
            CREATE TABLE IF NOT EXISTS workflow_outbox (
                event_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                aggregate_type TEXT NOT NULL,
                aggregate_id TEXT NOT NULL,
                aggregate_version INTEGER NOT NULL CHECK(aggregate_version > 0),
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                dedupe_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'claimed', 'completed', 'dead_letter')),
                attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                max_attempts INTEGER NOT NULL DEFAULT 5 CHECK(max_attempts > 0),
                available_at INTEGER NOT NULL,
                claimed_by TEXT,
                claim_expires_at INTEGER,
                last_error TEXT,
                created_at INTEGER NOT NULL,
                completed_at INTEGER,
                dead_lettered_at INTEGER,
                UNIQUE(tenant_id, dedupe_key),
                UNIQUE(tenant_id, aggregate_type, aggregate_id, aggregate_version)
            );
            CREATE INDEX IF NOT EXISTS workflow_outbox_claimable
                ON workflow_outbox(status, available_at, created_at);
            CREATE INDEX IF NOT EXISTS workflow_outbox_aggregate_order
                ON workflow_outbox(
                    tenant_id, aggregate_type, aggregate_id, aggregate_version
                );
            CREATE TABLE IF NOT EXISTS workflow_projection_watermarks (
                tenant_id TEXT NOT NULL,
                projection_name TEXT NOT NULL,
                aggregate_type TEXT NOT NULL,
                aggregate_id TEXT NOT NULL,
                projected_version INTEGER NOT NULL CHECK(projected_version > 0),
                last_event_id TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(
                    tenant_id, projection_name, aggregate_type, aggregate_id
                )
            );
        """)
        self._ensure_step_column("input_json", "TEXT NOT NULL DEFAULT '{}'")
        self._ensure_step_column("output_json", "TEXT")
        self._ensure_step_column("retry_at", "INTEGER")
        self._ensure_step_column("content_expires_at", "INTEGER")
        self._ensure_step_column("credential_version", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_table_column("workflow_approvals", "expires_at", "INTEGER")
        self._ensure_table_column(
            "workflow_approvals", "authorization_mode",
            "TEXT NOT NULL DEFAULT 'explicit_write'",
        )
        self._ensure_table_column(
            "concierge_conversations", "state_version",
            "INTEGER NOT NULL DEFAULT 1 CHECK(state_version > 0)",
        )
        self._ensure_table_column(
            "slack_conversation_entities", "provider_entity_id", "TEXT",
        )
        self._connection.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS slack_entity_versions
               ON slack_conversation_entities(
                   tenant_id, conversation_id, entity_kind, connection_id,
                   provider_entity_id, entity_version
               )"""
        )
        for column in ("workflow_run_id", "workflow_revision_id", "outcome_json"):
            self._ensure_table_column("slack_resolver_runs", column, "TEXT")
        self._connection.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS slack_resolver_runs_request
               ON slack_resolver_runs(
                   tenant_id, conversation_id, connection_id, entity_kind,
                   query_hash, requested_state_version
               )"""
        )
        self._connection.execute(
            """CREATE INDEX IF NOT EXISTS slack_resolver_runs_claimable
               ON slack_resolver_runs(status, retry_at, updated_at)"""
        )

    def _ensure_step_column(self, name, declaration):
        self._ensure_table_column("workflow_steps", name, declaration)

    def _ensure_table_column(self, table, name, declaration):
        columns = {
            row["name"] for row in self._connection.execute(
                "PRAGMA table_info(%s)" % table
            ).fetchall()
        }
        if name not in columns:
            cursor = self._connection.execute(
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

    @staticmethod
    def _conversation_content_context(tenant_id, conversation_id, field):
        return {
            "purpose": "concierge-conversation", "tenant_id": tenant_id,
            "conversation_id": conversation_id, "field": field,
        }

    def _encode_conversation_content(self, value, tenant_id, conversation_id, field):
        stored = value
        if self.content_crypto is not None:
            stored = self.content_crypto.seal(
                value,
                self._conversation_content_context(tenant_id, conversation_id, field),
            )
        return json.dumps(stored, sort_keys=True, separators=(",", ":"))

    def _decode_conversation_content(self, raw, tenant_id, conversation_id, field, default):
        if raw is None:
            return default
        stored = json.loads(raw)
        if self.content_crypto is None:
            return stored
        return self.content_crypto.open(
            stored,
            self._conversation_content_context(tenant_id, conversation_id, field),
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
                    "WHERE workflow_run_id = ? AND status IN "
                    "('draft', 'awaiting_approval', 'approved', 'authorized')",
                    (workflow_run_id,),
                )
                self._connection.execute(
                    "UPDATE workflow_steps SET execution_status = 'cancelled', "
                    "terminal_reason = 'superseded by a new revision' "
                    "WHERE workflow_run_id = ? AND execution_status IN "
                    "('queued', 'paused_by_policy')",
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
                            credential_version, input_json, depends_on_json, effect, verification_status,
                            content_expires_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            revision_id, step["step_id"], workflow_run_id,
                            tenant_id, step["capability_id"],
                            step["capability_version"], step.get("connection_id"),
                            step["descriptor_snapshot_hash"], step["input_hash"],
                            int(step.get("credential_version") or 0),
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

    def list_runnable_revisions(self, limit=100):
        with self._lock:
            rows = self._connection.execute(
                """SELECT r.workflow_run_id, r.workflow_revision_id, r.tenant_id,
                          a.authorization_mode
                   FROM workflow_revisions r
                   JOIN workflow_approvals a
                     ON a.workflow_revision_id = r.workflow_revision_id
                    AND a.workflow_run_id = r.workflow_run_id
                    AND a.tenant_id = r.tenant_id
                   WHERE r.status IN ('approved', 'authorized')
                     AND EXISTS (
                       SELECT 1 FROM workflow_steps s
                       WHERE s.workflow_revision_id = r.workflow_revision_id
                         AND s.execution_status = 'queued'
                     ) ORDER BY r.created_at, r.workflow_revision_id LIMIT ?""",
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def authorize_requested_read(
        self, workflow_run_id, revision_id, tenant_id, graph_hash,
        requested_by, now_ts, ttl_seconds=900,
    ):
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                effects = self._connection.execute(
                    "SELECT DISTINCT effect FROM workflow_steps "
                    "WHERE workflow_run_id = ? AND workflow_revision_id = ? "
                    "AND tenant_id = ?",
                    (workflow_run_id, revision_id, tenant_id),
                ).fetchall()
                if not effects or any(row["effect"] != "read" for row in effects):
                    raise ValueError("requested_read authorization requires a read-only revision")
                cursor = self._connection.execute(
                    """INSERT INTO workflow_approvals(
                        workflow_revision_id, workflow_run_id, tenant_id,
                        plan_graph_hash, approved_by, approved_at, expires_at,
                        authorization_mode
                    ) SELECT workflow_revision_id, workflow_run_id, tenant_id,
                             plan_graph_hash, ?, ?, ?, 'requested_read'
                      FROM workflow_revisions
                      WHERE workflow_revision_id = ? AND workflow_run_id = ?
                        AND tenant_id = ? AND plan_graph_hash = ? AND status = 'draft'""",
                    (requested_by, int(now_ts), int(now_ts) + int(ttl_seconds),
                     revision_id, workflow_run_id, tenant_id, graph_hash),
                )
                if cursor.rowcount != 1:
                    raise ValueError("revision authorization binding changed")
                self._connection.execute(
                    "UPDATE workflow_revisions SET status = 'authorized' "
                    "WHERE workflow_revision_id = ?", (revision_id,),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return True

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
                        plan_graph_hash, approved_by, approved_at, expires_at,
                        authorization_mode
                    ) SELECT workflow_revision_id, workflow_run_id, tenant_id,
                             plan_graph_hash, ?, ?, ?, 'explicit_write'
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
                     AND tenant_id = ? AND plan_graph_hash = ?
                     AND authorization_mode = 'explicit_write'""",
                (workflow_run_id, revision_id, tenant_id, graph_hash),
            ).fetchone()
        return bool(
            row is not None
            and (now_ts is None or row["expires_at"] is None or row["expires_at"] >= int(now_ts))
        )

    def revision_authorization_mode(
        self, workflow_run_id, revision_id, tenant_id, graph_hash, now_ts=None
    ):
        with self._lock:
            row = self._connection.execute(
                """SELECT authorization_mode, expires_at FROM workflow_approvals
                   WHERE workflow_run_id = ? AND workflow_revision_id = ?
                     AND tenant_id = ? AND plan_graph_hash = ?""",
                (workflow_run_id, revision_id, tenant_id, graph_hash),
            ).fetchone()
        if row is None or (
            now_ts is not None and row["expires_at"] is not None
            and row["expires_at"] < int(now_ts)
        ):
            return None
        return row["authorization_mode"]

    def is_step_authorized(
        self, workflow_run_id, revision_id, tenant_id, graph_hash, effect,
        now_ts=None,
    ):
        with self._lock:
            row = self._connection.execute(
                """SELECT approval.authorization_mode, approval.expires_at,
                          revision.status AS revision_status,
                          run.current_revision_id
                   FROM workflow_approvals AS approval
                   JOIN workflow_revisions AS revision
                     ON revision.workflow_revision_id = approval.workflow_revision_id
                    AND revision.workflow_run_id = approval.workflow_run_id
                    AND revision.tenant_id = approval.tenant_id
                   JOIN workflow_runs AS run
                     ON run.workflow_run_id = revision.workflow_run_id
                    AND run.tenant_id = revision.tenant_id
                   WHERE approval.workflow_run_id = ?
                     AND approval.workflow_revision_id = ?
                     AND approval.tenant_id = ?
                     AND approval.plan_graph_hash = ?""",
                (workflow_run_id, revision_id, tenant_id, graph_hash),
            ).fetchone()
        if row is None or row["current_revision_id"] != revision_id:
            return False
        if row["revision_status"] not in (
            "approved", "authorized", "executing", "in_progress", "completed",
        ):
            return False
        if (
            now_ts is not None
            and row["expires_at"] is not None
            and row["expires_at"] < int(now_ts)
        ):
            return False
        mode = row["authorization_mode"]
        return mode == "explicit_write" or (
            mode == "requested_read" and effect == "read"
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

    def retry_safe_write(self, revision_id, step_id, tenant_id, attempt):
        """A write is retryable only after reconciliation moved it to queued."""
        with self._lock:
            row = self._connection.execute(
                """SELECT execution_status FROM workflow_steps
                   WHERE workflow_revision_id = ? AND step_id = ?
                     AND tenant_id = ? AND attempt = ? AND effect = 'write'""",
                (revision_id, step_id, tenant_id, int(attempt)),
            ).fetchone()
        return bool(row is not None and row["execution_status"] == "queued")

    def retry_corrected_write(self, revision_id, step_id, tenant_id):
        """Retry only a write proven to have failed before broker dispatch."""
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE workflow_steps SET execution_status = 'queued',
                          terminal_reason = NULL, claimed_by = NULL, claimed_at = NULL
                   WHERE workflow_revision_id = ? AND step_id = ? AND tenant_id = ?
                     AND effect = 'write' AND execution_status = 'paused_by_policy'
                     AND terminal_reason LIKE 'missing_scope:%'""",
                (revision_id, step_id, tenant_id),
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
            "scopeUpgradeStepIds": [
                step["step_id"] for step in steps
                if step.get("effect") == "write"
                and step.get("execution_status") == "paused_by_policy"
                and str(step.get("terminal_reason") or "").startswith("missing_scope:")
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

    # Native Concierge conversation state is intentionally separate from the
    # agent-to-agent task envelope in conversation_state.py.
    def create_conversation(
        self, tenant_id, principal_id, now_ts, ttl_seconds=180,
        conversation_id=None, locale=None,
    ):
        if not tenant_id or not principal_id:
            raise ValueError("tenant_id and principal_id are required")
        conversation_id = conversation_id or "conversation:%s" % uuid.uuid4().hex
        now_ts = int(now_ts)
        expires_at = now_ts + int(ttl_seconds)
        state = {"locale": locale} if locale else {}
        with self._lock:
            self._connection.execute(
                """INSERT INTO concierge_conversations(
                    conversation_id, tenant_id, principal_id, status, state_json,
                    created_at, updated_at, expires_at, content_expires_at
                ) VALUES (?, ?, ?, 'interpreting', ?, ?, ?, ?, ?)""",
                (conversation_id, tenant_id, principal_id,
                 self._encode_conversation_content(
                     state, tenant_id, conversation_id, "state"
                 ), now_ts, now_ts, expires_at, expires_at),
            )
        return self.get_conversation(
            conversation_id, tenant_id, principal_id, now_ts
        )

    def get_conversation(
        self, conversation_id, tenant_id, principal_id, now_ts,
        include_terminal=False,
    ):
        """Return an owner-bound live conversation without existence leakage."""
        now_ts = int(now_ts)
        with self._lock:
            row = self._connection.execute(
                """SELECT * FROM concierge_conversations
                   WHERE conversation_id = ? AND tenant_id = ? AND principal_id = ?""",
                (conversation_id, tenant_id, principal_id),
            ).fetchone()
            if row is None:
                return None
            if row["status"] not in ("closed", "expired") and now_ts > row["expires_at"]:
                self._connection.execute(
                    """UPDATE concierge_conversations
                       SET status = 'expired', state_json = ?, presentation_json = NULL,
                           closed_at = ?, updated_at = ?
                       WHERE conversation_id = ? AND tenant_id = ? AND principal_id = ?""",
                    (self._encode_conversation_content(
                        {}, tenant_id, conversation_id, "state"
                    ), now_ts, now_ts, conversation_id, tenant_id, principal_id),
                )
                row = self._connection.execute(
                    """SELECT * FROM concierge_conversations
                       WHERE conversation_id = ? AND tenant_id = ? AND principal_id = ?""",
                    (conversation_id, tenant_id, principal_id),
                ).fetchone()
            if row["status"] in ("closed", "expired") and not include_terminal:
                return None
        return self._conversation(row)

    def _conversation(self, row):
        result = {
            "conversation_id": row["conversation_id"],
            "tenant_id": row["tenant_id"],
            "principal_id": row["principal_id"],
            "status": row["status"],
            "state_version": int(row["state_version"]),
            "workflow_run_id": row["workflow_run_id"],
            "workflow_revision_id": row["workflow_revision_id"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "expires_at": row["expires_at"], "closed_at": row["closed_at"],
            "presentation_hash": row["presentation_hash"],
        }
        result.update(self._decode_conversation_content(
            row["state_json"], row["tenant_id"], row["conversation_id"],
            "state", {},
        ))
        result["presentation"] = self._decode_conversation_content(
            row["presentation_json"], row["tenant_id"], row["conversation_id"],
            "presentation", None,
        )
        return result

    def update_conversation(
        self, conversation_id, tenant_id, principal_id, changes, now_ts,
        ttl_seconds=180, expected_version=None,
    ):
        allowed = set(self.CONVERSATION_STATE_FIELDS) | {
            "status", "workflow_run_id", "workflow_revision_id",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError("unsupported conversation fields: %s" % sorted(unknown))
        now_ts = int(now_ts)
        with self._lock:
            current = self.get_conversation(
                conversation_id, tenant_id, principal_id, now_ts
            )
            if current is None:
                raise KeyError("conversation unavailable")
            if expected_version is not None and int(
                current["state_version"]
            ) != int(expected_version):
                raise RuntimeError("conversation version conflict")
            state = {
                key: current.get(key) for key in allowed
                if key not in ("status", "workflow_run_id", "workflow_revision_id")
                and current.get(key) is not None
            }
            for key, value in changes.items():
                if key not in ("status", "workflow_run_id", "workflow_revision_id"):
                    if value is None:
                        state.pop(key, None)
                    else:
                        state[key] = value
            status = changes.get("status", current["status"])
            if status not in self.CONVERSATION_STATUSES:
                raise ValueError("invalid conversation status")
            run_id = changes.get("workflow_run_id", current["workflow_run_id"])
            revision_id = changes.get(
                "workflow_revision_id", current["workflow_revision_id"]
            )
            cursor = self._connection.execute(
                """UPDATE concierge_conversations SET status = ?, state_json = ?,
                       workflow_run_id = ?, workflow_revision_id = ?, updated_at = ?,
                       expires_at = ?, content_expires_at = ?,
                       state_version = state_version + 1
                   WHERE conversation_id = ? AND tenant_id = ? AND principal_id = ?
                     AND state_version = ?""",
                (status, self._encode_conversation_content(
                    state, tenant_id, conversation_id, "state"
                ), run_id, revision_id, now_ts, now_ts + int(ttl_seconds),
                 now_ts + int(ttl_seconds), conversation_id, tenant_id, principal_id,
                 int(current["state_version"])),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("conversation version conflict")
        return self.get_conversation(
            conversation_id, tenant_id, principal_id, now_ts
        )

    def begin_conversation_turn(
        self, conversation_id, tenant_id, principal_id, client_turn_id,
        expected_version, request, now_ts, content_ttl_seconds=180,
    ):
        """Reserve one owner-bound client turn without advancing conversation state."""
        if not client_turn_id or not isinstance(request, dict):
            raise ValueError("client_turn_id and request object are required")
        expected_version = int(expected_version)
        now_ts = int(now_ts)
        request_raw = json.dumps(request, sort_keys=True, separators=(",", ":"))
        request_hash = hashlib.sha256(request_raw.encode("utf-8")).hexdigest()
        with self._lock:
            current = self.get_conversation(
                conversation_id, tenant_id, principal_id, now_ts
            )
            if current is None:
                raise KeyError("conversation unavailable")
            prior = self._connection.execute(
                """SELECT * FROM concierge_turns
                   WHERE conversation_id = ? AND tenant_id = ?
                     AND principal_id = ? AND client_turn_id = ?""",
                (conversation_id, tenant_id, principal_id, client_turn_id),
            ).fetchone()
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise ValueError(
                        "client turn id was used for a different request"
                    )
                return self._conversation_turn_result(
                    prior, current, duplicate=True
                )
            if int(current["state_version"]) != expected_version:
                raise RuntimeError("conversation version conflict")
            active = self._connection.execute(
                """SELECT client_turn_id FROM concierge_turns
                   WHERE conversation_id = ? AND tenant_id = ?
                     AND principal_id = ? AND base_state_version = ?
                     AND status = 'started'""",
                (conversation_id, tenant_id, principal_id, expected_version),
            ).fetchone()
            if active is not None:
                raise RuntimeError("conversation turn already in progress")
            turn_version = self._connection.execute(
                """SELECT COALESCE(MAX(turn_version), 0) + 1 AS next_version
                   FROM concierge_turns WHERE conversation_id = ?
                     AND tenant_id = ? AND principal_id = ?""",
                (conversation_id, tenant_id, principal_id),
            ).fetchone()["next_version"]
            try:
                self._connection.execute(
                    """INSERT INTO concierge_turns(
                           conversation_id, tenant_id, principal_id, client_turn_id,
                           turn_version, base_state_version, request_hash,
                           request_json, status, content_expires_at, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'started', ?, ?)""",
                    (
                        conversation_id, tenant_id, principal_id, client_turn_id,
                        int(turn_version), expected_version, request_hash,
                        self._encode_conversation_content(
                            request, tenant_id, conversation_id,
                            "turn:%s:request" % client_turn_id,
                        ),
                        now_ts + int(content_ttl_seconds), now_ts,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise RuntimeError(
                    "conversation turn already in progress"
                ) from exc
            row = self._connection.execute(
                """SELECT * FROM concierge_turns
                   WHERE conversation_id = ? AND tenant_id = ?
                     AND principal_id = ? AND client_turn_id = ?""",
                (conversation_id, tenant_id, principal_id, client_turn_id),
            ).fetchone()
        return self._conversation_turn_result(row, current, duplicate=False)

    def commit_conversation_turn(
        self, conversation_id, tenant_id, principal_id, client_turn_id,
        expected_version, changes, response, now_ts, ttl_seconds=180,
    ):
        """Atomically apply a turn, advance CAS state, and append its event."""
        if not isinstance(changes, dict) or not isinstance(response, dict):
            raise ValueError("turn changes and response must be objects")
        allowed = set(self.CONVERSATION_STATE_FIELDS) | {
            "status", "workflow_run_id", "workflow_revision_id",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError("unsupported conversation fields: %s" % sorted(unknown))
        expected_version = int(expected_version)
        now_ts = int(now_ts)
        conflict = False
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                turn = self._connection.execute(
                    """SELECT * FROM concierge_turns
                       WHERE conversation_id = ? AND tenant_id = ?
                         AND principal_id = ? AND client_turn_id = ?""",
                    (conversation_id, tenant_id, principal_id, client_turn_id),
                ).fetchone()
                if turn is None:
                    raise KeyError("conversation turn unavailable")
                current_row = self._connection.execute(
                    """SELECT * FROM concierge_conversations
                       WHERE conversation_id = ? AND tenant_id = ?
                         AND principal_id = ?""",
                    (conversation_id, tenant_id, principal_id),
                ).fetchone()
                if current_row is None or current_row["status"] in (
                    "closed", "expired"
                ):
                    raise KeyError("conversation unavailable")
                current = self._conversation(current_row)
                if turn["status"] == "committed":
                    self._connection.execute("COMMIT")
                    return self._conversation_turn_result(
                        turn, current, duplicate=True
                    )
                if (
                    turn["status"] != "started"
                    or int(turn["base_state_version"]) != expected_version
                    or int(current["state_version"]) != expected_version
                ):
                    if turn["status"] == "started":
                        self._connection.execute(
                            """UPDATE concierge_turns SET status = 'conflicted'
                               WHERE conversation_id = ? AND tenant_id = ?
                                 AND principal_id = ? AND client_turn_id = ?""",
                            (conversation_id, tenant_id, principal_id, client_turn_id),
                        )
                    self._connection.execute("COMMIT")
                    conflict = True
                else:
                    state = {
                        key: current.get(key)
                        for key in self.CONVERSATION_STATE_FIELDS
                        if current.get(key) is not None
                    }
                    for key, value in changes.items():
                        if key not in {
                            "status", "workflow_run_id", "workflow_revision_id"
                        }:
                            if value is None:
                                state.pop(key, None)
                            else:
                                state[key] = value
                    blocking_need = state.get("blocking_need")
                    if blocking_need is not None and not isinstance(
                        blocking_need, dict
                    ):
                        raise ValueError("blocking_need must be one object")
                    status = changes.get("status", current["status"])
                    if status not in self.CONVERSATION_STATUSES:
                        raise ValueError("invalid conversation status")
                    run_id = changes.get(
                        "workflow_run_id", current["workflow_run_id"]
                    )
                    revision_id = changes.get(
                        "workflow_revision_id", current["workflow_revision_id"]
                    )
                    updated = self._connection.execute(
                        """UPDATE concierge_conversations SET status = ?,
                               state_json = ?, workflow_run_id = ?,
                               workflow_revision_id = ?, updated_at = ?,
                               expires_at = ?, content_expires_at = ?,
                               state_version = state_version + 1
                           WHERE conversation_id = ? AND tenant_id = ?
                             AND principal_id = ? AND state_version = ?""",
                        (
                            status,
                            self._encode_conversation_content(
                                state, tenant_id, conversation_id, "state"
                            ),
                            run_id, revision_id, now_ts,
                            now_ts + int(ttl_seconds),
                            now_ts + int(ttl_seconds),
                            conversation_id, tenant_id, principal_id,
                            expected_version,
                        ),
                    )
                    if updated.rowcount != 1:
                        raise RuntimeError("conversation version conflict")
                    response_raw = json.dumps(
                        response, sort_keys=True, separators=(",", ":")
                    )
                    response_hash = hashlib.sha256(
                        response_raw.encode("utf-8")
                    ).hexdigest()
                    self._connection.execute(
                        """UPDATE concierge_turns SET status = 'committed',
                               response_hash = ?, response_json = ?, committed_at = ?
                           WHERE conversation_id = ? AND tenant_id = ?
                             AND principal_id = ? AND client_turn_id = ?
                             AND status = 'started'""",
                        (
                            response_hash,
                            self._encode_conversation_content(
                                response, tenant_id, conversation_id,
                                "turn:%s:response" % client_turn_id,
                            ),
                            now_ts, conversation_id, tenant_id, principal_id,
                            client_turn_id,
                        ),
                    )
                    self.append_outbox_event(
                        tenant_id, "conversation", conversation_id,
                        "conversation.turn_committed",
                        {
                            "client_turn_id": client_turn_id,
                            "state_version": expected_version + 1,
                            "request_hash": turn["request_hash"],
                            "response_hash": response_hash,
                        },
                        "conversation-turn:%s:%s" % (
                            conversation_id, client_turn_id
                        ),
                        now_ts,
                    )
                    self._connection.execute("COMMIT")
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
            if conflict:
                raise RuntimeError("conversation version conflict")
            turn = self._connection.execute(
                """SELECT * FROM concierge_turns
                   WHERE conversation_id = ? AND tenant_id = ?
                     AND principal_id = ? AND client_turn_id = ?""",
                (conversation_id, tenant_id, principal_id, client_turn_id),
            ).fetchone()
            current = self.get_conversation(
                conversation_id, tenant_id, principal_id, now_ts
            )
        return self._conversation_turn_result(turn, current, duplicate=False)

    def _conversation_turn_result(self, row, conversation, duplicate):
        response = self._decode_conversation_content(
            row["response_json"], row["tenant_id"], row["conversation_id"],
            "turn:%s:response" % row["client_turn_id"], None,
        )
        return {
            "turn": {
                "client_turn_id": row["client_turn_id"],
                "turn_version": int(row["turn_version"]),
                "base_state_version": int(row["base_state_version"]),
                "status": row["status"],
                "request_hash": row["request_hash"],
                "response_hash": row["response_hash"],
            },
            "conversation": conversation,
            "response": response,
            "duplicate": bool(duplicate),
        }

    def store_slack_conversation_entity(
        self, conversation_id, tenant_id, principal_id, entity_kind,
        connection_id, team_id, provider_entity_id, entity, provenance,
        now_ts, stale_after_ts, expected_state_version=None,
    ):
        """Store one minimized, owner-bound provider snapshot idempotently."""
        fields = self.SLACK_ENTITY_FIELDS.get(entity_kind)
        if fields is None:
            raise ValueError("unsupported Slack entity kind")
        if not all((connection_id, team_id, provider_entity_id)):
            raise ValueError("Slack entity authority binding is required")
        if not isinstance(entity, dict) or not isinstance(provenance, dict):
            raise ValueError("Slack entity and provenance must be objects")
        minimized = {
            key: entity[key] for key in fields if entity.get(key) is not None
        }
        if not minimized:
            raise ValueError("Slack entity has no retainable fields")
        if str(minimized.get("id") or provider_entity_id) != str(
            provider_entity_id
        ) and entity_kind in {"workspace", "channel", "user", "file"}:
            raise ValueError("Slack entity provider identity changed")
        safe_provenance = {
            key: provenance[key]
            for key in self.SLACK_ENTITY_PROVENANCE_FIELDS
            if provenance.get(key) is not None
        }
        entity_raw = json.dumps(
            minimized, sort_keys=True, separators=(",", ":")
        )
        entity_hash = hashlib.sha256(entity_raw.encode("utf-8")).hexdigest()
        now_ts = int(now_ts)
        stale_after_ts = int(stale_after_ts)
        if stale_after_ts <= now_ts:
            raise ValueError("Slack entity freshness window must be in the future")
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                conversation = self._connection.execute(
                    """SELECT state_version FROM concierge_conversations
                       WHERE conversation_id = ? AND tenant_id = ?
                         AND principal_id = ? AND status NOT IN ('closed', 'expired')
                         AND expires_at >= ?""",
                    (conversation_id, tenant_id, principal_id, now_ts),
                ).fetchone()
                if conversation is None:
                    raise KeyError("conversation unavailable")
                if expected_state_version is not None and int(
                    conversation["state_version"]
                ) != int(expected_state_version):
                    raise RuntimeError("conversation version conflict")
                latest = self._connection.execute(
                    """SELECT * FROM slack_conversation_entities
                       WHERE conversation_id = ? AND tenant_id = ?
                         AND principal_id = ? AND entity_kind = ?
                         AND connection_id = ? AND team_id = ?
                         AND provider_entity_id = ?
                       ORDER BY entity_version DESC LIMIT 1""",
                    (
                        conversation_id, tenant_id, principal_id, entity_kind,
                        connection_id, team_id, provider_entity_id,
                    ),
                ).fetchone()
                if latest is not None and latest["entity_hash"] == entity_hash:
                    self._connection.execute("COMMIT")
                    return self._slack_conversation_entity(latest, now_ts)
                entity_version = 1 if latest is None else int(
                    latest["entity_version"]
                ) + 1
                if latest is not None and latest["superseded_at"] is None:
                    self._connection.execute(
                        """UPDATE slack_conversation_entities
                           SET superseded_at = ?
                           WHERE entity_ref_id = ? AND tenant_id = ?""",
                        (now_ts, latest["entity_ref_id"], tenant_id),
                    )
                entity_ref_id = "slack-entity:%s" % uuid.uuid4().hex
                self._connection.execute(
                    """INSERT INTO slack_conversation_entities(
                           entity_ref_id, tenant_id, conversation_id, principal_id,
                           entity_kind, connection_id, team_id, provider_entity_id,
                           entity_version, entity_hash, entity_json, provenance_json,
                           observed_at, stale_after
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        entity_ref_id, tenant_id, conversation_id, principal_id,
                        entity_kind, connection_id, team_id, provider_entity_id,
                        entity_version, entity_hash,
                        self._encode_conversation_content(
                            minimized, tenant_id, conversation_id,
                            "entity:%s" % entity_ref_id,
                        ),
                        json.dumps(
                            safe_provenance, sort_keys=True, separators=(",", ":")
                        ),
                        now_ts, stale_after_ts,
                    ),
                )
                row = self._connection.execute(
                    """SELECT * FROM slack_conversation_entities
                       WHERE entity_ref_id = ? AND tenant_id = ?""",
                    (entity_ref_id, tenant_id),
                ).fetchone()
                self._connection.execute("COMMIT")
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        return self._slack_conversation_entity(row, now_ts)

    def get_slack_conversation_entity(
        self, entity_ref_id, conversation_id, tenant_id, principal_id, now_ts,
        include_stale=False,
    ):
        with self._lock:
            row = self._connection.execute(
                """SELECT e.* FROM slack_conversation_entities e
                   JOIN concierge_conversations c
                     ON c.conversation_id = e.conversation_id
                    AND c.tenant_id = e.tenant_id
                    AND c.principal_id = e.principal_id
                   WHERE e.entity_ref_id = ? AND e.conversation_id = ?
                     AND e.tenant_id = ? AND e.principal_id = ?
                     AND c.status NOT IN ('closed', 'expired')
                     AND c.expires_at >= ?""",
                (
                    entity_ref_id, conversation_id, tenant_id, principal_id,
                    int(now_ts),
                ),
            ).fetchone()
        if row is None:
            return None
        stale = row["superseded_at"] is not None or int(row["stale_after"]) < int(
            now_ts
        )
        if stale and not include_stale:
            return None
        return self._slack_conversation_entity(row, int(now_ts))

    def _slack_conversation_entity(self, row, now_ts):
        result = {
            key: row[key] for key in (
                "entity_ref_id", "tenant_id", "conversation_id", "principal_id",
                "entity_kind", "connection_id", "team_id", "provider_entity_id",
                "entity_hash", "observed_at", "stale_after", "superseded_at",
            )
        }
        result["entity_version"] = int(row["entity_version"])
        result["provenance"] = json.loads(row["provenance_json"] or "{}")
        result["entity"] = self._decode_conversation_content(
            row["entity_json"], row["tenant_id"], row["conversation_id"],
            "entity:%s" % row["entity_ref_id"], {},
        )
        result["stale"] = (
            row["superseded_at"] is not None
            or int(row["stale_after"]) < int(now_ts)
        )
        return result

    def start_slack_resolver_run(
        self, conversation_id, tenant_id, principal_id, connection_id,
        entity_kind, query_hash, requested_state_version, now_ts, budget=None,
        workflow_run_id=None, workflow_revision_id=None,
    ):
        """Reserve one durable resolver run per request, replay-safe."""
        if not all((
            conversation_id, tenant_id, principal_id, connection_id,
            entity_kind, query_hash,
        )):
            raise ValueError("resolver run binding is required")
        if entity_kind not in self.SLACK_ENTITY_FIELDS:
            raise ValueError("unsupported Slack entity kind")
        requested_state_version = int(requested_state_version)
        if requested_state_version <= 0:
            raise ValueError("resolver run requires a positive state version")
        budget = {**self.DEFAULT_RESOLVER_BUDGET, **dict(budget or {})}
        now_ts = int(now_ts)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                conversation = self._connection.execute(
                    """SELECT 1 FROM concierge_conversations
                       WHERE conversation_id = ? AND tenant_id = ?
                         AND principal_id = ? AND status NOT IN ('closed', 'expired')
                         AND expires_at >= ?""",
                    (conversation_id, tenant_id, principal_id, now_ts),
                ).fetchone()
                if conversation is None:
                    raise KeyError("conversation unavailable")
                existing = self._connection.execute(
                    """SELECT * FROM slack_resolver_runs
                       WHERE tenant_id = ? AND conversation_id = ?
                         AND connection_id = ? AND entity_kind = ?
                         AND query_hash = ? AND requested_state_version = ?""",
                    (
                        tenant_id, conversation_id, connection_id, entity_kind,
                        query_hash, requested_state_version,
                    ),
                ).fetchone()
                if existing is not None:
                    self._connection.execute("COMMIT")
                    return dict(
                        self._slack_resolver_run(existing), created=False
                    )
                resolver_run_id = "slack-resolver:%s" % uuid.uuid4().hex
                self._connection.execute(
                    """INSERT INTO slack_resolver_runs(
                           resolver_run_id, tenant_id, conversation_id,
                           principal_id, connection_id, entity_kind, query_hash,
                           requested_state_version, status, cursor_json,
                           budget_json, workflow_run_id, workflow_revision_id,
                           created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)""",
                    (
                        resolver_run_id, tenant_id, conversation_id,
                        principal_id, connection_id, entity_kind, query_hash,
                        requested_state_version,
                        json.dumps({"next": None, "consumed": []}, sort_keys=True),
                        json.dumps(budget, sort_keys=True),
                        workflow_run_id, workflow_revision_id, now_ts, now_ts,
                    ),
                )
                row = self._connection.execute(
                    """SELECT * FROM slack_resolver_runs
                       WHERE resolver_run_id = ? AND tenant_id = ?""",
                    (resolver_run_id, tenant_id),
                ).fetchone()
                self._connection.execute("COMMIT")
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        return dict(self._slack_resolver_run(row), created=True)

    def record_slack_resolver_page(
        self, resolver_run_id, tenant_id, page_token, next_cursor,
        candidates_seen, now_ts, workflow_revision_id=None,
    ):
        """Advance one page durably, ignoring replayed provider callbacks."""
        now_ts = int(now_ts)
        page_token = "" if page_token is None else str(page_token)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    """SELECT * FROM slack_resolver_runs
                       WHERE resolver_run_id = ? AND tenant_id = ?""",
                    (resolver_run_id, tenant_id),
                ).fetchone()
                if row is None:
                    raise KeyError("resolver run not found")
                run = self._slack_resolver_run(row)
                if run["status"] in self.RESOLVER_TERMINAL_STATUSES:
                    self._connection.execute("COMMIT")
                    return dict(run, applied=False)
                cursor = dict(run["cursor"])
                consumed = list(cursor.get("consumed") or [])
                if page_token in consumed:
                    self._connection.execute("COMMIT")
                    return dict(run, applied=False)
                consumed.append(page_token)
                budget = run["budget"]
                pages_processed = run["pages_processed"] + 1
                candidates = run["candidates_seen"] + max(int(candidates_seen), 0)
                cursor = {"next": next_cursor, "consumed": consumed}
                self._connection.execute(
                    """UPDATE slack_resolver_runs
                       SET status = 'running', cursor_json = ?,
                           pages_processed = ?, candidates_seen = ?,
                           workflow_revision_id = COALESCE(?, workflow_revision_id),
                           updated_at = ?
                       WHERE resolver_run_id = ? AND tenant_id = ?""",
                    (
                        json.dumps(cursor, sort_keys=True), pages_processed,
                        candidates, workflow_revision_id, now_ts,
                        resolver_run_id, tenant_id,
                    ),
                )
                updated = self._connection.execute(
                    """SELECT * FROM slack_resolver_runs
                       WHERE resolver_run_id = ? AND tenant_id = ?""",
                    (resolver_run_id, tenant_id),
                ).fetchone()
                self._connection.execute("COMMIT")
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        result = self._slack_resolver_run(updated)
        result["applied"] = True
        result["budget_exhausted"] = (
            pages_processed >= int(budget.get("max_pages", 0) or 0)
            or candidates >= int(budget.get("max_candidates", 0) or 0)
        )
        result["exhausted"] = bool(
            result["budget_exhausted"] or not next_cursor
        )
        return result

    def complete_slack_resolver_run(
        self, resolver_run_id, tenant_id, outcome, now_ts, error_code=None,
    ):
        """Close a resolver run and publish its completion exactly once."""
        kind = (outcome or {}).get("kind")
        if kind not in self.RESOLVER_OUTCOMES:
            raise ValueError("unsupported resolver outcome")
        now_ts = int(now_ts)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    """SELECT * FROM slack_resolver_runs
                       WHERE resolver_run_id = ? AND tenant_id = ?""",
                    (resolver_run_id, tenant_id),
                ).fetchone()
                if row is None:
                    raise KeyError("resolver run not found")
                run = self._slack_resolver_run(row)
                if run["status"] in self.RESOLVER_TERMINAL_STATUSES:
                    self._connection.execute("COMMIT")
                    return dict(run, completed=False)
                status = "failed" if kind == "failed" else "completed"
                self._connection.execute(
                    """UPDATE slack_resolver_runs
                       SET status = ?, outcome_json = ?, last_error_code = ?,
                           updated_at = ?, completed_at = ?
                       WHERE resolver_run_id = ? AND tenant_id = ?
                         AND status NOT IN ('completed', 'failed', 'cancelled')""",
                    (
                        status,
                        self._encode_conversation_content(
                            dict(outcome), tenant_id, run["conversation_id"],
                            "resolver:%s" % resolver_run_id,
                        ),
                        error_code, now_ts, now_ts, resolver_run_id, tenant_id,
                    ),
                )
                self.append_outbox_event(
                    tenant_id, "conversation", run["conversation_id"],
                    "conversation.resolver_completed",
                    {
                        "resolver_run_id": resolver_run_id,
                        "principal_id": run["principal_id"],
                        "entity_kind": run["entity_kind"],
                        "outcome": kind,
                        "pages_processed": run["pages_processed"],
                        "candidates_seen": run["candidates_seen"],
                        "requested_state_version": run["requested_state_version"],
                    },
                    "slack-resolver:%s" % resolver_run_id, now_ts,
                )
                updated = self._connection.execute(
                    """SELECT * FROM slack_resolver_runs
                       WHERE resolver_run_id = ? AND tenant_id = ?""",
                    (resolver_run_id, tenant_id),
                ).fetchone()
                self._connection.execute("COMMIT")
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        return dict(self._slack_resolver_run(updated), completed=True)

    def list_paging_slack_reads(self, now_ts, limit=50):
        """Return live turns whose read has a page left to fetch."""
        now_ts = int(now_ts)
        with self._lock:
            rows = self._connection.execute(
                """SELECT conversation_id, tenant_id, principal_id
                   FROM concierge_conversations
                   WHERE status = 'retrieving'
                     AND status NOT IN ('closed', 'expired')
                     AND expires_at >= ?
                   ORDER BY updated_at ASC LIMIT ?""",
                (now_ts, int(limit)),
            ).fetchall()
        paging = []
        for row in rows:
            conversation = self.get_conversation(
                row["conversation_id"], row["tenant_id"], row["principal_id"],
                now_ts,
            )
            progress = (conversation or {}).get("read_progress") or {}
            if progress.get("cursor") and progress.get("dispatched") != progress[
                "cursor"
            ]:
                paging.append(conversation)
        return paging

    def _accumulate_slack_read_page(self, conversation, output, step_input):
        """Fold one page into the run and decide whether another is due.

        A single page is not an answer to "what was said this week"; it is the
        first hundred messages Slack happened to return. Pages accumulate until
        the cursor runs out or a budget stops them, and the budget stop is
        reported as partial rather than presented as complete.
        """
        prior = (conversation or {}).get("read_progress") or {}
        messages = list(prior.get("messages") or [])
        for message in (output.get("messages") or []):
            if isinstance(message, dict) and message.get("ts"):
                messages.append(message)
        pages = int(prior.get("pages") or 0) + 1
        cursor = output.get("next_cursor") or (
            output.get("response_metadata") or {}
        ).get("next_cursor") or None
        budget_exhausted = (
            pages >= self.READ_PAGE_BUDGET
            or len(messages) >= self.READ_MESSAGE_BUDGET
        )
        messages = messages[:self.READ_MESSAGE_BUDGET]
        state = {
            "pages": pages, "cursor": cursor, "messages": messages,
            "channel_id": step_input.get("channel_id"),
        }
        return {
            "state": state, "messages": messages,
            "budget_exhausted": bool(budget_exhausted and cursor),
            "continues": bool(cursor) and not budget_exhausted,
        }

    @staticmethod
    def _slack_author_labels(directory):
        """Map ids to a display name only; no email, title, or phone."""
        labels = {}
        for member in (directory or []):
            if not isinstance(member, dict) or not member.get("id"):
                continue
            label = (member.get("display_name") or member.get("real_name")
                     or member.get("handle"))
            if label:
                labels[member["id"]] = label
        return labels

    def _present_slack_evidence(self, output, step_input, locale,
                                directory=None):
        """Answer only from cited evidence, never by echoing channel text.

        The raw provider payload is untrusted: it carries other people's words
        and anything they chose to write, including instructions aimed at this
        system. Routing it through the presenter attributes every line to an
        author and a timestamp, and keeps the reviewed period and partiality
        attached to the answer rather than implied by it.
        """
        from agents.orchestrator.result_presenter import GroundedResultPresenter

        channel_id = step_input.get("channel_id")
        messages, citations = [], []
        for message in (output.get("messages") or []):
            if not isinstance(message, dict) or not message.get("ts"):
                continue
            messages.append({
                "channel_id": channel_id,
                "message_ts": message.get("ts"),
                "author_id": message.get("user"),
                "text": message.get("text", ""),
                "thread_ts": message.get("thread_ts"),
            })
            citations.append({
                "citation_id": "slack:%s:%s" % (channel_id, message["ts"]),
                "channel_id": channel_id,
                "message_ts": message["ts"],
                "author_id": message.get("user"),
            })
        period = ({"oldest": step_input["oldest"], "latest": step_input["latest"]}
                  if step_input.get("oldest") and step_input.get("latest")
                  else None)
        truncated = bool(output.get("next_cursor")) or bool(output.get("partial"))
        presented = GroundedResultPresenter().present(
            step_input.get("question") or "", {
                "messages": messages, "citations": citations,
                "period": period, "partial": truncated,
                "partial_reason": "page_budget_reached" if truncated else None,
            }, locale, self._slack_author_labels(directory),
        )
        # Permalinks require a per-message fan-out this slice does not perform,
        # so citations carry stable references and say so rather than implying
        # a link that was never fetched.
        presented["citation_complete"] = False
        return presented

    def append_conversation_outcome_event(
        self, conversation_id, tenant_id, principal_id, event_type, now_ts,
        operation_family=None, metrics=None,
    ):
        """Append one append-only product-outcome fact, metrics only."""
        if event_type not in self.OUTCOME_EVENT_TYPES:
            raise ValueError("unsupported conversation outcome event")
        if not all((conversation_id, tenant_id, principal_id)):
            raise ValueError("outcome events require owner binding")
        safe_metrics = {
            key: value for key, value in (metrics or {}).items()
            if key in self.OUTCOME_METRIC_FIELDS
            and isinstance(value, (int, float, str, bool))
        }
        now_ts = int(now_ts)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                owned = self._connection.execute(
                    """SELECT 1 FROM concierge_conversations
                       WHERE conversation_id = ? AND tenant_id = ?
                         AND principal_id = ?""",
                    (conversation_id, tenant_id, principal_id),
                ).fetchone()
                if owned is None:
                    raise KeyError("conversation unavailable")
                row = self._connection.execute(
                    """SELECT COALESCE(MAX(event_sequence), 0) AS sequence
                       FROM concierge_outcome_events
                       WHERE tenant_id = ? AND conversation_id = ?""",
                    (tenant_id, conversation_id),
                ).fetchone()
                sequence = int(row["sequence"]) + 1
                event_id = "outcome:%s" % uuid.uuid4().hex
                self._connection.execute(
                    """INSERT INTO concierge_outcome_events(
                           event_id, tenant_id, conversation_id, principal_id,
                           event_sequence, event_type, operation_family,
                           metrics_json, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event_id, tenant_id, conversation_id, principal_id,
                        sequence, event_type, operation_family,
                        json.dumps(
                            safe_metrics, sort_keys=True, separators=(",", ":")
                        ),
                        now_ts,
                    ),
                )
                self._connection.execute("COMMIT")
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        return {
            "event_id": event_id, "event_sequence": sequence,
            "event_type": event_type, "operation_family": operation_family,
            "metrics": safe_metrics, "created_at": now_ts,
        }

    def list_conversation_outcome_events(
        self, conversation_id, tenant_id, principal_id,
    ):
        if not all((conversation_id, tenant_id, principal_id)):
            raise ValueError("outcome event reads require owner binding")
        with self._lock:
            rows = self._connection.execute(
                """SELECT * FROM concierge_outcome_events
                   WHERE conversation_id = ? AND tenant_id = ?
                     AND principal_id = ?
                   ORDER BY event_sequence ASC""",
                (conversation_id, tenant_id, principal_id),
            ).fetchall()
        return [{
            "event_id": row["event_id"],
            "event_sequence": int(row["event_sequence"]),
            "event_type": row["event_type"],
            "operation_family": row["operation_family"],
            "metrics": json.loads(row["metrics_json"] or "{}"),
            "created_at": row["created_at"],
        } for row in rows]

    def conversation_outcome_baseline(self, tenant_id, since_ts, until_ts):
        """Aggregate the Phase 1 baseline without reading any content."""
        if not tenant_id:
            raise ValueError("baselines require a tenant")
        with self._lock:
            rows = self._connection.execute(
                """SELECT event_type, operation_family, COUNT(*) AS total,
                          COUNT(DISTINCT conversation_id) AS conversations
                   FROM concierge_outcome_events
                   WHERE tenant_id = ? AND created_at >= ? AND created_at < ?
                   GROUP BY event_type, operation_family""",
                (tenant_id, int(since_ts), int(until_ts)),
            ).fetchall()
        return [{
            "event_type": row["event_type"],
            "operation_family": row["operation_family"],
            "total": int(row["total"]),
            "conversations": int(row["conversations"]),
        } for row in rows]

    def _record_slack_resolver_step_page(
        self, resolver_run_id, tenant_id, resolver_step, output, candidates,
        now_ts,
    ):
        """Fold one executed resolver step into its durable run."""
        if not resolver_run_id:
            return None
        page_token = (resolver_step.get("input") or {}).get("cursor")
        next_cursor = output.get("next_cursor") or (
            output.get("response_metadata") or {}
        ).get("next_cursor")
        try:
            return self.record_slack_resolver_page(
                resolver_run_id, tenant_id, page_token, next_cursor or None,
                candidates, now_ts,
                workflow_revision_id=resolver_step.get("workflow_revision_id"),
            )
        except KeyError:
            return None

    def _complete_slack_resolver_run_if_any(
        self, resolver_run_id, tenant_id, outcome, now_ts,
    ):
        if not resolver_run_id:
            return None
        try:
            return self.complete_slack_resolver_run(
                resolver_run_id, tenant_id, outcome, now_ts
            )
        except KeyError:
            return None

    def get_slack_resolver_run(
        self, resolver_run_id, tenant_id, conversation_id=None,
        principal_id=None,
    ):
        if not tenant_id:
            raise ValueError("resolver run reads require a tenant")
        clauses = ["resolver_run_id = ?", "tenant_id = ?"]
        values = [resolver_run_id, tenant_id]
        if conversation_id is not None:
            clauses.append("conversation_id = ?")
            values.append(conversation_id)
        if principal_id is not None:
            clauses.append("principal_id = ?")
            values.append(principal_id)
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM slack_resolver_runs WHERE %s" % " AND ".join(clauses),
                tuple(values),
            ).fetchone()
        return self._slack_resolver_run(row) if row else None

    def list_resumable_slack_resolver_runs(self, now_ts, limit=50):
        """Return live runs whose conversation can still consume them."""
        now_ts = int(now_ts)
        with self._lock:
            rows = self._connection.execute(
                """SELECT r.* FROM slack_resolver_runs r
                   JOIN concierge_conversations c
                     ON c.conversation_id = r.conversation_id
                    AND c.tenant_id = r.tenant_id
                    AND c.principal_id = r.principal_id
                   WHERE r.status IN ('pending', 'running', 'waiting_retry')
                     AND (r.retry_at IS NULL OR r.retry_at <= ?)
                     AND c.status NOT IN ('closed', 'expired')
                     AND c.expires_at >= ?
                   ORDER BY r.updated_at ASC LIMIT ?""",
                (now_ts, now_ts, int(limit)),
            ).fetchall()
        return [self._slack_resolver_run(row) for row in rows]

    def attach_slack_resolver_workflow(
        self, resolver_run_id, tenant_id, workflow_run_id, workflow_revision_id,
        now_ts, cursor_token=None,
    ):
        """Bind the workflow now fetching one page, so retries stay single."""
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    """SELECT cursor_json FROM slack_resolver_runs
                       WHERE resolver_run_id = ? AND tenant_id = ?
                         AND status NOT IN ('completed', 'failed', 'cancelled')""",
                    (resolver_run_id, tenant_id),
                ).fetchone()
                if row is None:
                    self._connection.execute("COMMIT")
                    return False
                cursor = json.loads(row["cursor_json"] or "{}")
                cursor["dispatched"] = cursor_token
                self._connection.execute(
                    """UPDATE slack_resolver_runs
                       SET workflow_run_id = ?, workflow_revision_id = ?,
                           cursor_json = ?, status = 'running', updated_at = ?
                       WHERE resolver_run_id = ? AND tenant_id = ?
                         AND status NOT IN ('completed', 'failed', 'cancelled')""",
                    (
                        workflow_run_id, workflow_revision_id,
                        json.dumps(cursor, sort_keys=True), int(now_ts),
                        resolver_run_id, tenant_id,
                    ),
                )
                self._connection.execute("COMMIT")
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        return True

    def _slack_resolver_run(self, row):
        result = {
            key: row[key] for key in (
                "resolver_run_id", "tenant_id", "conversation_id",
                "principal_id", "connection_id", "entity_kind", "query_hash",
                "status", "retry_at", "last_error_code", "workflow_run_id",
                "workflow_revision_id", "created_at", "updated_at",
                "completed_at",
            )
        }
        result["requested_state_version"] = int(row["requested_state_version"])
        result["pages_processed"] = int(row["pages_processed"])
        result["candidates_seen"] = int(row["candidates_seen"])
        result["cursor"] = json.loads(row["cursor_json"] or "{}")
        result["budget"] = json.loads(row["budget_json"] or "{}")
        result["outcome"] = self._decode_conversation_content(
            row["outcome_json"], row["tenant_id"], row["conversation_id"],
            "resolver:%s" % row["resolver_run_id"], None,
        ) if row["outcome_json"] else None
        return result

    def apply_conversation_answer(
        self, conversation_id, tenant_id, principal_id, idempotency_key,
        field_name, value, now_ts, workflow_run_id=None,
        workflow_revision_id=None,
    ):
        if not idempotency_key or not field_name:
            raise ValueError("idempotency_key and field_name are required")
        answer_hash = hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        now_ts = int(now_ts)
        with self._lock:
            current = self.get_conversation(
                conversation_id, tenant_id, principal_id, now_ts
            )
            if current is None:
                raise KeyError("conversation unavailable")
            prior = self._connection.execute(
                """SELECT * FROM concierge_answers WHERE conversation_id = ?
                   AND tenant_id = ? AND principal_id = ? AND idempotency_key = ?""",
                (conversation_id, tenant_id, principal_id, idempotency_key),
            ).fetchone()
            if prior is not None:
                if prior["field_name"] != field_name or prior["answer_hash"] != answer_hash:
                    raise ValueError("idempotency key was used for a different answer")
                return self._conversation_answer_result(current, prior, True)
            need = current.get("blocking_need")
            if not isinstance(need, dict) or need.get("field") != field_name:
                raise ValueError("answer does not match the active blocking need")
            changes = {field_name: value, "blocking_need": None, "status": "interpreting"}
            # Entity fields are top-level state slots; arbitrary clarification
            # answers are retained under normalized known_inputs.
            if field_name not in {
                "locale", "operation", "active_connection", "active_channel",
                "active_person", "active_thread", "read_period", "pending_draft",
            }:
                known = dict(current.get("known_inputs") or {})
                known[field_name] = value
                changes.pop(field_name)
                changes["known_inputs"] = known
            # update_conversation intentionally has a narrow public allowlist;
            # known_inputs is written here as an internal normalized slot map.
            state = {
                key: current[key] for key in (
                    "locale", "operation", "active_connection", "active_channel",
                    "active_person", "active_thread", "read_period", "pending_draft",
                    "known_inputs",
                ) if current.get(key) is not None
            }
            state.update({k: v for k, v in changes.items() if k not in {
                "status", "workflow_run_id", "workflow_revision_id", "blocking_need"
            }})
            state.pop("blocking_need", None)
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    """INSERT INTO concierge_answers(
                        conversation_id, tenant_id, principal_id, idempotency_key,
                        field_name, answer_hash, workflow_run_id,
                        workflow_revision_id, applied_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (conversation_id, tenant_id, principal_id, idempotency_key,
                     field_name, answer_hash, workflow_run_id,
                     workflow_revision_id, now_ts),
                )
                self._connection.execute(
                    """UPDATE concierge_conversations SET status = 'interpreting',
                           state_json = ?, workflow_run_id = COALESCE(?, workflow_run_id),
                           workflow_revision_id = COALESCE(?, workflow_revision_id),
                           updated_at = ?
                       WHERE conversation_id = ? AND tenant_id = ? AND principal_id = ?""",
                    (self._encode_conversation_content(
                        state, tenant_id, conversation_id, "state"
                    ), workflow_run_id, workflow_revision_id, now_ts,
                     conversation_id, tenant_id, principal_id),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
            row = self._connection.execute(
                """SELECT * FROM concierge_answers WHERE conversation_id = ?
                   AND tenant_id = ? AND principal_id = ? AND idempotency_key = ?""",
                (conversation_id, tenant_id, principal_id, idempotency_key),
            ).fetchone()
            updated = self.get_conversation(
                conversation_id, tenant_id, principal_id, now_ts
            )
        return self._conversation_answer_result(updated, row, False)

    @staticmethod
    def _conversation_answer_result(conversation, row, duplicate):
        return {
            "conversation": conversation, "duplicate": duplicate,
            "workflow_run_id": row["workflow_run_id"],
            "workflow_revision_id": row["workflow_revision_id"],
        }

    def store_conversation_presentation(
        self, conversation_id, tenant_id, principal_id, presentation, now_ts,
        content_ttl_seconds=180,
    ):
        current = self.get_conversation(
            conversation_id, tenant_id, principal_id, now_ts
        )
        if current is None:
            raise KeyError("conversation unavailable")
        raw = json.dumps(presentation, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        with self._lock:
            self._connection.execute(
                """UPDATE concierge_conversations SET presentation_json = ?,
                       presentation_hash = ?, updated_at = ?, content_expires_at = ?
                   WHERE conversation_id = ? AND tenant_id = ? AND principal_id = ?""",
                (self._encode_conversation_content(
                    presentation, tenant_id, conversation_id, "presentation"
                ), digest, int(now_ts), int(now_ts) + int(content_ttl_seconds),
                 conversation_id, tenant_id, principal_id),
            )
        return self.get_conversation(
            conversation_id, tenant_id, principal_id, now_ts
        )

    def close_conversation(self, conversation_id, tenant_id, principal_id, now_ts):
        now_ts = int(now_ts)
        current = self.get_conversation(
            conversation_id, tenant_id, principal_id, now_ts
        )
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE concierge_conversations SET status = 'closed', state_json = ?,
                       presentation_json = NULL, closed_at = ?, updated_at = ?
                   WHERE conversation_id = ? AND tenant_id = ? AND principal_id = ?
                     AND status NOT IN ('closed', 'expired')""",
                (self._encode_conversation_content(
                    {}, tenant_id, conversation_id, "state"
                ), now_ts, now_ts, conversation_id, tenant_id, principal_id),
            )
        if cursor.rowcount != 1:
            return False
        self.append_conversation_outcome_event(
            conversation_id, tenant_id, principal_id,
            "rejected" if (current or {}).get("pending_draft") else "abandoned",
            now_ts, operation_family=(current or {}).get("operation"),
            metrics={"terminal_outcome": "closed_by_user"},
        )
        return True

    def purge_expired_conversation_content(self, now_ts):
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE concierge_conversations SET presentation_json = NULL
                   WHERE content_expires_at < ? AND presentation_json IS NOT NULL""",
                (int(now_ts),),
            )
        return cursor.rowcount

    def sync_conversation_workflow_outcome(self, revision_id, tenant_id,
                                           outcome, now_ts):
        """Project durable worker outcomes into the linked Concierge state."""
        with self._lock:
            row = self._connection.execute(
                """SELECT conversation_id, principal_id FROM concierge_conversations
                   WHERE workflow_revision_id = ? AND tenant_id = ?
                     AND status NOT IN ('closed', 'expired')""",
                (revision_id, tenant_id),
            ).fetchone()
        if row is None:
            return False
        status = outcome.get("status")
        mapped = {
            "complete": "succeeded",
            "retry_wait": "retryable_failure",
            "retryable_failure": "retryable_failure",
            "blocked_connection": "retryable_failure",
            "execution_unknown": "unknown_outcome",
            "paused_by_policy": "retryable_failure",
            "needs_replan": "retryable_failure",
        }.get(status)
        if mapped is None:
            return False
        changes = {"status": mapped}
        revision = self.get_revision_by_id(revision_id, tenant_id)
        effects = {step.get("effect") for step in (revision or {}).get("steps", [])}
        resolver_step = next((step for step in (revision or {}).get("steps", [])
                              if step.get("capability_id") in {
                                  "slack.channels.list", "slack.users.list"
                              }), None)
        current = self.get_conversation(
            row["conversation_id"], tenant_id, row["principal_id"], now_ts
        )
        resolution_request = (current or {}).get("resolution_request") or {}
        if status == "complete" and resolver_step and resolution_request:
            from agents.orchestrator.slack_conversation import normalize_name
            output = resolver_step.get("output") or {}
            field = resolution_request.get("field")
            key = "channels" if field == "channel" else "users"
            candidates = list(output.get(key) or [])
            wanted = normalize_name(resolution_request.get("query"))
            if field == "channel":
                matches = [item for item in candidates if (
                    normalize_name(item.get("name")) == wanted
                    and item.get("is_private") is not True
                )]
            else:
                matches = [item for item in candidates if wanted in {
                    normalize_name(item.get("display_name")),
                    normalize_name(item.get("real_name")),
                    normalize_name(item.get("handle")),
                }]
            resolver_run_id = resolution_request.get("resolver_run_id")
            page = self._record_slack_resolver_step_page(
                resolver_run_id, tenant_id, resolver_step, output,
                len(candidates), now_ts,
            )
            if len(matches) == 1:
                selected = matches[0]
                entity = ({"id": selected["id"], "name": selected["name"]}
                          if field == "channel" else {
                              key: selected[key] for key in (
                                  "id", "display_name", "real_name", "handle",
                                  "image_url",
                              ) if selected.get(key) is not None
                          })
                changes.update(status="resolving", blocking_need=None)
                changes["active_channel" if field == "channel" else "active_person"] = entity
                self._complete_slack_resolver_run_if_any(
                    resolver_run_id, tenant_id,
                    {"kind": "matched", "entity": entity}, now_ts,
                )
            elif not matches and page is not None and not page["exhausted"]:
                self.update_conversation(
                    row["conversation_id"], tenant_id, row["principal_id"],
                    {"status": "retrieving"}, now_ts,
                )
                return True
            else:
                safe_options = [{key: item[key] for key in (
                    "id", "name", "display_name", "real_name", "handle", "image_url"
                ) if item.get(key) is not None} for item in matches]
                locale = resolution_request.get("locale", "es")
                changes.update(status="needs_input", blocking_need={
                    "kind": "selection" if safe_options else "missing",
                    "field": field,
                    "question": (("¿Qué canal público de Slack?" if field == "channel"
                                  else "¿Qué persona de Slack?") if locale == "es" else
                                 ("Which public Slack channel?" if field == "channel"
                                  else "Which Slack person?")),
                    "options": safe_options,
                })
                self._complete_slack_resolver_run_if_any(
                    resolver_run_id, tenant_id,
                    {
                        "kind": "ambiguous" if safe_options else (
                            "exhausted" if page is not None
                            and page.get("budget_exhausted") else "not_found"
                        ),
                        "options": safe_options,
                    },
                    now_ts,
                )
            self.update_conversation(
                row["conversation_id"], tenant_id, row["principal_id"], changes, now_ts
            )
            return True
        if status == "complete" and effects == {"read"}:
            changes["status"] = "ready"
            outputs = [step.get("output") or {} for step in revision["steps"]]
            channels = next((list(item.get("channels") or []) for item in reversed(outputs)
                             if item.get("channels") is not None), None)
            if channels is not None:
                names = ["#%s" % item["name"] for item in channels
                         if isinstance(item, dict) and item.get("name")]
                current = self.get_conversation(
                    row["conversation_id"], tenant_id, row["principal_id"], now_ts
                )
                locale = (current or {}).get("locale", "es")
                private = (current or {}).get("operation") == "list_private_channels"
                kind_es = "privados" if private else "públicos"
                kind_en = "private" if private else "public"
                answer = ((("Tienes %d canales %s: " % (len(names), kind_es)) if locale == "es"
                           else "You have %d %s channels: " % (len(names), kind_en)) + ", ".join(names)
                          if names else
                          (("No encontré canales %s." % kind_es) if locale == "es"
                           else "I found no %s channels." % kind_en))
                self.store_conversation_presentation(
                    row["conversation_id"], tenant_id, row["principal_id"], {
                        "answer": answer, "citations": [], "partial": bool(
                            next((item.get("partial") for item in outputs
                                  if item.get("channels") is not None), False)
                        ),
                    }, now_ts,
                )
                self.update_conversation(
                    row["conversation_id"], tenant_id, row["principal_id"],
                    changes, now_ts,
                )
                return True
            read_step = next((step for step in reversed(revision["steps"])
                              if (step.get("output") or {}).get("messages")
                              is not None), None)
            evidence = (read_step or {}).get("output") or {}
            current = self.get_conversation(
                row["conversation_id"], tenant_id, row["principal_id"], now_ts
            )
            directory = next((
                (step.get("output") or {}).get("users")
                for step in revision["steps"]
                if (step.get("output") or {}).get("users") is not None
            ), None)
            step_input = (read_step or {}).get("input") or {}
            progress = self._accumulate_slack_read_page(
                current, evidence, step_input,
            )
            if progress["continues"]:
                # More pages remain inside budget: keep the turn retrieving so
                # the worker fetches the next one, and do not present a partial
                # answer as if it were the whole one.
                self.update_conversation(
                    row["conversation_id"], tenant_id, row["principal_id"],
                    {"status": "retrieving", "read_progress": progress["state"]},
                    now_ts,
                )
                return True
            changes["read_progress"] = None
            self.store_conversation_presentation(
                row["conversation_id"], tenant_id, row["principal_id"],
                self._present_slack_evidence(
                    {"messages": progress["messages"],
                     "next_cursor": progress["state"]["cursor"],
                     "partial": progress["budget_exhausted"]},
                    step_input, (current or {}).get("locale", "es"), directory,
                ), now_ts,
            )
        if status == "complete" and effects == {"write"}:
            changes["pending_draft"] = None
            current = self.get_conversation(
                row["conversation_id"], tenant_id, row["principal_id"], now_ts
            )
            locale = (current or {}).get("locale", "es")
            self.store_conversation_presentation(
                row["conversation_id"], tenant_id, row["principal_id"], {
                    "locale": locale,
                    "answer": "Mensaje enviado" if locale == "es" else "Message sent",
                    "citations": [], "partial": False,
                }, now_ts,
            )
        self.update_conversation(
            row["conversation_id"], tenant_id, row["principal_id"],
            changes, now_ts,
        )
        return True

    def append_outbox_event(
        self, tenant_id, aggregate_type, aggregate_id, event_type, payload,
        dedupe_key, now_ts, max_attempts=5, available_at=None,
    ):
        """Append one immutable event, assigning aggregate order atomically."""
        if not all((tenant_id, aggregate_type, aggregate_id, event_type, dedupe_key)):
            raise ValueError("outbox tenant, aggregate, event type and dedupe key are required")
        now_ts = int(now_ts)
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self._lock:
            owns_transaction = not self._connection.in_transaction
            try:
                if owns_transaction:
                    self._connection.execute("BEGIN IMMEDIATE")
                prior = self._connection.execute(
                    "SELECT * FROM workflow_outbox WHERE tenant_id = ? AND dedupe_key = ?",
                    (tenant_id, dedupe_key),
                ).fetchone()
                if prior is not None:
                    if (
                        prior["aggregate_type"] != aggregate_type
                        or prior["aggregate_id"] != aggregate_id
                        or prior["event_type"] != event_type
                        or prior["payload_json"] != payload_json
                    ):
                        raise ValueError("outbox dedupe key was reused for another event")
                    if owns_transaction:
                        self._connection.execute("COMMIT")
                    return self._outbox_event(prior)
                row = self._connection.execute(
                    "SELECT COALESCE(MAX(aggregate_version), 0) AS version "
                    "FROM workflow_outbox WHERE tenant_id = ? AND aggregate_type = ? "
                    "AND aggregate_id = ?",
                    (tenant_id, aggregate_type, aggregate_id),
                ).fetchone()
                version = int(row["version"]) + 1
                event_id = "outbox:%s" % uuid.uuid4().hex
                self._connection.execute(
                    """INSERT INTO workflow_outbox(
                        event_id, tenant_id, aggregate_type, aggregate_id,
                        aggregate_version, event_type, payload_json, dedupe_key,
                        max_attempts, available_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (event_id, tenant_id, aggregate_type, aggregate_id, version,
                     event_type, payload_json, dedupe_key, int(max_attempts),
                     int(now_ts if available_at is None else available_at), now_ts),
                )
                event = self._connection.execute(
                    "SELECT * FROM workflow_outbox WHERE event_id = ?", (event_id,)
                ).fetchone()
                if owns_transaction:
                    self._connection.execute("COMMIT")
            except Exception:
                if owns_transaction and self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        return self._outbox_event(event)

    @staticmethod
    def _outbox_event(row):
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    def get_outbox_event(self, event_id, tenant_id):
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM workflow_outbox WHERE event_id = ? AND tenant_id = ?",
                (event_id, tenant_id),
            ).fetchone()
        return self._outbox_event(row) if row else None

    def count_outbox_events(self, tenant_id, dedupe_key):
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) AS total FROM workflow_outbox "
                "WHERE tenant_id = ? AND dedupe_key = ?",
                (tenant_id, dedupe_key),
            ).fetchone()
        return int(row["total"])

    def claim_outbox_event(
        self, worker_id, now_ts, visibility_timeout=30, tenant_id=None,
    ):
        """Claim the oldest available event without overtaking its aggregate."""
        now_ts = int(now_ts)
        tenant_clause = " AND o.tenant_id = ?" if tenant_id else ""
        params = [now_ts, now_ts]
        if tenant_id:
            params.append(tenant_id)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    """SELECT o.* FROM workflow_outbox o
                       WHERE ((o.status = 'pending' AND o.available_at <= ?)
                          OR (o.status = 'claimed' AND o.claim_expires_at <= ?))
                    """ + tenant_clause + """
                       AND NOT EXISTS (
                           SELECT 1 FROM workflow_outbox earlier
                           WHERE earlier.tenant_id = o.tenant_id
                             AND earlier.aggregate_type = o.aggregate_type
                             AND earlier.aggregate_id = o.aggregate_id
                             AND earlier.aggregate_version < o.aggregate_version
                             AND earlier.status != 'completed'
                       )
                       ORDER BY o.created_at, o.event_id LIMIT 1""",
                    tuple(params),
                ).fetchone()
                if row is None:
                    self._connection.execute("COMMIT")
                    return None
                cursor = self._connection.execute(
                    """UPDATE workflow_outbox SET status = 'claimed', claimed_by = ?,
                           claim_expires_at = ?, attempts = attempts + 1
                       WHERE event_id = ? AND tenant_id = ?
                         AND ((status = 'pending' AND available_at <= ?)
                           OR (status = 'claimed' AND claim_expires_at <= ?))""",
                    (worker_id, now_ts + int(visibility_timeout), row["event_id"],
                     row["tenant_id"], now_ts, now_ts),
                )
                if cursor.rowcount != 1:
                    self._connection.execute("ROLLBACK")
                    return None
                claimed = self._connection.execute(
                    "SELECT * FROM workflow_outbox WHERE event_id = ?",
                    (row["event_id"],),
                ).fetchone()
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return self._outbox_event(claimed)

    def complete_outbox_event(self, event_id, tenant_id, worker_id, now_ts):
        with self._lock:
            current = self._connection.execute(
                "SELECT status, claimed_by FROM workflow_outbox "
                "WHERE event_id = ? AND tenant_id = ?", (event_id, tenant_id),
            ).fetchone()
            if current is None:
                return False
            if current["status"] == "completed":
                return True
            cursor = self._connection.execute(
                """UPDATE workflow_outbox SET status = 'completed', completed_at = ?,
                       claimed_by = NULL, claim_expires_at = NULL
                   WHERE event_id = ? AND tenant_id = ? AND status = 'claimed'
                     AND claimed_by = ?""",
                (int(now_ts), event_id, tenant_id, worker_id),
            )
        return cursor.rowcount == 1

    def fail_outbox_event(
        self, event_id, tenant_id, worker_id, now_ts, error, retry_delay,
    ):
        now_ts = int(now_ts)
        with self._lock:
            row = self._connection.execute(
                "SELECT attempts, max_attempts FROM workflow_outbox "
                "WHERE event_id = ? AND tenant_id = ? AND status = 'claimed' "
                "AND claimed_by = ?", (event_id, tenant_id, worker_id),
            ).fetchone()
            if row is None:
                return False
            dead = int(row["attempts"]) >= int(row["max_attempts"])
            status = "dead_letter" if dead else "pending"
            self._connection.execute(
                """UPDATE workflow_outbox SET status = ?, available_at = ?,
                       claimed_by = NULL, claim_expires_at = NULL, last_error = ?,
                       dead_lettered_at = ? WHERE event_id = ? AND tenant_id = ?""",
                (status, now_ts + int(retry_delay), str(error)[:1000],
                 now_ts if dead else None, event_id, tenant_id),
            )
        return "dead_letter" if dead else "retry"

    def get_projection_watermark(
        self, tenant_id, aggregate_type, aggregate_id,
        projection_name="conversation",
    ):
        with self._lock:
            row = self._connection.execute(
                """SELECT * FROM workflow_projection_watermarks
                   WHERE tenant_id = ? AND projection_name = ?
                     AND aggregate_type = ? AND aggregate_id = ?""",
                (tenant_id, projection_name, aggregate_type, aggregate_id),
            ).fetchone()
        return dict(row) if row else None

    def advance_projection_watermark(
        self, tenant_id, aggregate_type, aggregate_id, projected_version,
        event_id, now_ts, projection_name="conversation",
    ):
        with self._lock:
            cursor = self._connection.execute(
                """INSERT INTO workflow_projection_watermarks(
                       tenant_id, projection_name, aggregate_type, aggregate_id,
                       projected_version, last_event_id, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tenant_id, projection_name, aggregate_type, aggregate_id)
                   DO UPDATE SET projected_version = excluded.projected_version,
                       last_event_id = excluded.last_event_id,
                       updated_at = excluded.updated_at
                   WHERE workflow_projection_watermarks.projected_version
                         < excluded.projected_version""",
                (tenant_id, projection_name, aggregate_type, aggregate_id,
                 int(projected_version), event_id, int(now_ts)),
            )
        return cursor.rowcount == 1

    def purge_completed_outbox(self, tenant_id, completed_before):
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM workflow_outbox WHERE tenant_id = ? "
                "AND status = 'completed' AND completed_at < ?",
                (tenant_id, int(completed_before)),
            )
        return cursor.rowcount

    def enqueue_workflow_conversation_outcome(
        self, revision_id, tenant_id, outcome, now_ts,
    ):
        with self._lock:
            row = self._connection.execute(
                """SELECT conversation_id FROM concierge_conversations
                   WHERE workflow_revision_id = ? AND tenant_id = ?
                     AND status NOT IN ('closed', 'expired')""",
                (revision_id, tenant_id),
            ).fetchone()
        if row is None:
            return None
        status = str((outcome or {}).get("status") or "unknown")
        return self.append_outbox_event(
            tenant_id, "conversation", row["conversation_id"],
            "workflow.outcome", {"revision_id": revision_id, "outcome": outcome},
            "revision:%s:%s" % (revision_id, status), now_ts,
        )

    def recover_unprojected_conversation_outcomes(self, now_ts):
        """Self-heal a crash after durable completion but before outbox append."""
        with self._lock:
            rows = self._connection.execute(
                """SELECT c.workflow_revision_id, c.tenant_id
                   FROM concierge_conversations c
                   JOIN workflow_revisions r
                     ON r.workflow_revision_id = c.workflow_revision_id
                    AND r.tenant_id = c.tenant_id
                   WHERE c.status NOT IN ('closed', 'expired', 'succeeded', 'ready')
                     AND r.status = 'completed'"""
            ).fetchall()
        created = 0
        for row in rows:
            event = self.enqueue_workflow_conversation_outcome(
                row["workflow_revision_id"], row["tenant_id"],
                {"status": "complete"}, now_ts,
            )
            if event is not None:
                created += 1
        return created

    def get_revision_by_id(self, revision_id, tenant_id):
        with self._lock:
            row = self._connection.execute(
                """SELECT workflow_run_id FROM workflow_revisions
                   WHERE workflow_revision_id = ? AND tenant_id = ?""",
                (revision_id, tenant_id),
            ).fetchone()
        return self.get_revision(row["workflow_run_id"], revision_id, tenant_id) if row else None

    def close(self):
        with self._lock:
            self._connection.close()
