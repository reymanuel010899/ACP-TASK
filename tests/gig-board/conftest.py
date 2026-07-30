"""``tests/gig-board/``-specific fixtures (unit U7).

Mirrors ``tests/marketplace/conftest.py`` exactly, for exactly the same
reason: since unit U7, the Gig Board persists its Service/Gig resources as
``marketplace.tasks`` rows (``apps/gig_board/server/repository.py``) rather
than a fresh in-memory dict per test process. Without a per-test TRUNCATE,
rows a previous test left behind in the same persistent Postgres instance
would make count-based assertions (e.g. ``test_list_services_empty``
expects ``total == 0``) flaky/wrong across repeated runs -- exactly the
problem ``tests/marketplace/conftest.py``'s docstring already describes.

``TRUNCATE ... CASCADE`` on ``marketplace.tasks`` is shared, not
gig-board-specific -- there is no separate ``gig_board`` schema/table (see
the repository module's docstring) -- so this fixture clears the exact same
table ``tests/marketplace/conftest.py`` does. That's fine: pytest runs
tests sequentially by default (no xdist configured -- see ``pytest.ini``),
so truncating before each ``tests/gig-board/`` test only ever clears
whatever a PRIOR, already-finished test left behind, never data a
currently-running test in another directory still needs.
"""

import pytest

from libs.db import Database


@pytest.fixture(autouse=True)
def _clean_marketplace_tables():
    db = Database()
    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE marketplace.tasks CASCADE")
        conn.commit()
    yield
