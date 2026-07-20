"""Pytest configuration for federation tests - loads all fixtures."""

import pytest
from tests.federation.fixtures import (
    registry_data_dir,
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
    "registry_data_dir",
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
