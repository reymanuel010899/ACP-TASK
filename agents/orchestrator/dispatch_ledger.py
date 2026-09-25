"""ACP-TASK-owned write-ahead ledger for provider effects without idempotency."""

import hashlib
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone

from libs.connectors.base import ProviderNetworkError


class DuplicateDispatch(RuntimeError):
    pass


class AmbiguousDispatch(RuntimeError):
    pass


class DispatchLedger:
    def __init__(self, database_path, clock=None):
        self.clock = clock or time.time
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            database_path, check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript("""
            pragma journal_mode=WAL;
            create table if not exists provider_dispatch_ledger (
                tenant_id text not null,
                dispatch_key text not null,
                effect_id text not null,
                payload_hash text not null,
                callback_token text not null,
                status text not null check(status in (
                    'intent_recorded','dispatching','retryable','accepted',
                    'ambiguous','rejected'
                )),
                provider_id text,
                provider_status text,
                attempt_count integer not null default 0,
                created_at integer not null,
                updated_at integer not null,
                primary key(tenant_id, dispatch_key),
                unique(tenant_id, effect_id)
            );
        """)

    def dispatch(self, tenant_id, dispatch_key, effect_id, payload,
                 callback_token, provider_call):
        payload_hash = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()).hexdigest()
        now = int(self.clock())
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    "select * from provider_dispatch_ledger where tenant_id=? and dispatch_key=?",
                    (tenant_id, dispatch_key),
                ).fetchone()
                if row is None:
                    self._connection.execute(
                        """insert into provider_dispatch_ledger(
                            tenant_id,dispatch_key,effect_id,payload_hash,
                            callback_token,status,created_at,updated_at
                        ) values(?,?,?,?,?,'intent_recorded',?,?)""",
                        (tenant_id, dispatch_key, effect_id, payload_hash,
                         callback_token, now, now),
                    )
                else:
                    if row["payload_hash"] != payload_hash or row["effect_id"] != effect_id:
                        raise DuplicateDispatch("dispatch key is bound to different intent")
                    if row["status"] == "ambiguous":
                        raise AmbiguousDispatch("provider outcome requires reconciliation")
                    if row["status"] in (
                        "accepted", "dispatching", "intent_recorded", "rejected"
                    ):
                        raise DuplicateDispatch("dispatch already attempted")
                # ``intent_recorded`` is itself the exclusive claim. A second
                # worker observes it and refuses while the first is across the
                # network boundary. Only a documented-safe rate limit changes
                # it to retryable.
                self._connection.execute(
                    "update provider_dispatch_ledger set "
                    "attempt_count=attempt_count+1,updated_at=? "
                    "where tenant_id=? and dispatch_key=?",
                    (now, tenant_id, dispatch_key),
                )
                # Commit the intent before crossing the provider boundary.
                self._connection.execute("COMMIT")
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

        # Deliberately outside ``_lock``: other workers must be able to read
        # the committed claim and refuse instead of waiting, then starting a
        # second provider call after this one finishes.
        try:
            result = provider_call(self.get(tenant_id, dispatch_key))
        except Exception as exc:
            with self._lock:
                if isinstance(exc, (TimeoutError, ProviderNetworkError)):
                    status = "ambiguous"
                elif getattr(exc, "category", None) == "rate_limit":
                    status = "retryable"
                else:
                    status = "rejected"
                self._connection.execute(
                    "update provider_dispatch_ledger set status=?,updated_at=? "
                    "where tenant_id=? and dispatch_key=?",
                    (status, int(self.clock()), tenant_id, dispatch_key),
                )
            if status == "ambiguous":
                raise AmbiguousDispatch(
                    "provider outcome requires reconciliation"
                ) from exc
            raise
        if not isinstance(result, dict) or not result.get("provider_id"):
            with self._lock:
                self._connection.execute(
                    "update provider_dispatch_ledger set status='ambiguous',updated_at=? "
                    "where tenant_id=? and dispatch_key=?",
                    (int(self.clock()), tenant_id, dispatch_key),
                )
            raise AmbiguousDispatch("provider returned no durable identifier")
        with self._lock:
            self._connection.execute(
                """update provider_dispatch_ledger set status='accepted',
                    provider_id=?,provider_status=?,updated_at=?
                   where tenant_id=? and dispatch_key=?""",
                (result["provider_id"], result.get("status"), int(self.clock()),
                 tenant_id, dispatch_key),
            )
        return result

    def get(self, tenant_id, dispatch_key):
        row = self._connection.execute(
            "select * from provider_dispatch_ledger where tenant_id=? and dispatch_key=?",
            (tenant_id, dispatch_key),
        ).fetchone()
        return dict(row) if row else None

    def reconcile(self, tenant_id, dispatch_key, provider_id, status):
        with self._lock:
            row = self.get(tenant_id, dispatch_key)
            if row is None or row["status"] != "ambiguous":
                return False
            self._connection.execute(
                """update provider_dispatch_ledger set status='accepted',
                    provider_id=?,provider_status=?,updated_at=?
                   where tenant_id=? and dispatch_key=?""",
                (provider_id, status, int(self.clock()), tenant_id, dispatch_key),
            )
            return True


class PostgresDispatchLedger:
    """Shared write-ahead dispatch ledger with one database claim."""

    def __init__(self, db, clock=None):
        self.db = db
        self.clock = clock or time.time

    def dispatch(self, tenant_id, dispatch_key, effect_id, payload,
                 callback_token, provider_call):
        payload_hash = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False,
        ).encode()).hexdigest()
        now = _utc(self.clock())
        with self.db.transaction() as conn:
            inserted = conn.execute(
                """
                insert into orchestrator.dispatch_records(
                    tenant_id, dispatch_key, effect_id, payload_hash,
                    callback_token, status, created_at, updated_at
                ) values (%s, %s, %s, %s, %s, 'intent_recorded', %s, %s)
                on conflict (tenant_id, dispatch_key) do nothing
                returning dispatch_key
                """,
                (tenant_id, dispatch_key, effect_id, payload_hash,
                 callback_token, now, now),
            ).fetchone()
            row = conn.execute(
                """
                select tenant_id, dispatch_key, effect_id, payload_hash,
                       callback_token, status, provider_id, provider_status,
                       attempt_count, created_at, updated_at
                from orchestrator.dispatch_records
                where tenant_id = %s and dispatch_key = %s
                for update
                """,
                (tenant_id, dispatch_key),
            ).fetchone()
            record = _pg_dispatch_record(row)
            if inserted is None:
                if (record["payload_hash"] != payload_hash
                        or record["effect_id"] != effect_id):
                    raise DuplicateDispatch(
                        "dispatch key is bound to different intent"
                    )
                if record["status"] == "ambiguous":
                    raise AmbiguousDispatch(
                        "provider outcome requires reconciliation"
                    )
                if record["status"] in (
                    "accepted", "dispatching", "intent_recorded", "rejected"
                ):
                    raise DuplicateDispatch("dispatch already attempted")
            conn.execute(
                """
                update orchestrator.dispatch_records
                set attempt_count = attempt_count + 1, updated_at = %s
                where tenant_id = %s and dispatch_key = %s
                """,
                (now, tenant_id, dispatch_key),
            )

        try:
            result = provider_call(self.get(tenant_id, dispatch_key))
        except Exception as exc:
            if isinstance(exc, (TimeoutError, ProviderNetworkError)):
                status = "ambiguous"
            elif getattr(exc, "category", None) == "rate_limit":
                status = "retryable"
            else:
                status = "rejected"
            self._set_status(tenant_id, dispatch_key, status)
            if status == "ambiguous":
                raise AmbiguousDispatch(
                    "provider outcome requires reconciliation"
                ) from exc
            raise
        if not isinstance(result, dict) or not result.get("provider_id"):
            self._set_status(tenant_id, dispatch_key, "ambiguous")
            raise AmbiguousDispatch("provider returned no durable identifier")
        with self.db.transaction() as conn:
            conn.execute(
                """
                update orchestrator.dispatch_records
                set status = 'accepted', provider_id = %s,
                    provider_status = %s, updated_at = %s
                where tenant_id = %s and dispatch_key = %s
                """,
                (result["provider_id"], result.get("status"),
                 _utc(self.clock()), tenant_id, dispatch_key),
            )
        return result

    def get(self, tenant_id, dispatch_key):
        with self.db.connection() as conn:
            row = conn.execute(
                """
                select tenant_id, dispatch_key, effect_id, payload_hash,
                       callback_token, status, provider_id, provider_status,
                       attempt_count, created_at, updated_at
                from orchestrator.dispatch_records
                where tenant_id = %s and dispatch_key = %s
                """,
                (tenant_id, dispatch_key),
            ).fetchone()
        return _pg_dispatch_record(row)

    def reconcile(self, tenant_id, dispatch_key, provider_id, status):
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                update orchestrator.dispatch_records
                set status = 'accepted', provider_id = %s,
                    provider_status = %s, updated_at = %s
                where tenant_id = %s and dispatch_key = %s
                  and status = 'ambiguous'
                """,
                (provider_id, status, _utc(self.clock()), tenant_id,
                 dispatch_key),
            )
        return cursor.rowcount == 1

    def _set_status(self, tenant_id, dispatch_key, status):
        with self.db.transaction() as conn:
            conn.execute(
                """
                update orchestrator.dispatch_records
                set status = %s, updated_at = %s
                where tenant_id = %s and dispatch_key = %s
                """,
                (status, _utc(self.clock()), tenant_id, dispatch_key),
            )


def _pg_dispatch_record(row):
    if row is None:
        return None
    keys = (
        "tenant_id", "dispatch_key", "effect_id", "payload_hash",
        "callback_token", "status", "provider_id", "provider_status",
        "attempt_count", "created_at", "updated_at",
    )
    result = dict(zip(keys, row))
    for key in ("created_at", "updated_at"):
        result[key] = int(result[key].timestamp())
    return result


def _utc(value):
    return datetime.fromtimestamp(int(value), tz=timezone.utc)
