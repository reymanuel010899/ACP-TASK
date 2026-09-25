"""The administrator's control plane, at the boundary a browser reaches."""

from services.oauth.app import OAuthService
from services.oauth.repository import OAuthRepository


class SessionRepository:
    """Two sessions, two accounts, so cross-account attempts are expressible."""

    SESSIONS = {
        "session-acme": {"principal_id": "user:ana", "tenant_id": "org:acme"},
        "session-beta": {"principal_id": "user:ben", "tenant_id": "org:beta"},
    }
    TOKENS = {"session-acme": "csrf-acme", "session-beta": "csrf-beta"}

    def resolve(self, session_id, now, touch=True):
        return self.SESSIONS.get(session_id)

    def csrf_matches(self, session_id, token):
        return self.TOKENS.get(session_id) == token


def _service(tmp_path, effect_counts=None):
    return OAuthService(
        repository=OAuthRepository(str(tmp_path / "oauth.sqlite3")),
        session_repository=SessionRepository(),
        connector=None,
        managed_oauth_crypto=None,
        vault_service=None,
        clock=lambda: 1_700_000_000,
        effect_counts=effect_counts,
    )


def _families(body):
    return {item["family"]: item["enabled"] for item in body["families"]}


def test_every_family_the_manifest_ships_is_offered_and_starts_off(tmp_path):
    service = _service(tmp_path)

    status, body = service.control_plane_status("session-acme")

    assert status == 200
    families = _families(body)
    assert families["slack_messaging"] is False
    assert families["slack_direct_messages"] is False
    assert body["emergency_stop"] is False


def test_enabling_one_family_returns_the_state_the_server_will_enforce(tmp_path):
    service = _service(tmp_path)

    status, body = service.decide_control_plane("session-acme", "csrf-acme", {
        "action": "family", "family": "slack_messaging", "enabled": True,
    })

    assert status == 200
    families = _families(body)
    assert families["slack_messaging"] is True
    # The neighbouring family is untouched: one switch, one family.
    assert families["slack_direct_messages"] is False


def test_one_administrator_cannot_reach_another_accounts_switches(tmp_path):
    service = _service(tmp_path)
    service.decide_control_plane("session-beta", "csrf-beta", {
        "action": "family", "family": "slack_messaging", "enabled": True,
    })

    # There is no argument that names a tenant. The body below tries anyway.
    service.decide_control_plane("session-acme", "csrf-acme", {
        "action": "emergency_stop", "enabled": True,
        "tenant_id": "org:beta", "principal_id": "user:ben",
    })

    _status, beta = service.control_plane_status("session-beta")
    assert beta["emergency_stop"] is False
    assert _families(beta)["slack_messaging"] is True
    _status, acme = service.control_plane_status("session-acme")
    assert acme["emergency_stop"] is True


def test_a_control_plane_change_needs_a_session_and_a_csrf_token(tmp_path):
    service = _service(tmp_path)
    body = {"action": "emergency_stop", "enabled": True}

    assert service.decide_control_plane(None, "csrf-acme", body)[0] == 401
    assert service.decide_control_plane("session-acme", "wrong", body)[0] == 403
    assert service.control_plane_status("session-acme")[1][
        "emergency_stop"
    ] is False


def test_an_unknown_family_is_refused_rather_than_silently_created(tmp_path):
    service = _service(tmp_path)

    status, body = service.decide_control_plane("session-acme", "csrf-acme", {
        "action": "family", "family": "slack_teleportation", "enabled": True,
    })

    assert status == 422
    assert body["error"] == "unknown capability family"


def test_the_stop_reports_what_was_dispatched_against_what_was_prevented(
    tmp_path,
):
    counts = {
        "dispatched": 7, "prevented": 3, "in_progress": 1, "uncertain": 2,
        "failed": 0,
    }
    service = _service(tmp_path, effect_counts=lambda tenant_id: counts)

    _status, body = service.decide_control_plane("session-acme", "csrf-acme", {
        "action": "emergency_stop", "enabled": True, "reason": "paged",
    })

    assert body["emergency_stop"] is True
    assert body["stop_reason"] == "paged"
    assert body["stopped_by_principal_id"] == "user:ana"
    assert body["effects"] == counts


def test_counts_that_cannot_be_read_are_reported_absent_not_as_zero(tmp_path):
    def explode(_tenant_id):
        raise RuntimeError("workflow store is unavailable")

    service = _service(tmp_path, effect_counts=explode)

    _status, body = service.control_plane_status("session-acme")

    # Zeros would tell an operator nothing was prevented, when the truth is
    # that nobody counted.
    assert body["effects"] is None
