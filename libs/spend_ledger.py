"""Atomic worst-case spend reservation and actual-cost settlement."""

from decimal import Decimal, ROUND_UP
import sqlite3
import threading
import time
from datetime import datetime, timezone


class SpendCeilingExceeded(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class SpendLedger:
    def __init__(self, database_path, clock=None):
        self.clock = clock or time.time
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            database_path, check_same_thread=False, isolation_level=None,
            timeout=10,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript("""
            pragma journal_mode=WAL;
            create table if not exists spend_budgets(
                tenant_id text not null, budget_kind text not null,
                budget_id text not null, ceiling_micros integer not null,
                reserved_micros integer not null default 0,
                settled_micros integer not null default 0,
                primary key(tenant_id,budget_kind,budget_id)
            );
            create table if not exists spend_reservations(
                tenant_id text not null, reservation_id text not null,
                campaign_id text, channel text not null,
                reserved_micros integer not null, settled_micros integer,
                status text not null check(status in ('reserved','settled','released')),
                created_at integer not null, updated_at integer not null,
                primary key(tenant_id,reservation_id)
            );
            create table if not exists brand_daily_volume(
                tenant_id text not null,brand_id text not null,day text not null,
                volume integer not null default 0,ceiling integer not null,
                primary key(tenant_id,brand_id,day)
            );
        """)

    def set_ceiling(self, tenant_id, kind, budget_id, amount):
        micros = _micros(amount)
        self._connection.execute(
            """insert into spend_budgets(tenant_id,budget_kind,budget_id,ceiling_micros)
               values(?,?,?,?) on conflict(tenant_id,budget_kind,budget_id)
               do update set ceiling_micros=excluded.ceiling_micros""",
            (tenant_id, kind, budget_id, micros),
        )

    def reserve(self, tenant_id, reservation_id, channel, estimate,
                campaign_id=None):
        amount = _micros(estimate)
        now = int(self.clock())
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                prior = self._connection.execute(
                    "select * from spend_reservations where tenant_id=? and reservation_id=?",
                    (tenant_id, reservation_id),
                ).fetchone()
                if prior:
                    if prior["reserved_micros"] != amount:
                        raise ValueError("reservation id is bound to another estimate")
                    self._connection.execute("COMMIT")
                    return _reservation(prior)
                budgets = [("account", tenant_id)]
                if campaign_id:
                    budgets.append(("campaign", campaign_id))
                for kind, budget_id in budgets:
                    row = self._connection.execute(
                        """select * from spend_budgets where tenant_id=?
                           and budget_kind=? and budget_id=?""",
                        (tenant_id, kind, budget_id),
                    ).fetchone()
                    if row is None:
                        raise SpendCeilingExceeded("%s_budget_unavailable" % kind)
                    available = row["ceiling_micros"] - row["reserved_micros"] - row["settled_micros"]
                    if amount > available:
                        raise SpendCeilingExceeded("%s_ceiling_exhausted" % kind)
                for kind, budget_id in budgets:
                    self._connection.execute(
                        """update spend_budgets set reserved_micros=reserved_micros+?
                           where tenant_id=? and budget_kind=? and budget_id=?""",
                        (amount, tenant_id, kind, budget_id),
                    )
                self._connection.execute(
                    """insert into spend_reservations(
                        tenant_id,reservation_id,campaign_id,channel,
                        reserved_micros,status,created_at,updated_at
                    ) values(?,?,?,?,?,'reserved',?,?)""",
                    (tenant_id, reservation_id, campaign_id, channel, amount, now, now),
                )
                self._connection.execute("COMMIT")
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        return self.get(tenant_id, reservation_id)

    def settle(self, tenant_id, reservation_id, actual):
        actual_micros = _micros(actual)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    "select * from spend_reservations where tenant_id=? and reservation_id=?",
                    (tenant_id, reservation_id),
                ).fetchone()
                if row is None:
                    raise LookupError("reservation not found")
                if row["status"] == "settled":
                    self._connection.execute("COMMIT")
                    return _reservation(row)
                if row["status"] != "reserved":
                    raise ValueError("released reservation cannot settle")
                budgets = [("account", tenant_id)]
                if row["campaign_id"]:
                    budgets.append(("campaign", row["campaign_id"]))
                for kind, budget_id in budgets:
                    self._connection.execute(
                        """update spend_budgets set
                            reserved_micros=reserved_micros-?,
                            settled_micros=settled_micros+?
                           where tenant_id=? and budget_kind=? and budget_id=?""",
                        (row["reserved_micros"], actual_micros,
                         tenant_id, kind, budget_id),
                    )
                self._connection.execute(
                    """update spend_reservations set status='settled',
                       settled_micros=?,updated_at=? where tenant_id=? and reservation_id=?""",
                    (actual_micros, int(self.clock()), tenant_id, reservation_id),
                )
                self._connection.execute("COMMIT")
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
        return self.get(tenant_id, reservation_id)

    def release(self, tenant_id, reservation_id):
        with self._lock:
            row = self._connection.execute(
                "select * from spend_reservations where tenant_id=? and reservation_id=?",
                (tenant_id, reservation_id),
            ).fetchone()
            if row is None or row["status"] != "reserved":
                return False
            budgets = [("account", tenant_id)]
            if row["campaign_id"]:
                budgets.append(("campaign", row["campaign_id"]))
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                for kind, budget_id in budgets:
                    self._connection.execute(
                        "update spend_budgets set reserved_micros=reserved_micros-? "
                        "where tenant_id=? and budget_kind=? and budget_id=?",
                        (row["reserved_micros"], tenant_id, kind, budget_id),
                    )
                self._connection.execute(
                    "update spend_reservations set status='released',updated_at=? "
                    "where tenant_id=? and reservation_id=?",
                    (int(self.clock()), tenant_id, reservation_id),
                )
                self._connection.execute("COMMIT")
                return True
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def get(self, tenant_id, reservation_id):
        row = self._connection.execute(
            "select * from spend_reservations where tenant_id=? and reservation_id=?",
            (tenant_id, reservation_id),
        ).fetchone()
        return _reservation(row) if row else None

    def budget(self, tenant_id, kind, budget_id):
        row = self._connection.execute(
            "select * from spend_budgets where tenant_id=? and budget_kind=? and budget_id=?",
            (tenant_id, kind, budget_id),
        ).fetchone()
        return dict(row) if row else None

    def meter_brand_volume(self, tenant_id, brand_id, day, ceiling, units=1):
        """Atomically consume locally-metered A2P daily brand volume."""
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    "select volume,ceiling from brand_daily_volume where tenant_id=? and brand_id=? and day=?",
                    (tenant_id, brand_id, day),
                ).fetchone()
                current = row["volume"] if row else 0
                effective_ceiling = min(int(ceiling), row["ceiling"]) if row else int(ceiling)
                if current + int(units) > effective_ceiling:
                    raise SpendCeilingExceeded("brand_daily_volume_exhausted")
                self._connection.execute(
                    """insert into brand_daily_volume(tenant_id,brand_id,day,volume,ceiling)
                       values(?,?,?,?,?) on conflict(tenant_id,brand_id,day)
                       do update set volume=excluded.volume,ceiling=excluded.ceiling""",
                    (tenant_id, brand_id, day, current + int(units), effective_ceiling),
                )
                self._connection.execute("COMMIT")
                return current + int(units)
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise


class PostgresSpendLedger:
    """Shared spend authority with row-locked budget invariants."""

    def __init__(self, db, clock=None):
        self.db = db
        self.clock = clock or time.time

    def set_ceiling(self, tenant_id, kind, budget_id, amount):
        with self.db.transaction() as conn:
            conn.execute(
                """
                insert into billing.spend_budgets(
                    tenant_id, budget_kind, budget_id, ceiling_micros, updated_at
                ) values (%s, %s, %s, %s, %s)
                on conflict (tenant_id, budget_kind, budget_id)
                do update set ceiling_micros = excluded.ceiling_micros,
                              updated_at = excluded.updated_at
                """,
                (tenant_id, kind, budget_id, _micros(amount),
                 _utc(self.clock())),
            )

    def reserve(
        self, tenant_id, reservation_id, channel, estimate,
        campaign_id=None,
    ):
        amount = _micros(estimate)
        with self.db.transaction() as conn:
            prior = conn.execute(
                """
                select * from billing.spend_reservations
                where tenant_id = %s and reservation_id = %s
                """,
                (tenant_id, reservation_id),
            ).fetchone()
            if prior is not None:
                if prior[5] != amount:
                    raise ValueError("reservation id is bound to another estimate")
                return _pg_reservation(prior)
            budgets = [("account", tenant_id)]
            if campaign_id:
                budgets.append(("campaign", campaign_id))
            locked = {}
            for kind, budget_id in sorted(budgets):
                row = conn.execute(
                    """
                    select ceiling_micros, reserved_micros, settled_micros
                    from billing.spend_budgets
                    where tenant_id = %s and budget_kind = %s and budget_id = %s
                    for update
                    """,
                    (tenant_id, kind, budget_id),
                ).fetchone()
                if row is None:
                    raise SpendCeilingExceeded("%s_budget_unavailable" % kind)
                locked[(kind, budget_id)] = row
            for kind, budget_id in budgets:
                ceiling, reserved, settled = locked[(kind, budget_id)]
                if amount > int(ceiling) - int(reserved) - int(settled):
                    raise SpendCeilingExceeded("%s_ceiling_exhausted" % kind)
            for kind, budget_id in budgets:
                conn.execute(
                    """
                    update billing.spend_budgets
                    set reserved_micros = reserved_micros + %s, updated_at = %s
                    where tenant_id = %s and budget_kind = %s and budget_id = %s
                    """,
                    (amount, _utc(self.clock()), tenant_id, kind, budget_id),
                )
            now = _utc(self.clock())
            row = conn.execute(
                """
                insert into billing.spend_reservations(
                    tenant_id, reservation_id, campaign_id, effect_id, channel,
                    reserved_micros, status, created_at, updated_at
                ) values (%s, %s, %s, %s, %s, %s, 'reserved', %s, %s)
                returning *
                """,
                (tenant_id, reservation_id, campaign_id, reservation_id,
                 channel, amount, now, now),
            ).fetchone()
        return _pg_reservation(row)

    def settle(self, tenant_id, reservation_id, actual):
        actual_micros = _micros(actual)
        with self.db.transaction() as conn:
            row = conn.execute(
                """
                select * from billing.spend_reservations
                where tenant_id = %s and reservation_id = %s for update
                """,
                (tenant_id, reservation_id),
            ).fetchone()
            if row is None:
                raise LookupError("reservation not found")
            record = _pg_reservation(row)
            if record["status"] == "settled":
                return record
            if record["status"] != "reserved":
                raise ValueError("released reservation cannot settle")
            budgets = [("account", tenant_id)]
            if record["campaign_id"]:
                budgets.append(("campaign", record["campaign_id"]))
            for kind, budget_id in sorted(budgets):
                conn.execute(
                    """
                    select 1 from billing.spend_budgets
                    where tenant_id = %s and budget_kind = %s and budget_id = %s
                    for update
                    """,
                    (tenant_id, kind, budget_id),
                )
            for kind, budget_id in budgets:
                conn.execute(
                    """
                    update billing.spend_budgets
                    set reserved_micros = reserved_micros - %s,
                        settled_micros = settled_micros + %s, updated_at = %s
                    where tenant_id = %s and budget_kind = %s and budget_id = %s
                    """,
                    (record["reserved_micros"], actual_micros,
                     _utc(self.clock()), tenant_id, kind, budget_id),
                )
            row = conn.execute(
                """
                update billing.spend_reservations
                set status = 'settled', settled_micros = %s, updated_at = %s
                where tenant_id = %s and reservation_id = %s returning *
                """,
                (actual_micros, _utc(self.clock()), tenant_id, reservation_id),
            ).fetchone()
        return _pg_reservation(row)

    def release(self, tenant_id, reservation_id):
        with self.db.transaction() as conn:
            row = conn.execute(
                """
                select * from billing.spend_reservations
                where tenant_id = %s and reservation_id = %s for update
                """,
                (tenant_id, reservation_id),
            ).fetchone()
            if row is None or _pg_reservation(row)["status"] != "reserved":
                return False
            record = _pg_reservation(row)
            budgets = [("account", tenant_id)]
            if record["campaign_id"]:
                budgets.append(("campaign", record["campaign_id"]))
            for kind, budget_id in sorted(budgets):
                conn.execute(
                    """
                    select 1 from billing.spend_budgets
                    where tenant_id = %s and budget_kind = %s and budget_id = %s
                    for update
                    """,
                    (tenant_id, kind, budget_id),
                )
            for kind, budget_id in budgets:
                conn.execute(
                    """
                    update billing.spend_budgets
                    set reserved_micros = reserved_micros - %s, updated_at = %s
                    where tenant_id = %s and budget_kind = %s and budget_id = %s
                    """,
                    (record["reserved_micros"], _utc(self.clock()), tenant_id,
                     kind, budget_id),
                )
            conn.execute(
                """
                update billing.spend_reservations
                set status = 'released', updated_at = %s
                where tenant_id = %s and reservation_id = %s
                """,
                (_utc(self.clock()), tenant_id, reservation_id),
            )
        return True

    def get(self, tenant_id, reservation_id):
        with self.db.connection() as conn:
            row = conn.execute(
                """
                select * from billing.spend_reservations
                where tenant_id = %s and reservation_id = %s
                """,
                (tenant_id, reservation_id),
            ).fetchone()
        return _pg_reservation(row) if row else None

    def budget(self, tenant_id, kind, budget_id):
        with self.db.connection() as conn:
            row = conn.execute(
                """
                select * from billing.spend_budgets
                where tenant_id = %s and budget_kind = %s and budget_id = %s
                """,
                (tenant_id, kind, budget_id),
            ).fetchone()
        return _row_dict(row) if row else None

    def meter_brand_volume(self, tenant_id, brand_id, day, ceiling, units=1):
        with self.db.transaction() as conn:
            row = conn.execute(
                """
                select volume, ceiling from billing.brand_daily_volume
                where tenant_id = %s and brand_id = %s and day = %s for update
                """,
                (tenant_id, brand_id, day),
            ).fetchone()
            current = int(row[0]) if row else 0
            effective = min(int(ceiling), int(row[1])) if row else int(ceiling)
            if current + int(units) > effective:
                raise SpendCeilingExceeded("brand_daily_volume_exhausted")
            value = current + int(units)
            conn.execute(
                """
                insert into billing.brand_daily_volume(
                    tenant_id, brand_id, day, volume, ceiling
                ) values (%s, %s, %s, %s, %s)
                on conflict (tenant_id, brand_id, day)
                do update set volume = excluded.volume, ceiling = excluded.ceiling
                """,
                (tenant_id, brand_id, day, value, effective),
            )
        return value


def estimate_sms_cost(body, per_segment):
    gsm = all(ord(character) < 128 for character in body)
    single, multipart = (160, 153) if gsm else (70, 67)
    length = len(body)
    segments = 1 if length <= single else (length + multipart - 1) // multipart
    return Decimal(str(per_segment)) * segments


def estimate_voice_cost(max_duration_seconds, per_minute):
    minutes = (Decimal(max_duration_seconds) / Decimal(60)).quantize(
        Decimal("1"), rounding=ROUND_UP
    )
    return minutes * Decimal(str(per_minute))


def _micros(amount):
    return int((Decimal(str(amount)) * Decimal(1_000_000)).quantize(Decimal("1")))


def _reservation(row):
    value = dict(row)
    value["reserved"] = Decimal(value["reserved_micros"]) / Decimal(1_000_000)
    value["settled"] = (
        Decimal(value["settled_micros"]) / Decimal(1_000_000)
        if value["settled_micros"] is not None else None
    )
    return value


def _utc(value):
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def _row_dict(row):
    keys = (
        "tenant_id", "budget_kind", "budget_id", "currency",
        "ceiling_micros", "reserved_micros", "settled_micros", "updated_at",
    )
    return dict(zip(keys, row))


def _pg_reservation(row):
    keys = (
        "tenant_id", "reservation_id", "campaign_id", "effect_id", "channel",
        "reserved_micros", "settled_micros", "status", "created_at", "updated_at",
    )
    value = dict(zip(keys, row))
    value["reserved"] = Decimal(value["reserved_micros"]) / Decimal(1_000_000)
    value["settled"] = (
        Decimal(value["settled_micros"]) / Decimal(1_000_000)
        if value["settled_micros"] is not None else None
    )
    return value
