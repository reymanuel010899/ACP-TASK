"""Pytest configuration for federation tests - loads all fixtures.

The shared-identity-table truncation this suite needs (since U5, Registry
persists to Postgres and this suite registers literal, fixed principal_ids
like ``"user_quinn"``) now lives once, globally, in the root
``tests/conftest.py`` — see that module's docstring.
"""

from tests.federation.fixtures import (
    registry_service,
    registry_server,
    marketplace_server,
    gig_board_server,
    registry_client,
    marketplace_client,
    gig_board_client,
    all_apps,
    all_clients,
)

# Re-export all fixtures so pytest discovers them
__all__ = [
    "registry_service",
    "registry_server",
    "marketplace_server",
    "gig_board_server",
    "registry_client",
    "marketplace_client",
    "gig_board_client",
    "all_apps",
    "all_clients",
]
