"""``tests/marketplace/``-specific fixtures (unit U6).

The root ``tests/conftest.py`` already truncates the shared identity/catalog/
registry-apps tables before every test in the whole suite (see its
docstring). ``marketplace.*`` is this directory's OWN persisted state (unit
U6, ``apps/marketplace/server/repository.py``) -- mirroring the narrower
per-schema fixtures ``tests/vault/`` and ``tests/audit/`` already keep for
their own schemas rather than growing the shared root fixture further.

Without this, ``TRUNCATE`` never runs on ``marketplace.tasks`` between
tests, and several existing tests assert an exact task *count* (e.g.
``test_list_tasks_empty`` expects ``total == 0``, ``test_list_tasks_with_
pagination`` expects exactly the 5 tasks it just created) -- rows a
previous test left behind in the same persistent Postgres instance would
make those assertions flaky/wrong across repeated runs, even though
task/bid ids themselves (random per test) never collide.

``TRUNCATE ... CASCADE`` on ``marketplace.tasks`` alone is enough for U6/U7's
tables: every other marketplace table those units introduced (``offers``,
``counter_offers``, ``bids``, ``negotiation_messages``, ``work_results``) has
an ``ON DELETE CASCADE`` FK back to it, and Postgres's ``TRUNCATE ...
CASCADE`` additionally truncates every table with a live FK reference to the
target, not just cascading deletes within already-inserted rows.

Unit U8's tables (``hiring_grants``, ``ratings``, ``rating_summary``) are
NOT reachable that way -- ``agent_marketplace``'s hiring grants and ratings
have no FK relationship to ``marketplace.tasks`` at all (they key off
``identity.principals`` directly, same as ``marketplace.tasks`` does, but
never off a task row). ``hiring_grants`` is truncated explicitly instead;
``TRUNCATE ... CASCADE`` on it in turn covers ``grant_capabilities`` and
``grant_credential_scopes`` (both FK ``hiring_grants`` with ``ON DELETE
CASCADE``). ``ratings``/``rating_summary`` have no FK relationship to
``hiring_grants`` either (a rating only requires having hired the agent at
SOME point in the past -- see ``agent_marketplace/app.py``'s ``rate_agent``
-- it is not itself a child row of a grant), so both are truncated
explicitly too. Several tests in ``tests/marketplace/test_agent_hiring.py``
assert exact rating/grant counts (e.g. ``rating_count == 1`` right after the
very first rating for a fresh agent) that would be flaky/wrong across
repeated runs against the same persistent Postgres instance without this.
"""

import pytest

from libs.db import Database


@pytest.fixture(autouse=True)
def _clean_marketplace_tables():
    db = Database()
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE marketplace.tasks CASCADE")
            cur.execute("TRUNCATE TABLE marketplace.hiring_grants CASCADE")
            cur.execute("TRUNCATE TABLE marketplace.ratings CASCADE")
            cur.execute("TRUNCATE TABLE marketplace.rating_summary CASCADE")
        conn.commit()
    yield
