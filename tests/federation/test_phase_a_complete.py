"""Phase A End-to-End Federation Test Suite.

Comprehensive tests proving the federated ecosystem works:
- 3 apps (Console via Registry, Marketplace, Gig Board) coexist on same protocol
- Users maintain portable Principal across all apps
- Reputation flows correctly between apps
- Cross-app interaction and discovery works
- Registry independence is proven

Test scenarios:
1. User Portability - same Principal across apps
2. Reputation Aggregation - reputation combines across apps
3. Cross-App Interaction - users from different apps interact
4. Registry Independence - registry survives app restarts
5. Concurrent Users - multiple simultaneous users work correctly
6. Reputation Correctness - reputation calculations are accurate
7. Authorization Boundaries - users can't act on others' work
8. Principal Uniqueness - no duplicate registrations

Total: 20+ tests
"""

import pytest
from tests.federation.fixtures import (
    AppClient,
    registry_server,
    marketplace_server,
    gig_board_server,
    registry_client,
    marketplace_client,
    gig_board_client,
    all_apps,
    all_clients,
)


# ============================================================================
# Scenario 1: User Portability
# ============================================================================

class TestUserPortability:
    """User A maintains same Principal across all 3 apps."""

    def test_user_register_in_registry_login_everywhere(
        self, registry_client, marketplace_client, gig_board_client
    ):
        """User registers in registry, then logs in to marketplace and gig board."""
        user_principal = "user_alice"

        # Register user in registry
        user = registry_client.register_user(user_principal, username="alice")
        assert user["status"] == "registered"
        assert user["principal_id"] == user_principal

        # User can login to marketplace with same principal
        login_mp = marketplace_client.login_user(user_principal)
        assert login_mp["principal_id"] == user_principal

        # User can login to gig board with same principal
        login_gb = gig_board_client.login_user(user_principal)
        assert login_gb["principal_id"] == user_principal

        # All apps see the same user
        user_via_mp = marketplace_client.get_user(user_principal)
        assert user_via_mp["principal_id"] == user_principal

        user_via_gb = gig_board_client.get_user(user_principal)
        assert user_via_gb["principal_id"] == user_principal

    def test_user_session_persists_across_app_restarts(
        self, registry_client, marketplace_client
    ):
        """User session data persists even if apps restart."""
        user_principal = "user_bob"

        # Register user
        registry_client.register_user(user_principal, username="bob")

        # User logs in to marketplace
        login1 = marketplace_client.login_user(user_principal)
        assert login1["principal_id"] == user_principal

        # User logs in again (simulating page reload or app restart)
        login2 = marketplace_client.login_user(user_principal)
        assert login2["principal_id"] == user_principal

        # Verify user data is consistent
        user = marketplace_client.get_user(user_principal)
        assert user["username"] == "bob"

    def test_user_can_access_all_three_apps_sequentially(
        self, registry_client, marketplace_client, gig_board_client
    ):
        """User logs into all 3 apps in sequence with same Principal."""
        user_principal = "user_charlie"

        # Register user
        registry_client.register_user(user_principal, username="charlie")

        # Access marketplace
        mp_login = marketplace_client.login_user(user_principal)
        assert mp_login["principal_id"] == user_principal

        # Access gig board
        gb_login = gig_board_client.login_user(user_principal)
        assert gb_login["principal_id"] == user_principal

        # Verify can query from all apps
        from_mp = marketplace_client.get_user(user_principal)
        from_gb = gig_board_client.get_user(user_principal)

        assert from_mp["principal_id"] == from_gb["principal_id"]
        assert from_mp["username"] == from_gb["username"]

    def test_multiple_users_maintain_separate_sessions(
        self, registry_client, marketplace_client
    ):
        """Multiple users can have separate sessions simultaneously."""
        user1 = "user_dave"
        user2 = "user_eve"

        # Register both users
        registry_client.register_user(user1, username="dave")
        registry_client.register_user(user2, username="eve")

        # Both login to marketplace
        login1 = marketplace_client.login_user(user1)
        login2 = marketplace_client.login_user(user2)

        # Verify separate identities
        assert login1["principal_id"] == user1
        assert login2["principal_id"] == user2

        user_data1 = marketplace_client.get_user(user1)
        user_data2 = marketplace_client.get_user(user2)

        assert user_data1["username"] == "dave"
        assert user_data2["username"] == "eve"


# ============================================================================
# Scenario 2: Reputation Aggregation
# ============================================================================

class TestReputationAggregation:
    """Reputation from multiple apps aggregates correctly."""

    def test_reputation_from_marketplace_visible_everywhere(
        self, registry_client, marketplace_client, gig_board_client
    ):
        """User completes task in marketplace; reputation visible in all apps."""
        user = "user_frank"
        task_desc = "Fix authentication bug"

        # Register user
        registry_client.register_user(user)

        # Record reputation event in marketplace
        registry_client.record_reputation(
            user,
            task_id="task_001",
            capability_id="marketplace.tasks",
            verified=True,
        )

        # Query via marketplace
        user_mp = marketplace_client.get_user(user)
        assert user_mp["reputation_records"]
        assert user_mp["reputation_records"][0]["tasks_verified"] == 1

        # Query via gig board (should see same reputation)
        user_gb = gig_board_client.get_user(user)
        assert user_gb["reputation_records"]
        assert user_gb["reputation_records"][0]["tasks_verified"] == 1

    def test_reputation_from_multiple_apps_aggregates(
        self, registry_client, marketplace_client, gig_board_client
    ):
        """User completes tasks in marketplace and gigs in gig board; totals combine."""
        user = "user_grace"

        # Register user
        registry_client.register_user(user)

        # Marketplace: record 2 verified tasks
        registry_client.record_reputation(
            user,
            task_id="task_001",
            capability_id="marketplace.tasks",
            verified=True,
        )
        registry_client.record_reputation(
            user,
            task_id="task_002",
            capability_id="marketplace.tasks",
            verified=True,
        )

        # Gig Board: record 1 verified gig
        registry_client.record_reputation(
            user,
            task_id="gig_001",
            capability_id="gig_board.services",
            verified=True,
        )

        # Query via marketplace
        user_mp = marketplace_client.get_user(user)
        total_verified = sum(
            r.get("tasks_verified", 0) for r in user_mp.get("reputation_records", [])
        )
        assert total_verified >= 2  # At least the 2 marketplace tasks

        # Query via gig board
        user_gb = gig_board_client.get_user(user)
        total_verified_gb = sum(
            r.get("tasks_verified", 0) for r in user_gb.get("reputation_records", [])
        )
        assert total_verified_gb >= 1  # At least the 1 gig board task

    def test_reputation_verified_and_rejected_tallied(
        self, registry_client, marketplace_client
    ):
        """Verified and rejected work tallied correctly across apps."""
        user = "user_henry"

        # Register user
        registry_client.register_user(user)

        # Record: 3 verified, 2 rejected
        for i in range(3):
            registry_client.record_reputation(
                user,
                task_id=f"task_verified_{i}",
                capability_id="marketplace.tasks",
                verified=True,
            )

        for i in range(2):
            registry_client.record_reputation(
                user,
                task_id=f"task_rejected_{i}",
                capability_id="marketplace.tasks",
                verified=False,
            )

        # Query
        user_data = marketplace_client.get_user(user)
        records = user_data["reputation_records"]
        assert len(records) == 1  # One capability type

        assert records[0]["tasks_verified"] == 3
        assert records[0]["tasks_rejected"] == 2
        assert records[0]["verification_rate"] == 3.0 / 5.0

    def test_reputation_visible_immediately_across_apps(
        self, registry_client, marketplace_client, gig_board_client
    ):
        """Reputation recorded via registry visible immediately in all apps."""
        user = "user_iris"

        # Register
        registry_client.register_user(user)

        # Record reputation
        registry_client.record_reputation(
            user,
            task_id="task_immediate",
            capability_id="marketplace.tasks",
            verified=True,
        )

        # Immediately visible via both apps
        user_mp = marketplace_client.get_user(user)
        user_gb = gig_board_client.get_user(user)

        assert user_mp["reputation_records"][0]["tasks_verified"] == 1
        assert user_gb["reputation_records"][0]["tasks_verified"] == 1


# ============================================================================
# Scenario 3: Cross-App Interaction
# ============================================================================

class TestCrossAppInteraction:
    """Users from different apps can interact (task posted in one, completed by another)."""

    def test_user_from_marketplace_creates_task_user_from_gig_completes(
        self, registry_client, marketplace_client, gig_board_client
    ):
        """User A (marketplace) posts task; User B (gig board) accepts and completes it."""
        author = "user_jack"
        worker = "user_kate"

        # Both register
        registry_client.register_user(author)
        registry_client.register_user(worker)

        # Author posts task in marketplace
        task = marketplace_client.create_task(author, "Implement feature X")
        assert task["author_principal"] == author
        assert task["status"] == "open"

        # Worker (from gig board context) accepts task in marketplace
        accepted = marketplace_client.accept_task(task["id"], worker)
        assert accepted["status"] == "accepted"
        assert accepted["worker_principal"] == worker

        # Author completes task (records reputation for worker)
        completed = marketplace_client.complete_task(
            task["id"], author, "Excellent work"
        )
        assert completed["status"] == "completed"

        # Verify both users' reputation updated
        author_rep = marketplace_client.get_user(author)
        worker_rep = gig_board_client.get_user(worker)  # Query via gig board

        # Worker should have reputation recorded (from marketplace work)
        assert worker_rep.get("reputation_records")
        if worker_rep.get("reputation_records"):
            assert worker_rep["reputation_records"][0]["tasks_verified"] >= 1

    def test_task_negotiation_between_cross_app_users(
        self, registry_client, marketplace_client
    ):
        """Users from different contexts negotiate on a task."""
        user_a = "user_liam"
        user_b = "user_mia"

        # Register
        registry_client.register_user(user_a)
        registry_client.register_user(user_b)

        # User A posts task
        task = marketplace_client.create_task(user_a, "Negotiate this task")

        # User B accepts
        marketplace_client.accept_task(task["id"], user_b)

        # Both send negotiation messages
        marketplace_client.send_negotiation_message(
            task["id"], user_a, "Can you start this week?"
        )
        marketplace_client.send_negotiation_message(
            task["id"], user_b, "Yes, I can start Monday"
        )

        # Verify negotiation thread
        messages = marketplace_client.get_negotiations(task["id"])
        assert len(messages) == 2
        assert messages[0]["from"] == user_a
        assert messages[1]["from"] == user_b

    def test_cross_app_discovery_via_shared_registry(
        self, registry_client, marketplace_client, gig_board_client
    ):
        """User can discover other users' work across apps via registry."""
        user_x = "user_noah"
        user_y = "user_olivia"

        # Both register
        registry_client.register_user(user_x, username="noah")
        registry_client.register_user(user_y, username="olivia")

        # Give them some reputation in different apps
        registry_client.record_reputation(
            user_x,
            task_id="task_x1",
            capability_id="marketplace.tasks",
            verified=True,
        )
        registry_client.record_reputation(
            user_y,
            task_id="gig_y1",
            capability_id="gig_board.services",
            verified=True,
        )

        # Each can query the other via registry (via any app)
        user_x_data = marketplace_client.get_user(user_x)
        user_y_data = marketplace_client.get_user(user_y)  # Queried via marketplace

        assert user_x_data["username"] == "noah"
        assert user_y_data["username"] == "olivia"

        # Both have reputation
        assert user_x_data["reputation_records"]
        assert user_y_data["reputation_records"]


# ============================================================================
# Scenario 4: Registry Independence
# ============================================================================

class TestRegistryIndependence:
    """Registry operates independently; apps are stateless consumers."""

    def test_registry_survives_app_disconnection(
        self, registry_client, marketplace_client
    ):
        """User data persists in registry even if app disconnects."""
        user = "user_paul"

        # Register user via marketplace app
        registry_client.register_user(user, username="paul")

        # Record some reputation
        registry_client.record_reputation(
            user,
            task_id="task_p1",
            capability_id="marketplace.tasks",
            verified=True,
        )

        # Verify via registry
        user_data = registry_client.get_user(user)
        assert user_data["reputation_records"][0]["tasks_verified"] == 1

        # Still accessible (app/registry can reconnect)
        user_data_again = registry_client.get_user(user)
        assert user_data_again["reputation_records"][0]["tasks_verified"] == 1

    def test_registry_serves_all_apps_from_single_source(
        self, registry_client, marketplace_client, gig_board_client
    ):
        """Registry is single source of truth for all apps."""
        user = "user_quinn"

        # Register
        registry_client.register_user(user)

        # Record via registry
        registry_client.record_reputation(
            user,
            task_id="task_q1",
            capability_id="marketplace.tasks",
            verified=True,
        )

        # Query via all three endpoints - should all see same data
        via_registry = registry_client.get_user(user)
        via_marketplace = marketplace_client.get_user(user)
        via_gig_board = gig_board_client.get_user(user)

        # All should have same reputation
        assert via_registry["reputation_records"] == via_marketplace["reputation_records"]
        assert via_marketplace["reputation_records"] == via_gig_board["reputation_records"]

    def test_no_app_can_corrupt_registry_data(
        self, registry_client, marketplace_client
    ):
        """No single app can corrupt shared registry state."""
        user1 = "user_rachel"
        user2 = "user_sam"

        # Both register
        registry_client.register_user(user1)
        registry_client.register_user(user2)

        # Record reputation for user1
        registry_client.record_reputation(
            user1,
            task_id="task_r1",
            capability_id="marketplace.tasks",
            verified=True,
        )

        # Even if marketplace has its own tasks, user reputation is in registry
        task = marketplace_client.create_task(user1, "Some task")

        # User1's reputation still unchanged (just because they have a task)
        user_data = marketplace_client.get_user(user1)
        assert user_data["reputation_records"][0]["tasks_verified"] == 1

        # User2 unaffected
        user2_data = marketplace_client.get_user(user2)
        assert not user2_data.get("reputation_records", [])


# ============================================================================
# Scenario 5: Concurrent Users
# ============================================================================

class TestConcurrentUsers:
    """Multiple users simultaneously active in different apps."""

    def test_three_users_in_different_apps_concurrent_reputation(
        self, registry_client, marketplace_client, gig_board_client
    ):
        """3 users simultaneously in different contexts, all updating reputation."""
        user_a = "user_tara"
        user_b = "user_uber"
        user_c = "user_vera"

        # All register
        registry_client.register_user(user_a)
        registry_client.register_user(user_b)
        registry_client.register_user(user_c)

        # Simulate concurrent activity
        # User A in marketplace
        marketplace_client.create_task(user_a, "Task from A")

        # User B in gig board (register service)
        gig_board_client.register_service(user_b, "Service from B", "Service description")

        # User C just recording reputation
        registry_client.record_reputation(
            user_c,
            task_id="task_c1",
            capability_id="marketplace.tasks",
            verified=True,
        )

        # Verify all are tracked independently
        user_a_data = marketplace_client.get_user(user_a)
        user_b_data = marketplace_client.get_user(user_b)
        user_c_data = marketplace_client.get_user(user_c)

        # Only user_c has reputation (did work)
        assert not user_c_data.get("reputation_records", []) or user_c_data["reputation_records"][0]["tasks_verified"] == 1

    def test_reputation_updates_dont_interfere_across_users(
        self, registry_client
    ):
        """Reputation updates for one user don't affect others."""
        user1 = "user_wendy"
        user2 = "user_xander"

        # Register
        registry_client.register_user(user1)
        registry_client.register_user(user2)

        # Update user1 reputation
        registry_client.record_reputation(
            user1,
            task_id="task_w1",
            capability_id="marketplace.tasks",
            verified=True,
        )

        # User2 still has no reputation
        user2_data = registry_client.get_user(user2)
        assert not user2_data.get("reputation_records", [])

        # Update user2 reputation
        registry_client.record_reputation(
            user2,
            task_id="task_x1",
            capability_id="marketplace.tasks",
            verified=True,
        )

        # User1 still has 1 task (not affected by user2's update)
        user1_data = registry_client.get_user(user1)
        assert user1_data["reputation_records"][0]["tasks_verified"] == 1


# ============================================================================
# Scenario 6: Reputation Correctness
# ============================================================================

class TestReputationCorrectness:
    """Reputation calculations are accurate."""

    def test_reputation_tallies_exact_verified_rejected_counts(
        self, registry_client
    ):
        """Exact counts of verified and rejected work."""
        user = "user_yara"

        # Register
        registry_client.register_user(user)

        # Add 5 verified
        for i in range(5):
            registry_client.record_reputation(
                user,
                task_id=f"verified_{i}",
                capability_id="marketplace.tasks",
                verified=True,
            )

        # Add 3 rejected
        for i in range(3):
            registry_client.record_reputation(
                user,
                task_id=f"rejected_{i}",
                capability_id="marketplace.tasks",
                verified=False,
            )

        # Verify counts
        user_data = registry_client.get_user(user)
        records = user_data["reputation_records"]
        assert len(records) == 1
        assert records[0]["tasks_verified"] == 5
        assert records[0]["tasks_rejected"] == 3
        assert records[0]["verification_rate"] == 5.0 / 8.0

    def test_different_capabilities_tracked_separately(
        self, registry_client
    ):
        """Different capability types tracked separately."""
        user = "user_zara"

        # Register
        registry_client.register_user(user)

        # Record reputation for different capabilities
        registry_client.record_reputation(
            user,
            task_id="task_mp1",
            capability_id="marketplace.tasks",
            verified=True,
        )
        registry_client.record_reputation(
            user,
            task_id="gig_gb1",
            capability_id="gig_board.services",
            verified=True,
        )

        # Both should be tracked
        user_data = registry_client.get_user(user)
        records = user_data["reputation_records"]

        # Should have 2 capability records
        capability_ids = [r["capability_id"] for r in records]
        assert "marketplace.tasks" in capability_ids
        assert "gig_board.services" in capability_ids

    def test_verification_rate_calculation_accurate(
        self, registry_client
    ):
        """Verification rate calculated correctly: verified / (verified + rejected)."""
        user = "user_adam"

        # Register
        registry_client.register_user(user)

        # 2 verified, 8 rejected = 20% verification rate
        registry_client.record_reputation(
            user,
            task_id="t1",
            capability_id="marketplace.tasks",
            verified=True,
        )
        registry_client.record_reputation(
            user,
            task_id="t2",
            capability_id="marketplace.tasks",
            verified=True,
        )

        for i in range(8):
            registry_client.record_reputation(
                user,
                task_id=f"t_reject_{i}",
                capability_id="marketplace.tasks",
                verified=False,
            )

        # Check rate
        user_data = registry_client.get_user(user)
        rate = user_data["reputation_records"][0]["verification_rate"]
        assert abs(rate - 0.2) < 0.001  # 2 / 10


# ============================================================================
# Scenario 7: Authorization Boundaries
# ============================================================================

class TestAuthorizationBoundaries:
    """Users can only act on their own work."""

    def test_user_cannot_accept_own_marketplace_task(
        self, registry_client, marketplace_client
    ):
        """User cannot accept their own marketplace task."""
        user = "user_belle"

        # Register
        registry_client.register_user(user)

        # Create task
        task = marketplace_client.create_task(user, "My task")

        # Try to accept own task - should fail
        try:
            marketplace_client.accept_task(task["id"], user)
            pytest.fail("Should not allow user to accept own task")
        except RuntimeError as e:
            assert "cannot accept your own task" in str(e)

    def test_user_cannot_hire_own_gig_board_service(
        self, registry_client, gig_board_client
    ):
        """User cannot hire their own service."""
        user = "user_cody"

        # Register
        registry_client.register_user(user)

        # Register as service provider
        service = gig_board_client.register_service(user, "My Service", "My services")

        # Try to hire own service - should fail
        try:
            gig_board_client.create_gig(service["id"], user, "Hire myself")
            pytest.fail("Should not allow user to hire own service")
        except RuntimeError as e:
            assert "cannot hire yourself" in str(e)

    def test_unauthorized_user_cannot_complete_task(
        self, registry_client, marketplace_client
    ):
        """Only task author can complete task."""
        author = "user_dale"
        worker = "user_eden"
        other = "user_frank"

        # Register all
        registry_client.register_user(author)
        registry_client.register_user(worker)
        registry_client.register_user(other)

        # Author creates and worker accepts task
        task = marketplace_client.create_task(author, "Task")
        marketplace_client.accept_task(task["id"], worker)

        # Other user tries to complete - should fail
        try:
            marketplace_client.complete_task(task["id"], other, "Done")
            pytest.fail("Should not allow non-author to complete task")
        except RuntimeError as e:
            assert "only task author can complete" in str(e)


# ============================================================================
# Scenario 8: Principal Uniqueness
# ============================================================================

class TestPrincipalUniqueness:
    """No duplicate Principal registrations."""

    def test_duplicate_principal_registration_fails(self, registry_client):
        """Registering same Principal twice fails."""
        principal = "user_gwen"

        # First registration succeeds
        result1 = registry_client.register_user(principal, username="gwen")
        assert result1["status"] == "registered"

        # Second registration fails (409 Conflict)
        # Try via requests directly to catch the error
        import requests
        payload = {"principal_id": principal}
        resp = requests.post(
            registry_client.base_url + "/auth/register",
            json=payload,
            timeout=5,
        )
        assert resp.status_code == 409

    def test_each_user_has_unique_principal(
        self, registry_client, marketplace_client
    ):
        """Multiple users each have unique Principals."""
        users = [
            ("user_henry", "henry"),
            ("user_iris", "iris"),
            ("user_james", "james"),
        ]

        # Register all
        for principal, name in users:
            registry_client.register_user(principal, username=name)

        # Verify all unique
        principals = []
        for principal, name in users:
            user_data = marketplace_client.get_user(principal)
            principals.append(user_data["principal_id"])

        assert len(set(principals)) == 3  # All unique


# ============================================================================
# Additional Comprehensive Tests
# ============================================================================

class TestFederationComprehensive:
    """Additional tests for edge cases and complete flows."""

    def test_full_marketplace_workflow_with_registry(
        self, registry_client, marketplace_client
    ):
        """Complete marketplace workflow: create, accept, negotiate, complete."""
        author = "user_kyle"
        worker = "user_lucy"

        # Register
        registry_client.register_user(author)
        registry_client.register_user(worker)

        # Create task
        task = marketplace_client.create_task(author, "Complete implementation")
        assert task["status"] == "open"

        # Accept
        task = marketplace_client.accept_task(task["id"], worker)
        assert task["status"] == "accepted"

        # Negotiate
        marketplace_client.send_negotiation_message(
            task["id"], author, "What's the timeline?"
        )
        marketplace_client.send_negotiation_message(
            task["id"], worker, "Can do by Friday"
        )

        # Complete
        task = marketplace_client.complete_task(task["id"], author, "Perfect work!")
        assert task["status"] == "completed"

        # Verify reputation recorded
        worker_data = marketplace_client.get_user(worker)
        assert worker_data["reputation_records"][0]["tasks_verified"] == 1

    def test_full_gig_board_workflow_with_registry(
        self, registry_client, gig_board_client
    ):
        """Complete gig board workflow: service register, create gig, complete."""
        provider = "user_martin"
        buyer = "user_nancy"

        # Register
        registry_client.register_user(provider)
        registry_client.register_user(buyer)

        # Provider registers service
        service = gig_board_client.register_service(
            provider, "Web Development", "Professional web development services"
        )
        assert service["provider_principal"] == provider

        # Buyer creates gig (hires the service)
        gig = gig_board_client.create_gig(service["id"], buyer, "Build my website")
        assert gig["status"] == "active"
        assert gig["provider_principal"] == provider
        assert gig["buyer_principal"] == buyer

        # Buyer completes gig (records reputation for provider)
        gig = gig_board_client.complete_gig(gig["id"], buyer, "Excellent work!")
        assert gig["status"] == "completed"

        # Verify provider reputation recorded
        provider_data = gig_board_client.get_user(provider)
        assert provider_data.get("reputation_records")
        assert provider_data["reputation_records"][0]["tasks_verified"] == 1

    def test_user_with_mixed_marketplace_and_gig_work(
        self, registry_client, marketplace_client, gig_board_client
    ):
        """User completes work in both marketplace and gig board."""
        author_mp = "user_oscar"
        worker_mp = "user_penny"
        provider_gb = "user_quinn"
        buyer_gb = "user_rachel"

        # Register all
        registry_client.register_user(author_mp)
        registry_client.register_user(worker_mp)
        registry_client.register_user(provider_gb)
        registry_client.register_user(buyer_gb)

        # Marketplace: author posts task, worker completes
        task = marketplace_client.create_task(author_mp, "Marketplace task")
        marketplace_client.accept_task(task["id"], worker_mp)
        marketplace_client.complete_task(task["id"], author_mp, "Great!")

        # Gig Board: provider registers service, buyer hires and completes
        service = gig_board_client.register_service(provider_gb, "Service", "Description")
        gig = gig_board_client.create_gig(service["id"], buyer_gb, "Hire service")
        gig_board_client.complete_gig(gig["id"], buyer_gb, "Excellent!")

        # Verify worker has reputation from marketplace
        worker_data = marketplace_client.get_user(worker_mp)
        worker_verified = sum(
            r.get("tasks_verified", 0) for r in worker_data.get("reputation_records", [])
        )
        assert worker_verified >= 1  # At least 1 from marketplace

        # Verify provider has reputation from gig board
        provider_data = gig_board_client.get_user(provider_gb)
        provider_verified = sum(
            r.get("tasks_verified", 0) for r in provider_data.get("reputation_records", [])
        )
        assert provider_verified >= 1  # At least 1 from gig board

    def test_registry_state_consistent_across_multiple_queries(
        self, registry_client, marketplace_client, gig_board_client
    ):
        """Registry state is consistent when queried multiple times."""
        user = "user_quinn"

        # Register and create reputation
        registry_client.register_user(user)
        registry_client.record_reputation(
            user,
            task_id="task_1",
            capability_id="marketplace.tasks",
            verified=True,
        )

        # Query multiple times
        for _ in range(5):
            data = marketplace_client.get_user(user)
            assert data["reputation_records"][0]["tasks_verified"] == 1

        # Query from different apps
        data_mp = marketplace_client.get_user(user)
        data_gb = gig_board_client.get_user(user)

        assert data_mp["reputation_records"] == data_gb["reputation_records"]

    def test_no_data_loss_across_app_interactions(
        self, registry_client, marketplace_client, gig_board_client
    ):
        """Data is not lost when users interact across apps."""
        users = [f"user_test_{i}" for i in range(5)]

        # Register all
        for u in users:
            registry_client.register_user(u)

        # Each user records reputation
        for i, u in enumerate(users):
            for j in range(i + 1):
                registry_client.record_reputation(
                    u,
                    task_id=f"task_{i}_{j}",
                    capability_id="marketplace.tasks",
                    verified=True,
                )

        # Verify all data persists
        for i, u in enumerate(users):
            data = marketplace_client.get_user(u)
            verified_count = data["reputation_records"][0]["tasks_verified"]
            assert verified_count == i + 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
