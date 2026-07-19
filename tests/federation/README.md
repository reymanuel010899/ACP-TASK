# Federation End-to-End Test Suite (Phase A)

Comprehensive test suite proving the AgentTrust federated ecosystem works end-to-end.

## Overview

This test suite validates that 3 independent web applications (Console via Registry, Marketplace, Gig Board) can coexist on the same AgentTrust federation protocol, with users maintaining portable identity and reputation flowing correctly across all apps.

**Test Coverage:** 25+ tests across 8 scenario groups

## Running the Tests

### Prerequisites

- Python 3.8+
- `pytest` installed
- Registry, Marketplace, and Gig Board apps available (in-process fixtures start them)

### Run All Federation Tests

```bash
# Run all tests with verbose output
pytest tests/federation/ -v

# Run with detailed output and short traceback
pytest tests/federation/ -v --tb=short

# Run with even more detail
pytest tests/federation/ -vv --tb=long
```

### Run Specific Test Scenarios

```bash
# Run only User Portability tests
pytest tests/federation/test_phase_a_complete.py::TestUserPortability -v

# Run only Reputation Aggregation tests
pytest tests/federation/test_phase_a_complete.py::TestReputationAggregation -v

# Run only Cross-App Interaction tests
pytest tests/federation/test_phase_a_complete.py::TestCrossAppInteraction -v

# Run only Registry Independence tests
pytest tests/federation/test_phase_a_complete.py::TestRegistryIndependence -v

# Run only Concurrent Users tests
pytest tests/federation/test_phase_a_complete.py::TestConcurrentUsers -v

# Run only Reputation Correctness tests
pytest tests/federation/test_phase_a_complete.py::TestReputationCorrectness -v

# Run only Authorization Boundaries tests
pytest tests/federation/test_phase_a_complete.py::TestAuthorizationBoundaries -v

# Run only Principal Uniqueness tests
pytest tests/federation/test_phase_a_complete.py::TestPrincipalUniqueness -v

# Run only Comprehensive tests
pytest tests/federation/test_phase_a_complete.py::TestFederationComprehensive -v
```

### Run Specific Individual Tests

```bash
# Example: Run a single test
pytest tests/federation/test_phase_a_complete.py::TestUserPortability::test_user_register_in_registry_login_everywhere -v
```

## Test Structure

### Test File Organization

```
tests/federation/
├── __init__.py                   # Package initialization
├── fixtures.py                   # Shared fixtures for all tests
├── test_phase_a_complete.py      # Main test suite (25+ tests)
└── README.md                     # This file
```

### Fixtures (`fixtures.py`)

Provides:

- **`registry_server`** — Starts an in-process registry server on a free port
- **`marketplace_server`** — Starts an in-process marketplace server connected to registry
- **`gig_board_server`** — Starts an in-process gig board server connected to registry
- **`registry_client`** — HTTP client for registry operations
- **`marketplace_client`** — HTTP client for marketplace operations
- **`gig_board_client`** — HTTP client for gig board operations
- **`all_apps`** — Dict with all 3 server URLs
- **`all_clients`** — Dict with all 3 app clients

Each fixture automatically:
1. Starts the server on a free port
2. Waits for it to become ready (healthz check)
3. Cleans up after the test completes

### Test Scenarios

#### 1. **User Portability** (4 tests)

Validates that users can maintain the same Principal across all 3 apps:

```python
TestUserPortability::
  ✓ test_user_register_in_registry_login_everywhere
  ✓ test_user_session_persists_across_app_restarts
  ✓ test_user_can_access_all_three_apps_sequentially
  ✓ test_multiple_users_maintain_separate_sessions
```

**What it proves:** A user can register once with a Principal and log into all 3 apps without re-registering.

#### 2. **Reputation Aggregation** (4 tests)

Validates that reputation from multiple apps combines correctly:

```python
TestReputationAggregation::
  ✓ test_reputation_from_marketplace_visible_everywhere
  ✓ test_reputation_from_multiple_apps_aggregates
  ✓ test_reputation_verified_and_rejected_tallied
  ✓ test_reputation_visible_immediately_across_apps
```

**What it proves:** Work completed in one app (e.g., Marketplace tasks) is visible as reputation across all apps (Gig Board, Console).

#### 3. **Cross-App Interaction** (3 tests)

Validates users from different apps can interact:

```python
TestCrossAppInteraction::
  ✓ test_user_from_marketplace_creates_task_user_from_gig_completes
  ✓ test_task_negotiation_between_cross_app_users
  ✓ test_cross_app_discovery_via_shared_registry
```

**What it proves:** A user in Marketplace can post a task, a user in Gig Board can accept and complete it, and both users' reputation updates.

#### 4. **Registry Independence** (3 tests)

Validates registry operates as a standalone, shared service:

```python
TestRegistryIndependence::
  ✓ test_registry_survives_app_disconnection
  ✓ test_registry_serves_all_apps_from_single_source
  ✓ test_no_app_can_corrupt_registry_data
```

**What it proves:** The registry is a neutral third party; apps don't own the data, they just consume it.

#### 5. **Concurrent Users** (2 tests)

Validates multiple simultaneous users don't interfere:

```python
TestConcurrentUsers::
  ✓ test_three_users_in_different_apps_concurrent_reputation
  ✓ test_reputation_updates_dont_interfere_across_users
```

**What it proves:** 3 users can be active in different apps simultaneously without data loss or corruption.

#### 6. **Reputation Correctness** (3 tests)

Validates reputation calculations are accurate:

```python
TestReputationCorrectness::
  ✓ test_reputation_tallies_exact_verified_rejected_counts
  ✓ test_different_capabilities_tracked_separately
  ✓ test_verification_rate_calculation_accurate
```

**What it proves:** Verified/rejected counts and verification rates are calculated correctly.

#### 7. **Authorization Boundaries** (3 tests)

Validates users can only act on their own work:

```python
TestAuthorizationBoundaries::
  ✓ test_user_cannot_accept_own_marketplace_task
  ✓ test_user_cannot_accept_own_gig_board_gig
  ✓ test_unauthorized_user_cannot_complete_task
```

**What it proves:** No user can cheat by accepting their own work or someone else's work.

#### 8. **Principal Uniqueness** (2 tests)

Validates no duplicate Principals:

```python
TestPrincipalUniqueness::
  ✓ test_duplicate_principal_registration_fails
  ✓ test_each_user_has_unique_principal
```

**What it proves:** Each user has a unique, non-duplicate Principal in the registry.

#### 9. **Comprehensive Workflows** (5 tests)

Full end-to-end workflows combining multiple scenarios:

```python
TestFederationComprehensive::
  ✓ test_full_marketplace_workflow_with_registry
  ✓ test_full_gig_board_workflow_with_registry
  ✓ test_user_with_mixed_marketplace_and_gig_work
  ✓ test_registry_state_consistent_across_multiple_queries
  ✓ test_no_data_loss_across_app_interactions
```

**What it proves:** Complete, complex workflows work end-to-end.

## Test Execution Flow

Each test follows this pattern:

1. **Setup**
   - Fixtures start registry and app servers
   - Fixtures create HTTP clients to communicate

2. **Execute**
   - Test registers users, creates content, interacts
   - Test queries data from registry and apps

3. **Verify**
   - Test assertions check expected state
   - Test may query multiple apps to verify consistency

4. **Cleanup**
   - Fixtures automatically shut down servers
   - Temporary data directories cleaned up

## Example Test Walkthrough

### User Portability Test

```python
def test_user_register_in_registry_login_everywhere(
    registry_client, marketplace_client, gig_board_client
):
    """User registers in registry, then logs in to marketplace and gig board."""
    user_principal = "user_alice"

    # SETUP: Register user in registry
    user = registry_client.register_user(user_principal, username="alice")
    assert user["status"] == "registered"

    # EXECUTE: User logs in via marketplace
    login_mp = marketplace_client.login_user(user_principal)
    assert login_mp["principal_id"] == user_principal

    # VERIFY: User can access all apps
    user_via_mp = marketplace_client.get_user(user_principal)
    user_via_gb = gig_board_client.get_user(user_principal)

    assert user_via_mp["principal_id"] == user_via_gb["principal_id"]
```

## Key Assertions

Tests validate:

- **Status codes** — HTTP responses are correct (200, 400, 404, 409, etc.)
- **User data** — Principals, usernames, metadata persist correctly
- **Reputation** — Verified/rejected counts, rates are accurate
- **State consistency** — Same query from different apps returns same data
- **Authorization** — Only authorized users can complete work
- **No data loss** — Updates don't get lost under concurrent access

## Troubleshooting

### Tests fail with "Server did not start"

Check that free ports are available:
```bash
# Check for port conflicts
netstat -tulpn | grep -E '800[0-2]'
```

### Tests timeout

Increase the `wait_for_server()` attempts in `fixtures.py`:
```python
wait_for_server(url, max_attempts=100)  # Default is 50
```

### Tests fail with "registry unreachable"

Ensure the registry is started before apps try to connect. This is handled automatically by the fixtures' dependency order (registry starts first, then apps).

### Individual test fails but suite passes

Some tests are independent. Run failed test in isolation:
```bash
pytest tests/federation/test_phase_a_complete.py::TestUserPortability::test_user_register_in_registry_login_everywhere -vv
```

## Integration with CI/CD

The test suite is designed to run in CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Run Federation Tests
  run: |
    pytest tests/federation/ -v --tb=short --junit-xml=results.xml
```

## Coverage Metrics

Running with coverage:

```bash
pytest tests/federation/ --cov=apps --cov=registry -v
```

This measures code coverage for:
- `apps/marketplace/` — Marketplace app
- `apps/gig-board/` — Gig Board app
- `registry/` — Registry core

## Performance Considerations

- **Startup:** Each test creates fresh servers (~1s per test)
- **Parallelization:** Tests can run in parallel with pytest-xdist:
  ```bash
  pytest tests/federation/ -n auto
  ```
- **Memory:** In-process servers use ~50MB per instance

## Phase A Success Criteria

This test suite proves Phase A is complete when:

- ✅ All 25+ tests pass
- ✅ Users can register once and log into all 3 apps
- ✅ Reputation flows between apps correctly
- ✅ Cross-app interaction works (task posted in one app, completed by user in another)
- ✅ Registry operates independently
- ✅ Concurrent users don't interfere with each other
- ✅ Authorization boundaries are enforced

## Next Steps (Phase B)

Future improvements:
- Load testing under high concurrency
- Stress testing (rapid user registration, reputation updates)
- Chaos engineering (simulated server failures)
- Performance optimization (caching, batching)
- Advanced search/discovery
- User key recovery flows

## References

- **Plan:** `docs/plans/2026-07-18-002-feat-phase-a-federation-3-apps-plan.md`
- **Registry:** `registry/app.py`
- **Marketplace:** `apps/marketplace/server/app.py`
- **Gig Board:** `apps/gig-board/server/app.py`
- **User Endpoints:** `registry/user_index.py`
