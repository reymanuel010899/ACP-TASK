import tempfile
import os

import pytest

from services.action_broker.app import ActionBroker
from services.session.repository import SessionRepository

NOW = 1_700_000_000
FRESHNESS = ActionBroker.REINFORCED_FRESHNESS_SECONDS


def _sessions(tmp_path):
    return SessionRepository(str(tmp_path / "sessions.sqlite3"))


class _Actions:
    def __init__(self, reinforced):
        self.reinforced = reinforced
        self.decided = None

    def get(self, proposal_id):
        return {"proposal_id": proposal_id, "reinforced": self.reinforced}

    def decide(self, proposal_id, version, principal, approved, now):
        self.decided = (proposal_id, version, principal, approved)
        return True


def _broker(sessions, reinforced, now=NOW):
    return ActionBroker(
        _Actions(reinforced), sessions, object(), object(), clock=lambda: now,
    )


def _session(sessions, now=NOW):
    created = sessions.create("user:alice", "proof-%d" % now, now)
    return created["session_id"], created["csrf_token"]


def test_a_session_that_just_authenticated_is_fresh(tmp_path):
    sessions = _sessions(tmp_path)
    session_id, _csrf = _session(sessions)

    attestation = sessions.authentication_attestation(session_id, NOW, FRESHNESS)

    assert attestation["fresh"] is True
    assert attestation["age_seconds"] == 0


def test_using_a_session_does_not_refresh_its_authentication(tmp_path):
    sessions = _sessions(tmp_path)
    session_id, _csrf = _session(sessions)

    sessions.resolve(session_id, NOW + FRESHNESS + 60, touch=True)
    attestation = sessions.authentication_attestation(
        session_id, NOW + FRESHNESS + 60, FRESHNESS,
    )

    # Touching keeps a session alive; it proves nothing new about who is there.
    assert attestation["fresh"] is False
    assert attestation["reason"] == "authentication_stale"


def test_reauthenticating_makes_a_stale_session_fresh_again(tmp_path):
    sessions = _sessions(tmp_path)
    session_id, _csrf = _session(sessions)
    later = NOW + FRESHNESS + 60

    assert sessions.attest_authentication(session_id, later) is True
    assert sessions.authentication_attestation(
        session_id, later, FRESHNESS,
    )["fresh"] is True


def test_an_unknown_session_is_never_fresh(tmp_path):
    sessions = _sessions(tmp_path)

    attestation = sessions.authentication_attestation("nope", NOW, FRESHNESS)

    assert attestation["fresh"] is False
    assert attestation["reason"] == "session_absent"


def test_a_reinforced_approval_from_a_stale_session_is_refused(tmp_path):
    sessions = _sessions(tmp_path)
    session_id, csrf = _session(sessions)
    later = NOW + FRESHNESS + 60
    broker = _broker(sessions, reinforced=True, now=later)

    status, body = broker.decide(
        session_id, csrf, "proposal:1", {"version": 1, "approved": True},
    )

    assert status == 403
    assert body["error"] == "step_up_required"
    assert body["recovery"] == "reauthenticate"
    assert broker.actions.decided is None


def test_a_reinforced_approval_after_reauthentication_goes_through(tmp_path):
    sessions = _sessions(tmp_path)
    session_id, csrf = _session(sessions)
    later = NOW + FRESHNESS + 60
    sessions.attest_authentication(session_id, later)
    broker = _broker(sessions, reinforced=True, now=later)

    status, body = broker.decide(
        session_id, csrf, "proposal:1", {"version": 1, "approved": True},
    )

    assert status == 200
    assert body["status"] == "approved"


def test_an_ordinary_approval_is_untouched_by_step_up(tmp_path):
    sessions = _sessions(tmp_path)
    session_id, csrf = _session(sessions)
    later = NOW + FRESHNESS + 60
    broker = _broker(sessions, reinforced=False, now=later)

    status, body = broker.decide(
        session_id, csrf, "proposal:1", {"version": 1, "approved": True},
    )

    # Step-up is for effects that cannot be walked back, not a tax on
    # everyday work.
    assert status == 200
    assert body["status"] == "approved"


def test_rejecting_a_reinforced_proposal_never_needs_a_step_up(tmp_path):
    sessions = _sessions(tmp_path)
    session_id, csrf = _session(sessions)
    later = NOW + FRESHNESS + 60
    broker = _broker(sessions, reinforced=True, now=later)

    status, body = broker.decide(
        session_id, csrf, "proposal:1", {"version": 1, "approved": False},
    )

    # Refusing to do something is always safe, so a stale session may refuse.
    assert status == 200
    assert body["status"] == "rejected"
