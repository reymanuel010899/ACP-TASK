"""Integration coverage for the first-party BFF session lifecycle (U0).

The tests deliberately exercise the real HTTP handler and SQLite repository
together.  Cryptographic identity proof is produced with ``libs.signing``;
the session service is not given a mocked principal.
"""

import json
import threading
from contextlib import contextmanager
from http.client import HTTPConnection

from libs import signing
from services.session.app import make_server
from services.session.repository import SessionRepository


NOW = 1_700_000_000


class Clock(object):
    def __init__(self, value=NOW):
        self.value = value

    def __call__(self):
        return self.value


def _assertion(now=NOW):
    principal = signing.generate_keypair()
    session = signing.generate_keypair()
    principal_id = principal.public_key_b64()
    proof = signing.build_session_assertion(
        principal_id,
        principal.signing_key,
        session.public_key_b64(),
        now_ts=now,
    )
    return principal_id, proof


@contextmanager
def _running_session_service(clock, idle_ttl=60, absolute_ttl=300):
    repository = SessionRepository(
        ":memory:",
        idle_ttl_seconds=idle_ttl,
        absolute_ttl_seconds=absolute_ttl,
    )
    server = make_server(
        host="127.0.0.1",
        port=0,
        repository=repository,
        clock=clock,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], repository
    finally:
        server.shutdown()
        server.server_close()
        repository.close()
        thread.join(timeout=2)


def _request(port, method, path="/sessions/current", body=None, cookie=None, csrf=None):
    headers = {}
    encoded = None
    if body is not None:
        encoded = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = cookie
    if csrf:
        headers["X-CSRF-Token"] = csrf

    connection = HTTPConnection("127.0.0.1", port, timeout=2)
    connection.request(method, path, body=encoded, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    result = (
        response.status,
        json.loads(raw.decode("utf-8")) if raw else None,
        dict(response.getheaders()),
    )
    connection.close()
    return result


def _create(port, proof, cookie=None):
    status, body, headers = _request(
        port,
        "POST",
        "/sessions",
        {"assertion": proof},
        cookie=cookie,
    )
    set_cookie = headers.get("Set-Cookie", "")
    session_cookie = set_cookie.split(";", 1)[0]
    return status, body, headers, session_cookie


def test_signed_principal_creates_opaque_http_only_session_and_derives_identity():
    clock = Clock()
    principal_id, proof = _assertion()

    with _running_session_service(clock) as (port, repository):
        status, body, headers, cookie = _create(port, proof)

        assert status == 201
        assert body["principal_id"] == principal_id
        assert body["csrf_token"]
        assert principal_id not in cookie
        assert repository.count_active(now_ts=clock()) == 1

        set_cookie = headers["Set-Cookie"]
        assert "Secure" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=Lax" in set_cookie

        # Identity comes only from the opaque cookie.  A caller cannot select
        # another principal through a query parameter.
        status, current, _ = _request(
            port,
            "GET",
            "/sessions/current?principal_id=attacker-controlled",
            cookie=cookie,
        )
        assert status == 200
        assert current["principal_id"] == principal_id


def test_unauthenticated_and_invalid_identity_proof_fail_closed():
    clock = Clock()
    _, proof = _assertion()
    proof["principal_id"] = signing.generate_keypair().public_key_b64()

    with _running_session_service(clock) as (port, repository):
        status, _, _ = _request(port, "GET")
        assert status == 401

        status, _, headers, _ = _create(port, proof)
        assert status == 401
        assert "Set-Cookie" not in headers
        assert repository.count_active(now_ts=clock()) == 0


def test_authentication_rotates_existing_cookie_and_rejects_proof_replay():
    clock = Clock()
    principal_id, first_proof = _assertion()
    _, second_proof = _assertion()
    second_proof["principal_id"] = principal_id
    # Re-sign a fresh assertion for the same principal.
    principal = signing.load_signing_key(
        # The helper intentionally does not expose its private key, so create
        # the actual same-principal pair here for the fixation scenario.
        signing.generate_keypair().signing_key_b64()
    )
    principal_id = principal.public_key_b64()
    first_session_key = signing.generate_keypair()
    second_session_key = signing.generate_keypair()
    first_proof = signing.build_session_assertion(
        principal_id, principal.signing_key, first_session_key.public_key_b64(), now_ts=NOW
    )
    second_proof = signing.build_session_assertion(
        principal_id, principal.signing_key, second_session_key.public_key_b64(), now_ts=NOW + 1
    )

    with _running_session_service(clock) as (port, _):
        status, _, _, first_cookie = _create(port, first_proof)
        assert status == 201

        clock.value += 1
        status, _, _, rotated_cookie = _create(port, second_proof, cookie=first_cookie)
        assert status == 201
        assert rotated_cookie != first_cookie

        status, _, _ = _request(port, "GET", cookie=first_cookie)
        assert status == 401
        status, _, _ = _request(port, "GET", cookie=rotated_cookie)
        assert status == 200

        # A captured signed proof is one-use and cannot mint another cookie.
        status, _, _, _ = _create(port, first_proof)
        assert status == 401


def test_idle_and_absolute_expiry_are_enforced_server_side():
    clock = Clock()
    _, idle_proof = _assertion()

    with _running_session_service(clock, idle_ttl=10, absolute_ttl=25) as (port, _):
        status, _, _, idle_cookie = _create(port, idle_proof)
        assert status == 201
        clock.value += 11
        status, _, headers = _request(port, "GET", cookie=idle_cookie)
        assert status == 401
        assert "Max-Age=0" in headers["Set-Cookie"]

        _, absolute_proof = _assertion(now=clock())
        status, _, _, absolute_cookie = _create(port, absolute_proof)
        assert status == 201
        for _ in range(3):
            clock.value += 8
            status, _, _ = _request(port, "GET", cookie=absolute_cookie)
            assert status == 200
        clock.value += 2
        status, _, _ = _request(port, "GET", cookie=absolute_cookie)
        assert status == 401


def test_idle_window_is_served_to_the_client_on_create_and_resolve():
    """The browser enforces the SAME idle cutoff this service does, so the
    number has to travel rather than be hardcoded on both sides and drift.
    `SessionProvider.tsx` reads it as `idle_ttl_seconds`."""
    clock = Clock()
    _, proof = _assertion()

    with _running_session_service(clock, idle_ttl=1800, absolute_ttl=43200) as (port, _):
        status, body, _, cookie = _create(port, proof)
        assert status == 201
        assert body["idle_ttl_seconds"] == 1800
        # The absolute cutoff stays absolute: it is not slid by activity.
        assert body["expires_at"] == clock() + 43200

        clock.value += 600
        status, current, _ = _request(port, "GET", cookie=cookie)
        assert status == 200
        assert current["idle_ttl_seconds"] == 1800
        assert current["expires_at"] == NOW + 43200


def test_revoke_requires_matching_csrf_and_cannot_cross_users():
    clock = Clock()
    _, alice_proof = _assertion()
    _, bob_proof = _assertion()

    with _running_session_service(clock) as (port, _):
        _, alice, _, alice_cookie = _create(port, alice_proof)
        _, bob, _, bob_cookie = _create(port, bob_proof)

        status, _, _ = _request(
            port, "DELETE", cookie=bob_cookie, csrf=alice["csrf_token"]
        )
        assert status == 403
        status, _, _ = _request(port, "GET", cookie=bob_cookie)
        assert status == 200

        status, _, headers = _request(
            port, "DELETE", cookie=bob_cookie, csrf=bob["csrf_token"]
        )
        assert status == 204
        assert "Max-Age=0" in headers["Set-Cookie"]
        status, _, _ = _request(port, "GET", cookie=bob_cookie)
        assert status == 401
