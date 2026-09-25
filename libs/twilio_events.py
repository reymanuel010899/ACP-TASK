"""Idempotent Twilio provider-event ledger and non-regressing verdicts."""

import json
import sqlite3
import threading
import time


STATUS_RANK = {
    "accepted": 10, "queued": 20, "sending": 30, "sent": 40,
    "ringing": 40, "delivered": 100, "read": 110,
    "undelivered": 100, "failed": 100, "canceled": 100,
    "completed": 100, "busy": 100, "no-answer": 100,
}
TERMINAL = frozenset({
    "delivered", "read", "undelivered", "failed", "canceled",
    "completed", "busy", "no-answer",
})


class TwilioEventRepository:
    def __init__(self, database_path, clock=None):
        self.clock = clock or time.time
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            database_path, check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript("""
            pragma journal_mode=WAL;
            create table if not exists twilio_provider_events (
                tenant_id text not null,
                event_key text not null,
                effect_id text,
                provider_id text,
                identity_address text not null,
                event_type text not null,
                status text,
                payload_json text not null,
                authenticated integer not null,
                received_at integer not null,
                primary key (tenant_id, event_key)
            );
            create table if not exists twilio_effect_verdicts (
                tenant_id text not null,
                effect_id text not null,
                provider_id text,
                status text not null,
                rank integer not null,
                terminal integer not null,
                updated_at integer not null,
                primary key (tenant_id, effect_id)
            );
        """)

    def record(self, tenant_id, event_key, effect_id, identity_address,
               event_type, payload, provider_id=None, status=None):
        now = int(self.clock())
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                cursor = self._connection.execute(
                    """insert or ignore into twilio_provider_events(
                        tenant_id,event_key,effect_id,provider_id,identity_address,
                        event_type,status,payload_json,authenticated,received_at
                    ) values(?,?,?,?,?,?,?,?,1,?)""",
                    (tenant_id, event_key, effect_id, provider_id,
                     identity_address, event_type, status,
                     json.dumps(payload, sort_keys=True, separators=(",", ":")), now),
                )
                inserted = cursor.rowcount == 1
                if inserted and effect_id and status:
                    self._advance_verdict(
                        tenant_id, effect_id, provider_id, status, now
                    )
                self._connection.execute("COMMIT")
                return inserted
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def _advance_verdict(self, tenant_id, effect_id, provider_id, status, now):
        rank = STATUS_RANK.get(status, 0)
        current = self._connection.execute(
            "select status,rank,terminal from twilio_effect_verdicts "
            "where tenant_id=? and effect_id=?", (tenant_id, effect_id)
        ).fetchone()
        if current is not None:
            if current["terminal"]:
                # Read may legitimately follow delivered; conflicting terminal
                # states never overwrite the first authenticated final fact.
                if current["status"] == "delivered" and status == "read":
                    pass
                else:
                    return
            elif rank < current["rank"]:
                return
        self._connection.execute(
            """insert into twilio_effect_verdicts(
                tenant_id,effect_id,provider_id,status,rank,terminal,updated_at
            ) values(?,?,?,?,?,?,?) on conflict(tenant_id,effect_id) do update set
                provider_id=excluded.provider_id,status=excluded.status,
                rank=excluded.rank,terminal=excluded.terminal,
                updated_at=excluded.updated_at""",
            (tenant_id, effect_id, provider_id, status, rank,
             1 if status in TERMINAL else 0, now),
        )

    def verdict(self, tenant_id, effect_id):
        row = self._connection.execute(
            "select * from twilio_effect_verdicts where tenant_id=? and effect_id=?",
            (tenant_id, effect_id),
        ).fetchone()
        return dict(row) if row else None

    def event_count(self, tenant_id):
        return self._connection.execute(
            "select count(*) from twilio_provider_events where tenant_id=?",
            (tenant_id,),
        ).fetchone()[0]
