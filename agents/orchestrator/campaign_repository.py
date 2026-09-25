"""Tenant-bound campaign envelopes, fixed cohorts, and truthful outcomes."""

import hashlib
import json
import sqlite3
import threading
import time


class CampaignError(RuntimeError):
    pass


class CampaignPermissionDenied(CampaignError):
    pass


class CampaignEnvelopeChanged(CampaignError):
    pass


class CampaignStateConflict(CampaignError):
    pass


TERMINAL_EFFECT_STATES = frozenset({
    "completed", "prevented", "uncertain", "never_eligible", "cancelled",
})


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


class CampaignRepository:
    """SQLite operational model mirroring the forced-RLS production schema."""

    def __init__(self, database_path, clock=None):
        self.clock = clock or time.time
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            database_path, check_same_thread=False, isolation_level=None, timeout=10,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript("""
            pragma journal_mode=WAL;
            create table if not exists campaigns(
                tenant_id text not null, campaign_id text not null,
                created_by text not null, authorized_by text,
                definition_json text not null, definition_hash text not null,
                cohort_hash text, envelope_hash text,
                status text not null,
                approval_expires_at integer, envelope_expires_at integer,
                reaffirm_by integer, estimated_spend_micros integer not null default 0,
                created_at integer not null, updated_at integer not null,
                primary key(tenant_id,campaign_id)
            );
            create table if not exists campaign_cohort(
                tenant_id text not null,campaign_id text not null,
                contact_id text not null,channel text not null,address_id text not null,
                branch_id text not null,masked_destination text not null,
                included integer not null,exclusion_reason text,
                primary key(tenant_id,campaign_id,contact_id,channel)
            );
            create table if not exists campaign_effects(
                tenant_id text not null,campaign_id text not null,
                contact_id text not null,channel text not null,address_id text not null,
                cycle integer not null default 1,status text not null,
                reason text,not_before integer not null default 0,
                claimed_by text,claimed_at integer,lease_expires_at integer,
                attempt_count integer not null default 0,provider_id text,
                updated_at integer not null,
                primary key(tenant_id,campaign_id,contact_id,channel)
            );
            create table if not exists campaign_audit(
                event_id integer primary key autoincrement,tenant_id text not null,
                campaign_id text not null,event_type text not null,
                actor_id text,details_json text not null,created_at integer not null
            );
        """)

    def create_preview(self, tenant_id, campaign_id, principal_id, definition,
                       audience, exclusions=None, estimated_spend_micros=0,
                       approval_ttl_seconds=900):
        self._validate_definition(definition)
        now = int(self.clock())
        included = {}
        for member in audience:
            self._validate_member(member)
            included.setdefault((member["contact_id"], member["channel"]), dict(member))
        if len(included) > int(definition["audience_ceiling"]):
            raise ValueError("campaign audience exceeds its ceiling")
        excluded = list(exclusions or ())
        cohort_proof = [{
            "contact_id": row["contact_id"], "channel": row["channel"],
            "address_id": row["address_id"], "branch_id": row["branch_id"],
        } for row in sorted(included.values(), key=lambda item: (
            item["contact_id"], item["channel"]
        ))]
        cohort_hash = _hash(cohort_proof)
        envelope_hash = _hash({
            "definition": definition, "definition_hash": _hash(definition),
            "cohort_hash": cohort_hash,
        })
        with self._transaction():
            self._connection.execute(
                """insert into campaigns(
                    tenant_id,campaign_id,created_by,definition_json,definition_hash,
                    cohort_hash,envelope_hash,status,approval_expires_at,
                    estimated_spend_micros,created_at,updated_at
                ) values(?,?,?,?,?,?,?,'audience_previewed',?,?,?,?)""",
                (tenant_id, campaign_id, principal_id, _json(definition),
                 _hash(definition), cohort_hash, envelope_hash,
                 now + int(approval_ttl_seconds), int(estimated_spend_micros), now, now),
            )
            for row in included.values():
                self._connection.execute(
                    """insert into campaign_cohort(
                        tenant_id,campaign_id,contact_id,channel,address_id,branch_id,
                        masked_destination,included
                    ) values(?,?,?,?,?,?,?,1)""",
                    (tenant_id, campaign_id, row["contact_id"], row["channel"],
                     row["address_id"], row["branch_id"], row["masked_destination"]),
                )
            for row in excluded:
                self._connection.execute(
                    """insert or ignore into campaign_cohort(
                        tenant_id,campaign_id,contact_id,channel,address_id,branch_id,
                        masked_destination,included,exclusion_reason
                    ) values(?,?,?,?,?,?,?,0,?)""",
                    (tenant_id, campaign_id, row["contact_id"], row.get("channel", "sms"),
                     row.get("address_id", "excluded:%s" % row["contact_id"]),
                     row.get("branch_id", definition["audience_rule"]["branch_id"]),
                     row.get("masked_destination", "redacted"), row["reason"]),
                )
            self._audit(tenant_id, campaign_id, "audience_previewed", principal_id, {
                "eligible_count": len(included), "excluded_count": len(excluded),
            }, now)
        return self.preview(tenant_id, campaign_id)

    def preview(self, tenant_id, campaign_id):
        campaign = self.get(tenant_id, campaign_id)
        rows = self._connection.execute(
            "select * from campaign_cohort where tenant_id=? and campaign_id=?",
            (tenant_id, campaign_id),
        ).fetchall()
        audience = [{
            "contact_id": row["contact_id"], "channel": row["channel"],
            "branch_id": row["branch_id"],
            "masked_destination": row["masked_destination"],
        } for row in rows if row["included"]]
        reasons = {}
        for row in rows:
            if not row["included"]:
                reasons[row["exclusion_reason"]] = reasons.get(row["exclusion_reason"], 0) + 1
        return {
            "campaign_id": campaign_id, "status": campaign["status"],
            "eligible_count": len(audience), "excluded_count": sum(reasons.values()),
            "exclusion_reasons": reasons, "audience": audience,
            "estimated_spend_micros": campaign["estimated_spend_micros"],
            "envelope_hash": campaign.get("envelope_hash"),
        }

    def authorize(self, tenant_id, campaign_id, principal_id, permission_check):
        now = int(self.clock())
        campaign = self.get(tenant_id, campaign_id)
        definition = campaign["definition"]
        branch_id = definition["audience_rule"]["branch_id"]
        if not permission_check(principal_id, branch_id):
            raise CampaignPermissionDenied("campaign_use permission is required")
        if campaign["status"] != "audience_previewed":
            raise CampaignStateConflict("campaign is not ready for authorization")
        if campaign["approval_expires_at"] < now:
            raise CampaignStateConflict("campaign preview authorization expired")
        envelope = {
            "definition": definition, "definition_hash": campaign["definition_hash"],
            "cohort_hash": campaign["cohort_hash"],
        }
        envelope_hash = _hash(envelope)
        if envelope_hash != campaign["envelope_hash"]:
            raise CampaignEnvelopeChanged("campaign preview binding changed")
        duration = int(definition["duration_seconds"])
        schedule_end = int(definition["schedule"]["ends_at"])
        schedule_start = int(definition["schedule"]["starts_at"])
        envelope_expires_at = min(schedule_start + duration, schedule_end)
        if envelope_expires_at <= now:
            raise CampaignStateConflict("campaign envelope is already expired")
        with self._transaction():
            cursor = self._connection.execute(
                """update campaigns set status='authorized',authorized_by=?,
                    envelope_hash=?,envelope_expires_at=?,updated_at=?
                   where tenant_id=? and campaign_id=? and status='audience_previewed'""",
                (principal_id, envelope_hash, envelope_expires_at, now,
                 tenant_id, campaign_id),
            )
            if cursor.rowcount != 1:
                raise CampaignStateConflict("campaign authorization raced")
            cohort = self._connection.execute(
                """select * from campaign_cohort where tenant_id=? and campaign_id=?
                   and included=1""", (tenant_id, campaign_id),
            ).fetchall()
            for row in cohort:
                self._connection.execute(
                    """insert into campaign_effects(
                        tenant_id,campaign_id,contact_id,channel,address_id,status,
                        not_before,updated_at
                    ) values(?,?,?,?,?,'pending',?,?)""",
                    (tenant_id, campaign_id, row["contact_id"], row["channel"],
                     row["address_id"], int(definition["schedule"]["starts_at"]), now),
                )
            self._audit(tenant_id, campaign_id, "authorized", principal_id, {
                "envelope_hash": envelope_hash,
            }, now)
        return self.get(tenant_id, campaign_id)

    def assert_envelope(self, tenant_id, campaign_id, definition):
        campaign = self.get(tenant_id, campaign_id)
        cohort = self._connection.execute(
            """select contact_id,channel,address_id,branch_id from campaign_cohort
               where tenant_id=? and campaign_id=? and included=1
               order by contact_id,channel""", (tenant_id, campaign_id),
        ).fetchall()
        cohort_hash = _hash([dict(row) for row in cohort])
        current_envelope_hash = _hash({
            "definition": definition, "definition_hash": _hash(definition),
            "cohort_hash": cohort_hash,
        })
        if (
            _hash(definition) != campaign["definition_hash"]
            or cohort_hash != campaign["cohort_hash"]
            or current_envelope_hash != campaign["envelope_hash"]
        ):
            now = int(self.clock())
            with self._transaction():
                self._connection.execute(
                    "update campaigns set status='invalidated',updated_at=? where tenant_id=? and campaign_id=?",
                    (now, tenant_id, campaign_id),
                )
                self._connection.execute(
                    """update campaign_effects set status='cancelled',reason='envelope_changed',
                       updated_at=? where tenant_id=? and campaign_id=? and status in ('pending','deferred')""",
                    (now, tenant_id, campaign_id),
                )
                self._audit(tenant_id, campaign_id, "envelope_invalidated", None, {}, now)
            raise CampaignEnvelopeChanged("material campaign definition changed")
        return campaign["envelope_hash"]

    def check_authority(self, tenant_id, campaign_id, permission_check,
                        reaffirm_within_seconds=86400):
        campaign = self.get(tenant_id, campaign_id)
        branch = campaign["definition"]["audience_rule"]["branch_id"]
        if permission_check(campaign["authorized_by"], branch):
            return "valid"
        now = int(self.clock())
        self._connection.execute(
            """update campaigns set status='paused',reaffirm_by=?,updated_at=?
               where tenant_id=? and campaign_id=? and status in ('authorized','scheduled','running')""",
            (now + int(reaffirm_within_seconds), now, tenant_id, campaign_id),
        )
        self._audit(tenant_id, campaign_id, "reaffirmation_required", None, {}, now)
        return "reaffirmation_required"

    def add_late_audience_member(self, tenant_id, campaign_id, member):
        campaign = self.get(tenant_id, campaign_id)
        if not campaign["definition"].get("include_late_arrivals"):
            return False
        if campaign["status"] not in (
            "authorized", "scheduled", "running", "deferred_quiet_hours",
            "throttled", "blocked_connection",
        ):
            return False
        self._validate_member(member)
        definition = campaign["definition"]
        now = int(self.clock())
        with self._transaction():
            count = self._connection.execute(
                """select count(*) as total from campaign_cohort
                   where tenant_id=? and campaign_id=? and included!=0""",
                (tenant_id, campaign_id),
            ).fetchone()["total"]
            if count >= int(definition["audience_ceiling"]):
                return False
            cursor = self._connection.execute(
                """insert or ignore into campaign_cohort(
                    tenant_id,campaign_id,contact_id,channel,address_id,branch_id,
                    masked_destination,included
                ) values(?,?,?,?,?,?,?,2)""",
                (tenant_id, campaign_id, member["contact_id"], member["channel"],
                 member["address_id"], member["branch_id"],
                 member["masked_destination"]),
            )
            if cursor.rowcount != 1:
                return False
            self._connection.execute(
                """insert into campaign_effects(
                    tenant_id,campaign_id,contact_id,channel,address_id,status,
                    not_before,updated_at
                ) values(?,?,?,?,?,'pending',?,?)""",
                (tenant_id, campaign_id, member["contact_id"], member["channel"],
                 member["address_id"],
                 max(now, int(definition["schedule"]["starts_at"])), now),
            )
            self._audit(tenant_id, campaign_id, "late_arrival_admitted", None, {
                "contact_id": member["contact_id"], "channel": member["channel"],
            }, now)
        return True

    def get(self, tenant_id, campaign_id):
        row = self._connection.execute(
            "select * from campaigns where tenant_id=? and campaign_id=?",
            (tenant_id, campaign_id),
        ).fetchone()
        if row is None:
            raise LookupError("campaign not found")
        value = dict(row)
        value["definition"] = json.loads(value.pop("definition_json"))
        return value

    def list_campaigns(self, tenant_id, limit=50):
        rows = self._connection.execute(
            """select * from campaigns where tenant_id=?
               order by created_at desc,campaign_id desc limit ?""",
            (tenant_id, int(limit)),
        ).fetchall()
        result = []
        for row in rows:
            value = dict(row)
            value["definition"] = json.loads(value.pop("definition_json"))
            result.append(value)
        return result

    def list_effects(self, tenant_id, campaign_id):
        return [dict(row) for row in self._connection.execute(
            """select * from campaign_effects where tenant_id=? and campaign_id=?
               order by contact_id,channel""", (tenant_id, campaign_id),
        ).fetchall()]

    def next_campaign(self, now_ts):
        row = self._connection.execute(
            """select tenant_id,campaign_id from campaigns
               where status in ('authorized','scheduled','running','blocked_connection',
                                'deferred_quiet_hours','throttled')
               order by updated_at,tenant_id,campaign_id limit 1"""
        ).fetchone()
        return dict(row) if row else None

    def set_status(self, tenant_id, campaign_id, status, reason=None):
        now = int(self.clock())
        self._connection.execute(
            "update campaigns set status=?,updated_at=? where tenant_id=? and campaign_id=?",
            (status, now, tenant_id, campaign_id),
        )
        self._audit(tenant_id, campaign_id, "status_changed", None,
                    {"status": status, "reason": reason}, now)

    def claim_next(self, worker_id, now_ts, lease_seconds=60,
                   tenant_id=None, campaign_id=None):
        now_ts = int(now_ts)
        with self._transaction():
            params = [now_ts]
            scope = ""
            if tenant_id is not None:
                scope += " and e.tenant_id=?"
                params.append(tenant_id)
            if campaign_id is not None:
                scope += " and e.campaign_id=?"
                params.append(campaign_id)
            rows = self._connection.execute(
                """select e.*,c.definition_json,c.envelope_hash,c.envelope_expires_at,
                          c.status as campaign_status
                   from campaign_effects e join campaigns c
                     on c.tenant_id=e.tenant_id and c.campaign_id=e.campaign_id
                   where e.status in ('pending','deferred') and e.not_before<=?
                     and c.status in ('authorized','scheduled','running',
                                      'deferred_quiet_hours','throttled')""" + scope +
                " order by c.updated_at,e.updated_at,e.contact_id,e.channel",
                tuple(params),
            ).fetchall()
            chosen = None
            for row in rows:
                definition = json.loads(row["definition_json"])
                active = self._connection.execute(
                    """select count(*) as total from campaign_effects
                       where tenant_id=? and campaign_id=? and status='claimed'""",
                    (row["tenant_id"], row["campaign_id"]),
                ).fetchone()["total"]
                if active < int(definition["concurrency"]):
                    chosen = row
                    break
            if chosen is None:
                return None
            cursor = self._connection.execute(
                """update campaign_effects set status='claimed',claimed_by=?,claimed_at=?,
                       lease_expires_at=?,updated_at=?
                   where tenant_id=? and campaign_id=? and contact_id=? and channel=?
                     and status in ('pending','deferred')""",
                (worker_id, now_ts, now_ts + int(lease_seconds), now_ts,
                 chosen["tenant_id"], chosen["campaign_id"], chosen["contact_id"],
                 chosen["channel"]),
            )
            if cursor.rowcount != 1:
                return None
            self._connection.execute(
                "update campaigns set status='running',updated_at=? where tenant_id=? and campaign_id=?",
                (now_ts, chosen["tenant_id"], chosen["campaign_id"]),
            )
        result = dict(chosen)
        result["status"] = "claimed"
        result["claimed_by"] = worker_id
        result["claimed_at"] = now_ts
        result["lease_expires_at"] = now_ts + int(lease_seconds)
        result["definition"] = json.loads(result.pop("definition_json"))
        return result

    def complete_effect(self, effect, status, reason=None, provider_id=None,
                        defer_until=None, count_attempt=False):
        if status not in TERMINAL_EFFECT_STATES | {"pending", "deferred"}:
            raise ValueError("invalid campaign effect status")
        now = int(self.clock())
        not_before = int(defer_until) if defer_until is not None else effect["not_before"]
        cursor = self._connection.execute(
            """update campaign_effects set status=?,reason=?,provider_id=?,not_before=?,
                   claimed_by=null,claimed_at=null,lease_expires_at=null,
                   attempt_count=attempt_count+?,updated_at=?
               where tenant_id=? and campaign_id=? and contact_id=? and channel=?
                 and status='claimed' and claimed_by=?""",
            (status, reason, provider_id, not_before, 1 if count_attempt else 0,
             now, effect["tenant_id"], effect["campaign_id"], effect["contact_id"],
             effect["channel"], effect["claimed_by"]),
        )
        return cursor.rowcount == 1

    def expire(self, tenant_id, campaign_id, now_ts):
        campaign = self.get(tenant_id, campaign_id)
        if int(now_ts) <= int(campaign["envelope_expires_at"]):
            return False
        with self._transaction():
            self._connection.execute(
                "update campaigns set status='expired',updated_at=? where tenant_id=? and campaign_id=?",
                (int(now_ts), tenant_id, campaign_id),
            )
            self._connection.execute(
                """update campaign_effects set status='cancelled',reason='envelope_expired',
                       updated_at=? where tenant_id=? and campaign_id=?
                       and status in ('pending','deferred')""",
                (int(now_ts), tenant_id, campaign_id),
            )
        return True

    def extend_envelope(self, tenant_id, campaign_id, _seconds):
        self.get(tenant_id, campaign_id)
        raise ValueError("campaign envelope cannot be extended; authorize a new campaign")

    def recover_expired_claims(self, now_ts):
        with self._lock:
            cursor = self._connection.execute(
                """update campaign_effects set status='uncertain',
                       reason='worker_lease_expired',claimed_by=null,claimed_at=null,
                       lease_expires_at=null,updated_at=?
                   where status='claimed' and lease_expires_at<?""",
                (int(now_ts), int(now_ts)),
            )
        return cursor.rowcount

    def reconcile_effect(self, tenant_id, campaign_id, contact_id, channel,
                         verdict, provider_id=None):
        status = "completed" if verdict == "delivered" else "prevented"
        reason = None if verdict == "delivered" else verdict
        cursor = self._connection.execute(
            """update campaign_effects set status=?,reason=?,provider_id=coalesce(?,provider_id),
                   updated_at=? where tenant_id=? and campaign_id=? and contact_id=?
                   and channel=? and status='uncertain'""",
            (status, reason, provider_id, int(self.clock()), tenant_id, campaign_id,
             contact_id, channel),
        )
        if cursor.rowcount:
            self.finalize(tenant_id, campaign_id)
        return cursor.rowcount == 1

    def pause(self, tenant_id, campaign_id, actor_id):
        campaign = self.get(tenant_id, campaign_id)
        if campaign["status"] not in ("authorized", "scheduled", "running",
                                      "deferred_quiet_hours", "throttled",
                                      "blocked_connection"):
            raise CampaignStateConflict("campaign cannot be paused")
        self.set_status(tenant_id, campaign_id, "paused", "operator_pause")
        self._audit(tenant_id, campaign_id, "paused", actor_id, {}, int(self.clock()))

    def resume(self, tenant_id, campaign_id, actor_id):
        campaign = self.get(tenant_id, campaign_id)
        if campaign["status"] != "paused" or campaign.get("reaffirm_by") is not None:
            raise CampaignStateConflict("campaign requires reaffirmation or is not paused")
        self.set_status(tenant_id, campaign_id, "running", "operator_resume")
        self._audit(tenant_id, campaign_id, "resumed", actor_id, {}, int(self.clock()))

    def reaffirm(self, tenant_id, campaign_id, principal_id, permission_check):
        campaign = self.get(tenant_id, campaign_id)
        branch = campaign["definition"]["audience_rule"]["branch_id"]
        if campaign["status"] != "paused" or campaign.get("reaffirm_by") is None:
            raise CampaignStateConflict("campaign does not require reaffirmation")
        if int(self.clock()) > int(campaign["reaffirm_by"]):
            raise CampaignStateConflict("campaign reaffirmation window expired")
        if not permission_check(principal_id, branch):
            raise CampaignPermissionDenied("campaign_use permission is required")
        now = int(self.clock())
        self._connection.execute(
            """update campaigns set status='running',authorized_by=?,reaffirm_by=null,
                   updated_at=? where tenant_id=? and campaign_id=? and status='paused'""",
            (principal_id, now, tenant_id, campaign_id),
        )
        self._audit(tenant_id, campaign_id, "reaffirmed", principal_id, {
            "envelope_hash": campaign["envelope_hash"],
        }, now)
        return self.get(tenant_id, campaign_id)

    def stop(self, tenant_id, campaign_id, reason):
        now = int(self.clock())
        with self._transaction():
            self._connection.execute(
                "update campaigns set status='stopped',updated_at=? where tenant_id=? and campaign_id=?",
                (now, tenant_id, campaign_id),
            )
            self._connection.execute(
                """update campaign_effects set status='prevented',reason=?,updated_at=?
                   where tenant_id=? and campaign_id=? and status in ('pending','deferred')""",
                (reason, now, tenant_id, campaign_id),
            )

    def drain_remaining(self, tenant_id, campaign_id, reason):
        now = int(self.clock())
        with self._transaction():
            self._connection.execute(
                "update campaigns set status='draining',updated_at=? where tenant_id=? and campaign_id=?",
                (now, tenant_id, campaign_id),
            )
            self._connection.execute(
                """update campaign_effects set status='prevented',reason=?,updated_at=?
                   where tenant_id=? and campaign_id=? and status in ('pending','deferred')""",
                (reason, now, tenant_id, campaign_id),
            )

    def finalize(self, tenant_id, campaign_id):
        rows = self.list_effects(tenant_id, campaign_id)
        if any(row["status"] in ("pending", "deferred", "claimed") for row in rows):
            return False
        status = "reconciling" if any(row["status"] == "uncertain" for row in rows) else "drained"
        current = self.get(tenant_id, campaign_id)["status"]
        if current not in ("expired", "stopped", "invalidated"):
            self.set_status(tenant_id, campaign_id, status)
        return status

    def report(self, tenant_id, campaign_id):
        campaign = self.get(tenant_id, campaign_id)
        counts = {"completed": 0, "in_progress": 0, "prevented": 0,
                  "uncertain": 0, "never_eligible_within_window": 0}
        for effect in self.list_effects(tenant_id, campaign_id):
            status = effect["status"]
            if status == "completed":
                counts["completed"] += 1
            elif status in ("pending", "deferred", "claimed"):
                counts["in_progress"] += 1
            elif status == "uncertain":
                counts["uncertain"] += 1
            elif status == "never_eligible":
                counts["never_eligible_within_window"] += 1
            else:
                counts["prevented"] += 1
        return {"campaign_id": campaign_id, "status": campaign["status"],
                "audience_total": sum(counts.values()), "outcomes": counts}

    def _audit(self, tenant_id, campaign_id, event_type, actor_id, details, now):
        self._connection.execute(
            """insert into campaign_audit(
                tenant_id,campaign_id,event_type,actor_id,details_json,created_at
            ) values(?,?,?,?,?,?)""",
            (tenant_id, campaign_id, event_type, actor_id, _json(details), now),
        )

    def _transaction(self):
        return _Transaction(self._connection, self._lock)

    @staticmethod
    def _validate_definition(value):
        required = {
            "audience_rule", "content", "channels", "senders", "schedule",
            "frequency", "budget_micros", "concurrency", "duration_seconds",
            "stop_conditions", "include_late_arrivals", "audience_ceiling",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("campaign definition fields are incomplete")
        if int(value["budget_micros"]) <= 0 or int(value["concurrency"]) <= 0:
            raise ValueError("campaign budget and concurrency must be positive")
        if int(value["duration_seconds"]) <= 0:
            raise ValueError("campaign duration must be positive")
        if int(value["audience_ceiling"]) <= 0:
            raise ValueError("campaign audience ceiling must be positive")
        forbidden = {"to", "destination", "address", "address_id", "contact_id"}
        stack = [value]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                if forbidden & set(item):
                    raise ValueError("campaign definition cannot carry destinations")
                stack.extend(item.values())
            elif isinstance(item, (list, tuple)):
                stack.extend(item)

    @staticmethod
    def _validate_member(member):
        required = {
            "contact_id", "channel", "address_id", "branch_id", "masked_destination",
        }
        if not isinstance(member, dict) or set(member) != required:
            raise ValueError("campaign audience member fields are incomplete")


class _Transaction:
    def __init__(self, connection, lock):
        self.connection, self.lock = connection, lock

    def __enter__(self):
        self.lock.acquire()
        self.connection.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, exc_type, _exc, _traceback):
        self.connection.execute("ROLLBACK" if exc_type else "COMMIT")
        self.lock.release()
        return False
