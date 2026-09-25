from pathlib import Path


SQL = (
    Path(__file__).parents[2]
    / "migrations"
    / "0028_personal_contact_directories.sql"
).read_text()


def test_personal_directory_owner_is_stored_and_unique_per_tenant():
    assert "add column owner_principal_id text" in SQL
    assert "branches_one_personal_root_per_principal" in SQL
    assert "on contacts.branches(tenant_id, owner_principal_id)" in SQL
    assert "where parent_branch_id is null" in SQL


def test_existing_roots_are_backfilled_from_the_initial_owner_grant():
    assert "permission.reason = 'initial directory owner'" in SQL
    assert "permission.dimension = 'administer'" in SQL
