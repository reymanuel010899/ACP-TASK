"""WhatsApp customer-service windows and approved-template registry."""

import sqlite3
import threading
import time


WINDOW_SECONDS = 24 * 60 * 60
AVAILABLE_TEMPLATE_STATES = frozenset({"approved"})


class WhatsAppStateRepository:
    def __init__(self, database_path, clock=None):
        self.clock = clock or time.time
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            database_path, check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript("""
            pragma journal_mode=WAL;
            create table if not exists whatsapp_session_windows(
                tenant_id text not null,address_id text not null,sender_id text not null,
                opened_at integer not null,expires_at integer not null,
                source_event_key text not null,updated_at integer not null,
                primary key(tenant_id,address_id,sender_id)
            );
            create table if not exists whatsapp_templates(
                tenant_id text not null,content_sid text not null,sender_id text not null,
                name text not null,language text not null,category text not null,
                status text not null,quality text,variables_json text not null,
                updated_at integer not null,
                primary key(tenant_id,content_sid,sender_id)
            );
        """)

    def open_window(self, tenant_id, address_id, sender_id, source_event_key,
                    received_at=None):
        opened = int(received_at if received_at is not None else self.clock())
        expires = opened + WINDOW_SECONDS
        with self._lock:
            self._connection.execute(
                """insert into whatsapp_session_windows(
                    tenant_id,address_id,sender_id,opened_at,expires_at,
                    source_event_key,updated_at
                ) values(?,?,?,?,?,?,?) on conflict(tenant_id,address_id,sender_id)
                do update set opened_at=max(opened_at,excluded.opened_at),
                    expires_at=max(expires_at,excluded.expires_at),
                    source_event_key=case when excluded.opened_at>=opened_at
                        then excluded.source_event_key else source_event_key end,
                    updated_at=excluded.updated_at""",
                (tenant_id, address_id, sender_id, opened, expires,
                 source_event_key, int(self.clock())),
            )
        return self.window(tenant_id, address_id, sender_id)

    def window(self, tenant_id, address_id, sender_id):
        row = self._connection.execute(
            """select * from whatsapp_session_windows where tenant_id=?
               and address_id=? and sender_id=?""",
            (tenant_id, address_id, sender_id),
        ).fetchone()
        value = dict(row) if row else None
        if value:
            value["open"] = value["expires_at"] > int(self.clock())
        return value

    def register_template(self, tenant_id, content_sid, sender_id, name,
                          language, category, status, variables=(), quality=None):
        import json
        if category not in ("marketing", "utility", "authentication"):
            raise ValueError("unsupported WhatsApp template category")
        self._connection.execute(
            """insert into whatsapp_templates(
                tenant_id,content_sid,sender_id,name,language,category,status,
                quality,variables_json,updated_at
            ) values(?,?,?,?,?,?,?,?,?,?) on conflict(tenant_id,content_sid,sender_id)
            do update set name=excluded.name,language=excluded.language,
                category=excluded.category,status=excluded.status,
                quality=excluded.quality,variables_json=excluded.variables_json,
                updated_at=excluded.updated_at""",
            (tenant_id, content_sid, sender_id, name, language, category,
             status, quality, json.dumps(sorted(variables)), int(self.clock())),
        )

    def template(self, tenant_id, content_sid, sender_id):
        row = self._connection.execute(
            """select * from whatsapp_templates where tenant_id=?
               and content_sid=? and sender_id=?""",
            (tenant_id, content_sid, sender_id),
        ).fetchone()
        value = dict(row) if row else None
        if value:
            value["available"] = value["status"] in AVAILABLE_TEMPLATE_STATES
        return value
