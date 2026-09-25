"""Tenant context shared by Registry administrative registration tests."""

import pytest

from libs.db import Database, bind_organization_id
from libs.identity_repository import IdentityRepository


REGISTRY_TEST_ORGANIZATION_ID = "org:test-registry-suite"


@pytest.fixture(autouse=True)
def _registry_tenant_context():
    db = Database()
    identity = IdentityRepository(db)
    bind_organization_id(REGISTRY_TEST_ORGANIZATION_ID)
    if not identity.organization_exists(REGISTRY_TEST_ORGANIZATION_ID):
        identity.create_organization(
            REGISTRY_TEST_ORGANIZATION_ID,
            "Registry Test Suite",
        )
    try:
        yield
    finally:
        bind_organization_id(None)
