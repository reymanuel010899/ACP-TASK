from pathlib import Path

from tools.migrate import _pending_migrations


MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"
FILENAME = "0012_conversational_concierge.sql"


def test_conversational_concierge_migration_has_identity_and_rls_guards():
    sql = (MIGRATIONS / FILENAME).read_text()

    assert "unique (conversation_id, tenant_id, principal_id)" in sql
    assert "references identity.organizations(organization_id)" in sql
    assert "references identity.principals(principal_id)" in sql
    assert "foreign key (workflow_run_id, workflow_revision_id, tenant_id)" in sql
    assert sql.count("force row level security") == 2
    assert sql.count("current_setting('app.current_org_id', true)") == 4


def test_migration_runner_treats_second_pass_as_a_no_op():
    first = [path.name for path in _pending_migrations(MIGRATIONS, set())]
    assert FILENAME in first

    second = [
        path.name for path in _pending_migrations(MIGRATIONS, set(first))
    ]
    assert second == []
