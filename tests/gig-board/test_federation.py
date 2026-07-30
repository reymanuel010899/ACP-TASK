"""Federation tests between Gig Board and Marketplace.

Demonstrates that U4 (Gig Board) works alongside U3 (Marketplace)
and proves that federation works across different app domains.
"""

import threading
import pytest
import requests

from apps.gig_board.server.app import make_server as make_gig_board
from apps.marketplace.server.app import make_server as make_marketplace
from libs.db import Database
from libs.ulid import generate_ulid


def base_url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


@pytest.fixture
def gig_board():
    server = make_gig_board(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def marketplace():
    server = make_marketplace(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_both_apps_run_independently(gig_board, marketplace):
    """Test that both apps can run simultaneously without interference."""
    # Healthz checks
    gb_health = requests.get(base_url(gig_board) + "/healthz", timeout=5)
    assert gb_health.status_code == 200

    mp_health = requests.get(base_url(marketplace) + "/healthz", timeout=5)
    assert mp_health.status_code == 200


def test_user_can_participate_in_both_apps(gig_board, marketplace):
    """Test that a user (Principal) can participate in both apps."""
    user_principal = "ed25519_alice"

    # Create a service in Gig Board
    gb_service = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": user_principal,
            "service_name": "Consulting",
            "description": "Business consulting",
        },
        timeout=5,
    )
    assert gb_service.status_code == 200

    # Create a task in Marketplace (as author, different role)
    mp_task = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": user_principal,
            "description": "Need help with project",
        },
        timeout=5,
    )
    assert mp_task.status_code == 200

    # Verify both exist
    gb_services = requests.get(
        base_url(gig_board) + "/api/services",
        timeout=5,
    )
    assert len(gb_services.json()["services"]) == 1

    mp_tasks = requests.get(
        base_url(marketplace) + "/api/tasks",
        timeout=5,
    )
    # Unit U7: gig-board's Service listing is now a row in the SAME shared
    # ``marketplace.tasks`` table apps/marketplace uses (unit U6), scoped by
    # capability_id = 'gig-board.gigs'. apps/marketplace's own /api/tasks
    # excludes rows carrying that capability_id (see
    # MarketplaceRepository.list_tasks's docstring) precisely so a
    # marketplace user's task list never shows unrelated gig-board postings
    # -- so this still sees only the 1 task it created itself, exactly as
    # before table consolidation.
    assert len(mp_tasks.json()["tasks"]) == 1


def test_different_users_in_different_apps(gig_board, marketplace):
    """Test that different users can participate in each app domain."""
    # User A: Service provider in Gig Board
    alice_principal = "ed25519_alice"
    alice_service = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": alice_principal,
            "service_name": "Logo Design",
            "description": "Professional logos",
        },
        timeout=5,
    )
    assert alice_service.status_code == 200

    # User B: Task poster in Marketplace
    bob_principal = "ed25519_bob"
    bob_task = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": bob_principal,
            "description": "Build a website",
        },
        timeout=5,
    )
    assert bob_task.status_code == 200

    # Verify they're in separate domains
    gig_board_users = set()
    for svc in requests.get(base_url(gig_board) + "/api/services", timeout=5).json()["services"]:
        gig_board_users.add(svc["provider_principal"])

    marketplace_users = set()
    for task in requests.get(base_url(marketplace) + "/api/tasks", timeout=5).json()["tasks"]:
        marketplace_users.add(task["author_principal"])

    assert alice_principal in gig_board_users
    assert bob_principal in marketplace_users
    # They shouldn't overlap (this test case)
    assert gig_board_users != marketplace_users


def test_marketplace_patterns_still_work(marketplace):
    """Regression test: ensure marketplace functionality isn't broken."""
    author = "ed25519_author"
    worker = "ed25519_worker"

    # Create task
    task_resp = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": author,
            "description": "Fix the bug",
        },
        timeout=5,
    )
    assert task_resp.status_code == 200
    task_id = task_resp.json()["task"]["id"]

    # Accept task
    accept_resp = requests.post(
        base_url(marketplace) + f"/api/tasks/{task_id}/accept",
        json={"worker_principal": worker},
        timeout=5,
    )
    assert accept_resp.status_code == 200

    # Verify it's accepted
    task_check = requests.get(
        base_url(marketplace) + f"/api/tasks/{task_id}",
        timeout=5,
    )
    assert task_check.json()["task"]["status"] == "accepted"
    assert task_check.json()["task"]["worker_principal"] == worker


def test_gig_board_patterns_work_independently(gig_board):
    """Regression test: ensure gig board functionality isn't broken."""
    provider = "ed25519_provider"
    buyer = "ed25519_buyer"

    # Register service
    service_resp = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": provider,
            "service_name": "Tutoring",
            "description": "Math tutoring",
        },
        timeout=5,
    )
    assert service_resp.status_code == 200
    service_id = service_resp.json()["service"]["id"]

    # Create gig
    gig_resp = requests.post(
        base_url(gig_board) + "/api/gigs",
        json={
            "service_id": service_id,
            "buyer_principal": buyer,
            "description": "Teach algebra",
        },
        timeout=5,
    )
    assert gig_resp.status_code == 200

    # Verify gig exists
    gigs_resp = requests.get(
        base_url(gig_board) + f"/api/gigs?principal_id={buyer}",
        timeout=5,
    )
    assert len(gigs_resp.json()["gigs"]) == 1


def test_both_apps_scale_independently(gig_board, marketplace):
    """Test that both apps can scale independently."""
    # Create 5 services in gig board
    for i in range(5):
        requests.post(
            base_url(gig_board) + "/api/services",
            json={
                "principal_id": f"ed25519_provider_{i}",
                "service_name": f"Service {i}",
                "description": f"Description {i}",
            },
            timeout=5,
        )

    # Create 3 tasks in marketplace
    for i in range(3):
        requests.post(
            base_url(marketplace) + "/api/tasks",
            json={
                "principal_id": f"ed25519_author_{i}",
                "description": f"Task {i}",
            },
            timeout=5,
        )

    # Verify counts
    gb_services = requests.get(base_url(gig_board) + "/api/services", timeout=5)
    # gig-board's OWN listing stays correctly scoped to its
    # "gig-board.gigs"-capability rows -- proves it in isolation regardless
    # of how many unrelated marketplace tasks share the same physical table.
    assert gb_services.json()["total"] == 5

    mp_tasks = requests.get(base_url(marketplace) + "/api/tasks", timeout=5)
    # Unit U7: gig-board's 5 services are now rows in the SAME shared
    # ``marketplace.tasks`` table (unit U6), but marketplace's own
    # /api/tasks excludes 'gig-board.gigs'-capability rows -- so its total
    # is exactly the 3 marketplace tasks this test created, unaffected by
    # how many unrelated gig-board services exist. See the identical note
    # in test_user_can_participate_in_both_apps.
    assert mp_tasks.json()["total"] == 3


def test_federation_different_data_models(gig_board, marketplace):
    """Verify that both apps have different data models appropriate for their domain."""
    # Gig Board: Service model (provider-centric)
    gig_board_service = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": "ed25519_provider",
            "service_name": "Coaching",
            "description": "Career coaching",
        },
        timeout=5,
    ).json()["service"]

    # Gig Board has provider_principal, service_name, gigs_completed
    assert "provider_principal" in gig_board_service
    assert "service_name" in gig_board_service
    assert "gigs_completed" in gig_board_service

    # Marketplace: Task model (work-centric)
    marketplace_task = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": "ed25519_author",
            "description": "Build API",
        },
        timeout=5,
    ).json()["task"]

    # Marketplace has author_principal, description, negotiations
    assert "author_principal" in marketplace_task
    assert "description" in marketplace_task
    assert "negotiations" in marketplace_task

    # They're different!
    assert "service_name" not in marketplace_task
    assert "negotiations" not in gig_board_service


# ---------------------------------------------------------------------------
# Unit U7: gig-board consolidated onto the SAME marketplace.tasks table.
# ---------------------------------------------------------------------------


def test_capability_scoping_isolates_services_from_marketplace_tasks(
    gig_board, marketplace
):
    """Prove capability_id-based scoping actually isolates gig-board's own
    Service/Gig views from apps/marketplace's unrelated tasks that now live
    in the SAME physical ``marketplace.tasks`` table (unit U6/U7) -- and
    vice versa: a marketplace task_id is never mistaken for a gig-board
    resource."""
    provider = "ed25519_shared_principal"

    # Same principal posts a plain marketplace task AND registers a
    # gig-board service -- both land as rows in marketplace.tasks.
    mp_task = requests.post(
        base_url(marketplace) + "/api/tasks",
        json={
            "principal_id": provider,
            "description": "A perfectly ordinary marketplace task",
        },
        timeout=5,
    ).json()["task"]

    gb_service = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": provider,
            "service_name": "Isolated Service",
            "description": "Should never be confused with the task above",
        },
        timeout=5,
    ).json()["service"]

    # gig-board's own listing shows exactly the 1 service it created -- the
    # marketplace task by the SAME principal never leaks in.
    services = requests.get(
        base_url(gig_board) + "/api/services", timeout=5
    ).json()
    assert services["total"] == 1
    assert [s["id"] for s in services["services"]] == [gb_service["id"]]

    # The marketplace task_id is not a gig-board service, and is never
    # mistaken for a gig either (both scoping checks in
    # GigBoardRepository -- capability_id AND the "kind" envelope -- hold).
    not_a_service = requests.get(
        base_url(gig_board) + "/api/services/%s" % mp_task["id"], timeout=5
    )
    assert not_a_service.status_code == 404

    not_a_gig = requests.get(
        base_url(gig_board) + "/api/gigs?principal_id=%s" % provider,
        timeout=5,
    ).json()
    assert not_a_gig["gigs"] == []  # no gig-board booking exists at all yet

    # And the gig-board service_id is never mistaken for a marketplace task
    # in the other direction either (defense in depth -- apps/marketplace's
    # own GET /api/tasks/{id} still finds it, since it IS a real
    # marketplace.tasks row; what matters is gig-board's OWN scoping, above).
    mp_view_of_service = requests.get(
        base_url(marketplace) + "/api/tasks/%s" % gb_service["id"], timeout=5
    ).json()["task"]
    assert mp_view_of_service["author_principal"] == provider


def test_gigs_completed_is_derived_and_cannot_drift(gig_board):
    """``gigs_completed`` is a live COUNT over completed
    ``marketplace.tasks`` rows (``GigBoardRepository.gigs_completed``), not
    a stored/incremented counter -- so directly manipulating the underlying
    rows (bypassing every gig-board code path entirely) changes what's
    reported immediately, proving there is no separate counter to drift out
    of sync."""
    provider = "ed25519_derive_provider"
    buyer = "ed25519_derive_buyer"

    service = requests.post(
        base_url(gig_board) + "/api/services",
        json={
            "principal_id": provider,
            "service_name": "Derivation Test Service",
            "description": "Proves gigs_completed can't drift",
        },
        timeout=5,
    ).json()["service"]
    assert service["gigs_completed"] == 0

    # Complete 2 real gigs through the normal API -- no manual increment
    # path exists anywhere in this codebase to reach for comparison.
    for _ in range(2):
        gig = requests.post(
            base_url(gig_board) + "/api/gigs",
            json={
                "service_id": service["id"],
                "buyer_principal": buyer,
                "description": "a booking",
            },
            timeout=5,
        ).json()["gig"]
        requests.post(
            base_url(gig_board) + "/api/gigs/%s/complete" % gig["id"],
            json={"buyer_principal": buyer, "outcome": "done"},
            timeout=5,
        )

    after_two = requests.get(
        base_url(gig_board) + "/api/services/%s" % service["id"], timeout=5
    ).json()["service"]
    assert after_two["gigs_completed"] == 2

    # Now bypass EVERY gig-board code path and insert a THIRD completed
    # "gig" row directly, straight into marketplace.tasks -- there is no
    # gig-board method that could have done this (no increment path
    # exists), and yet the reported count must already reflect it, because
    # it's a live query, not a cached/stored field.
    db = Database()
    with db.transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO marketplace.tasks
                    (task_id, author_principal_id, worker_principal_id,
                     capability_id, description, status)
                VALUES (%s, %s, %s, 'gig-board.gigs', %s, 'completed')
                """,
                (
                    generate_ulid(), buyer, provider,
                    '{"kind": "gig", "service_id": "%s", '
                    '"description": "injected directly"}' % service["id"],
                ),
            )

    after_direct_insert = requests.get(
        base_url(gig_board) + "/api/services/%s" % service["id"], timeout=5
    ).json()["service"]
    assert after_direct_insert["gigs_completed"] == 3
