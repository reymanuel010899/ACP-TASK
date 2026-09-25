"""Tenant-bound ownership history for Twilio numbers and channel addresses."""

from libs.ulid import generate_ulid


class IdentityAlreadyOwned(RuntimeError):
    pass


class TwilioIdentityRepository:
    def __init__(self, db):
        self.db = db

    def claim(self, tenant_id, connection_id, address, provider_sid, kind,
              verified_at):
        with self.db.transaction() as conn:
            conn.execute("select set_config('app.current_org_id',%s,true)", (tenant_id,))
            try:
                row = conn.execute(
                    """insert into twilio.identities(
                        identity_version_id,identity_address,tenant_id,
                        connection_id,provider_identity_sid,identity_kind,
                        possession_verified_at,valid_from
                    ) values(%s,%s,%s,%s,%s,%s,%s,%s)
                    returning identity_version_id,identity_address,tenant_id,
                              connection_id,valid_from,valid_until""",
                    ("identity:%s" % generate_ulid(), address, tenant_id,
                     connection_id, provider_sid, kind, verified_at, verified_at),
                ).fetchone()
            except Exception as exc:
                # The partial unique index is the global owner lock. Do not
                # disclose which tenant owns it.
                if getattr(exc, "sqlstate", None) == "23505":
                    raise IdentityAlreadyOwned("identity is already owned") from exc
                raise
        return _row(row)

    def release(self, tenant_id, address, released_at):
        with self.db.transaction() as conn:
            conn.execute("select set_config('app.current_org_id',%s,true)", (tenant_id,))
            row = conn.execute(
                """update twilio.identities set valid_until=%s
                   where tenant_id=%s and identity_address=%s and valid_until is null
                   returning identity_version_id""",
                (released_at, tenant_id, address),
            ).fetchone()
        return row is not None

    def owner_at(self, address, event_time):
        # Callback attribution runs under a privileged service role and
        # returns only the owning tenant id; callers then bind that tenant for
        # every subsequent read. Current ownership is deliberately irrelevant.
        with self.db.connection() as conn:
            row = conn.execute(
                """select tenant_id from twilio.identities
                   where identity_address=%s and valid_from<=%s
                     and (valid_until is null or valid_until>%s)
                   order by valid_from desc limit 1""",
                (address, event_time, event_time),
            ).fetchone()
        return row[0] if row else None


def _row(row):
    columns = (
        "identity_version_id", "identity_address", "tenant_id",
        "connection_id", "valid_from", "valid_until",
    )
    return dict(zip(columns, row)) if row else None
