import json
from contextlib import contextmanager

import pytest

from libs.integrations.catalog import VerifiedAccountState, VerifiedSender
from services.integrations.repository import (
    IntegrationConnectionConflict,
    ProviderControlPlaneRepository,
)


TENANT = "org:acme"
CONNECTION = "conn:twilio"
ACCOUNT_ID = "AC0000000000000000000000000000001"
SENDER_A = "+18095550100"
SENDER_B = "+18095550200"


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConnection:
    """Just enough Postgres to hold the control plane's four tables."""

    def __init__(self):
        self.account = None
        self.families = {}
        self.senders = {}
        self.templates = {}
        self.derived = []
        self.effective_scopes = []
        self.statements = []

    def execute(self, sql, params=()):
        flat = " ".join(sql.split())
        self.statements.append((flat, params))
        if "insert into integrations.provider_accounts" in flat:
            self.account = (params[2], params[3], params[4])
        elif "insert into integrations.provider_account_families" in flat:
            self.families[params[2]] = True
        elif "insert into integrations.provider_senders" in flat:
            self.senders[params[2]] = [
                params[3], json.loads(params[4]), bool(params[5])
            ]
        elif "update integrations.provider_senders" in flat:
            sender_id = params[6]
            if sender_id not in self.senders:
                return FakeCursor(())
            self.senders[sender_id][2] = bool(params[0])
            return FakeCursor([(sender_id,)])
        elif "update integrations.provider_account_families" in flat:
            family = params[3]
            if family not in self.families:
                return FakeCursor(())
            self.families[family] = bool(params[0])
            return FakeCursor([(family,)])
        elif "select provider, provider_account_id, status" in flat:
            return FakeCursor([self.account] if self.account else ())
        elif "select family from" in flat:
            return FakeCursor(
                [(name,) for name, on in sorted(self.families.items()) if on]
            )
        elif "select sender_id, family, countries, enabled" in flat:
            return FakeCursor([
                (sender_id, row[0], json.dumps(sorted(row[1])), row[2])
                for sender_id, row in sorted(self.senders.items())
            ])
        elif "select template_id" in flat:
            return FakeCursor(sorted(self.templates.items()))
        elif "delete from integrations.provider_derived_scopes" in flat:
            self.derived = []
        elif "insert into integrations.provider_derived_scopes" in flat:
            self.derived.append((params[2], params[3], params[4]))
        elif "update integrations.connections" in flat:
            self.effective_scopes = json.loads(params[0])
        return FakeCursor(())


class FakeDatabase:
    def __init__(self):
        self.conn = FakeConnection()

    @contextmanager
    def transaction(self):
        yield self.conn

    @contextmanager
    def connection(self):
        yield self.conn


def _state(status="verified", senders=None):
    return VerifiedAccountState(
        provider="twilio",
        account_id=ACCOUNT_ID,
        status=status,
        families=frozenset({"sms:send"}),
        senders=senders if senders is not None else (
            VerifiedSender(SENDER_A, "sms", frozenset({"ES"})),
            VerifiedSender(SENDER_B, "sms", frozenset({"DO"})),
        ),
    )


def _repository(state=None):
    db = FakeDatabase()
    repository = ProviderControlPlaneRepository(db)
    repository.record_verified_account(
        TENANT, CONNECTION, "twilio", ACCOUNT_ID, state or _state(),
    )
    return repository, db


def test_recording_a_verified_account_materialises_its_synthetic_scopes():
    _repository_, db = _repository()

    assert db.conn.effective_scopes == [
        "twilio:geo:DO", "twilio:geo:ES",
        "twilio:sender:%s" % SENDER_A, "twilio:sender:%s" % SENDER_B,
        "twilio:sms:send",
    ]
    # Each derived scope records what it came from, so an operator can answer
    # why an effect stopped dispatching from data rather than reconstruction.
    assert ("twilio:sender:%s" % SENDER_A, "sender", SENDER_A) in db.conn.derived
    assert ("twilio:geo:ES", "geo", "ES") in db.conn.derived
    assert ("twilio:sms:send", "family", "sms") in db.conn.derived


def test_disabling_one_sender_removes_one_scope_and_leaves_the_other():
    repository, db = _repository()

    scopes = repository.set_sender_enabled(
        TENANT, CONNECTION, SENDER_A, False, acting_principal_id="user:alice",
    )

    assert "twilio:sender:%s" % SENDER_A not in scopes
    assert "twilio:sender:%s" % SENDER_B in scopes
    assert "twilio:sms:send" in scopes
    assert db.conn.effective_scopes == sorted(scopes)


def test_disabling_a_sender_never_touches_the_credential_version():
    repository, db = _repository()

    repository.set_sender_enabled(TENANT, CONNECTION, SENDER_A, False)

    # A version bump would fail every queued effect on this connection, in
    # every family, with a reason that reads as tampering. The secret did not
    # change, so nothing here may claim it did.
    written = " ".join(statement for statement, _params in db.conn.statements)
    assert "credential_version" not in written


def test_disabling_a_family_removes_its_senders_authority_too():
    repository, _db = _repository()

    scopes = repository.set_family_enabled(TENANT, CONNECTION, "sms", False)

    # Enabling the number and enabling the family are separate acts, and the
    # narrower one wins.
    assert scopes == frozenset()


def test_an_account_that_stops_verifying_derives_nothing():
    repository, db = _repository()

    scopes = repository.record_verified_account(
        TENANT, CONNECTION, "twilio", ACCOUNT_ID, _state(status="suspended"),
    )

    assert scopes == frozenset()
    assert db.conn.effective_scopes == []


def test_rotating_the_static_secret_is_the_one_thing_that_bumps_the_version():
    db = FakeDatabase()
    db.conn.execute = lambda sql, params=(): FakeCursor([("cred:2", 4)])
    repository = ProviderControlPlaneRepository(db)

    result = repository.rotate_static_credential(TENANT, CONNECTION, "cred:2")

    assert result == {"credential_id": "cred:2", "credential_version": 4}


def test_a_sender_outside_this_connection_cannot_be_toggled():
    repository, _db = _repository()

    with pytest.raises(IntegrationConnectionConflict):
        repository.set_sender_enabled(TENANT, CONNECTION, "+10000000000", False)


def test_verified_state_reads_back_what_the_control_plane_holds():
    repository, _db = _repository()

    state = repository.verified_state(TENANT, CONNECTION)

    assert state.provider == "twilio"
    assert state.account_id == ACCOUNT_ID
    assert state.status == "verified"
    assert state.families == frozenset({"sms:send"})
    assert {sender.sender_id for sender in state.senders} == {
        SENDER_A, SENDER_B
    }
