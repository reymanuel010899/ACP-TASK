"""Shared Postgres access layer (unit U1).

The one place every service gets a pooled connection, a transaction context
manager, and a way to set the Row-Level-Security org-context GUC
(``app.current_org_id``) for the lifetime of a request-scoped transaction.
Raw SQL only, via psycopg (KTD1) -- no ORM, no query builder, matching this
codebase's existing 100%-stdlib, framework-free convention (see
``registry/app.py``, ``vault/app.py``: plain ``http.server.ThreadingHTTPServer``,
no web framework).

Environment variables
----------------------
``DATABASE_URL``
    A libpq/psycopg connection string, e.g.::

        postgresql://registry_svc:password@localhost:5432/agenttrust

    Every service is expected to connect with its own least-privilege role
    (``registry_svc``, ``vault_svc``, ``audit_svc``, ``trust_svc``,
    ``marketplace_svc`` -- see ``infra/roles.sql``). The migration runner
    (``tools/migrate.py``) and ``infra/roles.sql`` itself connect with a
    separate owner/admin DSN instead (e.g. the ``postgres`` superuser in
    ``infra/docker-compose.yml``) -- that owner role is never the one a
    service uses at runtime, so RLS (U2, U9) actually binds on every
    connection an application makes.

``REDIS_URL``
    A redis-py connection string, e.g. ``redis://localhost:6379/0``, for the
    deliberately-ephemeral state described in the design doc. This module
    only wraps Postgres; callers reach Redis directly via
    ``redis.from_url(os.environ["REDIS_URL"])`` (KTD1's "no extra layer"
    applies here too -- there's nothing Postgres-specific to abstract).

Usage
-----
::

    from libs.db import Database

    db = Database()  # reads DATABASE_URL, or pass dsn= explicitly

    with db.connection() as conn:
        conn.execute("select 1")

    with db.transaction() as conn:
        db.set_org_context(conn, organization_id)
        conn.execute("insert into registry.agents (...) values (...)")
    # transaction commits (or rolls back on exception) on context exit;
    # app.current_org_id resets automatically since it was SET LOCAL.
"""

import os
import threading
from contextlib import contextmanager
from typing import Optional

from psycopg_pool import ConnectionPool

#: Local-dev fallback, matching infra/docker-compose.yml's defaults. Real
#: deployments always set DATABASE_URL explicitly; this only saves typing
#: when running against the docker-compose stack locally.
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/agenttrust"

#: Request-scoped org context (unit U9). Every service's HTTP request
#: entrypoint (``do_GET``/``do_POST``/... in ``registry/app.py``,
#: ``vault/app.py``, ``apps/marketplace/server/app.py``, ``audit/app.py``,
#: ``agent_marketplace/app.py``) calls :func:`bind_organization_id` ONCE, as
#: the first thing it does, before dispatching into any repository method.
#: :meth:`Database.connection` / :meth:`Database.transaction` then apply
#: whatever value is currently bound automatically, via :meth:`Database.
#: set_org_context`, on every connection/transaction they check out --
#: existing repository code (already committed in U2-U8) needed NO changes
#: to participate in RLS, since the org-context setter now happens at the
#: one choke point every repository call already passes through, rather
#: than threading an organization_id parameter through ~100 existing
#: repository method signatures across five services.
#:
#: A plain ``threading.local`` (not a ``contextvars.ContextVar``) is
#: deliberate: every service here is a stdlib ``http.server.
#: ThreadingHTTPServer`` (``daemon_threads = True``), which hands each
#: accepted connection its own OS thread for the lifetime of that
#: connection (``ThreadingMixIn.process_request_thread``) -- contextvars are
#: NOT automatically propagated into a freshly spawned ``threading.Thread``
#: the way they would be into a child ``asyncio`` task, so a thread-local is
#: the construct that actually matches this concurrency model. Because the
#: request entrypoint re-binds this on every single request (see below), a
#: keep-alive connection that serves several requests on the same thread
#: never leaks one request's org context into the next.
_org_context = threading.local()


def bind_organization_id(organization_id: Optional[str]) -> None:
    """Bind the ``organization_id`` in effect for the remainder of request
    handling on the *current thread* (U9's per-request org-context setter).

    Call this once per request, before touching any tenant-scoped table --
    every later :meth:`Database.connection` / :meth:`Database.transaction`
    on this thread will apply it automatically. Pass ``None`` (the default
    for a request that carries no org context at all -- e.g. an anonymous
    or solo/unaffiliated caller) to explicitly clear any value a prior
    request handled on this same thread may have bound; callers MUST NOT
    skip calling this just because the value is ``None`` -- an omitted call
    would leave a *previous* request's bound value in place for a
    thread reused across keep-alive requests.
    """
    _org_context.value = organization_id or None


def current_organization_id() -> Optional[str]:
    """The ``organization_id`` currently bound on this thread via
    :func:`bind_organization_id`, or ``None`` if none has been bound (the
    default for any thread that never called it -- e.g. a test or script
    using :class:`Database` directly, outside of any HTTP request)."""
    return getattr(_org_context, "value", None)


class Database:
    """Pooled Postgres access: one instance per process, shared by a service.

    Wraps :class:`psycopg_pool.ConnectionPool`. Construct once at service
    startup (not per-request) and reuse; the pool itself manages acquiring
    and returning individual connections.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        min_size: int = 1,
        max_size: int = 10,
        open: bool = True,
    ):
        self.dsn = dsn or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
        self._pool = ConnectionPool(
            self.dsn,
            min_size=min_size,
            max_size=max_size,
            open=open,
            kwargs={"autocommit": False},
        )

    def open(self) -> None:
        """Open the pool if it was constructed with ``open=False``."""
        self._pool.open()

    def close(self) -> None:
        """Release all pooled connections. Call on service shutdown."""
        self._pool.close()

    @contextmanager
    def connection(self):
        """Yield a pooled connection for ad-hoc use (no transaction semantics
        beyond psycopg's own per-statement autocommit=False behavior --
        callers that need atomicity across statements should use
        :meth:`transaction` instead).

        Applies whatever ``organization_id`` is currently bound via
        :func:`bind_organization_id` (U9) before yielding, so every RLS
        policy keyed on ``app.current_org_id`` sees the right value for the
        request this connection was checked out to serve -- unconditionally,
        including the "no org context" case (``None``), so a pooled
        connection can never carry over a stale value from whichever
        request last used it.
        """
        with self._pool.connection() as conn:
            self.set_org_context(conn, current_organization_id())
            yield conn

    @contextmanager
    def transaction(self):
        """Yield a connection with an explicit transaction: commits on clean
        exit, rolls back if the ``with`` block raises. This is what the
        migration runner and every repository's multi-statement writes
        should use.

        Same automatic org-context application as :meth:`connection` (U9),
        applied first, before the caller's own statements run.
        """
        with self._pool.connection() as conn:
            with conn.transaction():
                self.set_org_context(conn, current_organization_id())
                yield conn

    def set_org_context(self, conn, organization_id: Optional[str]) -> None:
        """Set ``app.current_org_id`` for the remainder of the *current*
        transaction on ``conn`` (RLS org-context setter, per the design doc's
        ``current_setting('app.current_org_id', true)`` policy pattern).

        Must be called inside an open transaction (e.g. within a
        :meth:`transaction` block) -- it uses Postgres's ``set_config(...,
        is_local => true)``, the parameterized equivalent of ``SET LOCAL``,
        which resets automatically on commit/rollback. That is what makes
        this safe to call once per request on a *pooled* connection: the
        setting can never leak into a later request that reuses the same
        physical connection after this transaction ends.

        Pass ``organization_id=None`` for a principal with no
        ``home_organization_id`` (the solo/unaffiliated case, U9) -- this
        clears the setting for the transaction rather than leaving a stale
        value from a previous use of the pooled connection.
        """
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.current_org_id', %s, true)",
                (organization_id or "",),
            )
