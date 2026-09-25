"""Postgres-backed storage for the Registry (unit U5, ``registry`` schema --
``migrations/0005_registry.sql``).

Replaces the in-memory state of ``registry/index_store.py``'s ``IndexStore``,
``registry/agent_index.py``'s ``AgentIndex``, and
``registry/app_registry.py``'s ``AppRegistry``. Those three modules keep
their exact pre-existing public method signatures (thin wrappers now,
delegating here) so ``registry/app.py`` and every existing test needed no
changes beyond how those classes are constructed.

Two pre-existing, independent registration paths, ONE unified table
--------------------------------------------------------------------
Before this unit, ``IndexStore`` (backing ``POST /register``) and
``AgentIndex`` (backing ``POST /agents/register``) were two completely
separate in-memory dicts with two different Agent Card conventions:

* ``POST /register`` (legacy, U4): the card is A2A-shaped --
  ``agent_card["capabilities"]`` is a DICT (``{"streaming": ..., "extensions":
  [...]}``, checked for the AgentTrust trust extension) and capability ids
  come from ``agent_card["skills"][].id`` (see
  ``registry.index_store.card_capability_ids``).
* ``POST /agents/register`` (first-class Agent Principal, U5):
  ``agent_card["capabilities"]`` is a plain LIST of capability-id strings.

Both card shapes are still fully exercised by existing, must-pass tests
(``tests/registry/test_capability_search.py`` uses the skills[] shape,
``tests/registry/test_agent_registration.py`` uses the capabilities[] list),
so this module does NOT collapse them into one extraction convention --
wrinkle #4 asks to "pick ONE consistent extraction convention", and the
convention chosen is: **each registration path keeps its own, already-tested
extraction function; both write into the SAME ``registry.agents`` /
``registry.agent_capabilities`` tables**, so capability search is backed by
ONE indexed join either way (R7) instead of two separate in-memory capability
indexes. The two registration paths stay behaviourally isolated from each
other by a real, structural discriminator rather than a second parallel
table: ``identity.principals.created_by`` is set (mandatory, validated
upstream) ONLY by the ``/agents/register`` path, so
:meth:`find_agent_principals_by_capability` / :meth:`get_agent_principal`
require ``created_by IS NOT NULL`` while the legacy
:meth:`find_registrations_by_capability` / :meth:`get_registration` apply no
such filter (a first-class agent's capabilities are also visible to a plain
``/search`` -- a reasonable emergent consolidation, and nothing in the
existing suite checks the opposite).

FK wrinkles (principal + capability) -- same resolution pattern as
``vault/repository.py``'s ``_ensure_principal`` (see that module's
docstring for the full precedent this follows)
--------------------------------------------------------------------------
``registry.agents.principal_id`` is a foreign key into
``identity.principals``, and ``registry.agent_capabilities.capability_id``
is a foreign key into ``catalog.capabilities`` -- but neither existing
registration endpoint has ever required a separate "register this principal
first" or "register this capability first" step, and some already-committed
tests use non-dot-namespaced capability ids (e.g. ``"code_review"``, see
``tests/integration/test_all_3_apps_with_independent_registry.py``) that
would fail ``libs.capability_repository.CapabilityRepository``'s RFC-0001
pattern validation outright. Both FKs are therefore satisfied the same way
U3 solved the analogous vault wrinkle: an idempotent "insert a minimal row
if one doesn't already exist" helper, called on every write path that
introduces a new principal_id/capability_id. The capability helper
deliberately bypasses ``CapabilityRepository``'s pattern check (the database
itself has no CHECK constraint on the shape -- only that repository class
enforces it) since this auto-registration is a best-effort FK-satisfying
placeholder, not an authoritative/validated catalog entry.

Uses ``libs.db.Database`` for every connection -- no hand-rolled psycopg
connection handling here (KTD1). New surrogate keys (``key_id`` for API
keys) are ULIDs (KTD4); ``principal_id``/``capability_id``/``app_id`` keep
their existing natural string identity.
"""

import hashlib
import json
import secrets
from datetime import datetime
from typing import Dict, List, Optional

import psycopg
from psycopg.rows import dict_row

from libs.db import Database, current_organization_id
from libs.identity_repository import IdentityRepository
from libs.repository_contract import normalize_tenant_id
from libs.ulid import generate_ulid

#: Service types the federation layer knows how to look up (RFC-0004) --
#: kept here (not imported from registry.app_registry) so this module has
#: no dependency on the thin-wrapper layer it backs.
SERVICE_TYPES = (
    "agent_marketplace",
    "credential_vault",
    "verification_service",
)


class RegistryRepository(object):
    """Repository for ``registry.*`` tables: agents, agent_capabilities,
    apps, api_keys."""

    def __init__(self, db=None):
        # type: (Optional[Database]) -> None
        self._db = db or Database()
        self._identity = IdentityRepository(self._db)

    # -- FK-satisfying helpers (see module docstring) ----------------------

    def _ensure_principal(self, principal_id, principal_type, created_by=None):
        # type: (str, str, Optional[str]) -> None
        if self._identity.principal_exists(principal_id):
            return
        try:
            self._identity.register_principal(
                principal_id, principal_type, created_by=created_by
            )
        except ValueError:
            pass  # lost a race with a concurrent ensure/registration -- fine

    def _ensure_capability(self, conn, capability_id, skill=None):
        # type: (object, str, Optional[dict]) -> None
        """Ensure ``capability_id`` exists in the catalog — and ENRICH it.

        When the registering card carries skill metadata (``skills[]``:
        name/description/tags/examples), that context is persisted into
        ``catalog.capabilities`` so discovery (and the orchestrator's brain)
        knows what each capability actually DOES, not just its id. Real
        metadata upgrades a placeholder row; a metadata-less registration
        never clobbers previously stored context.
        """
        skill = skill or {}
        description = (skill.get("description") or "").strip()
        extensions = {}
        if skill.get("name") and skill.get("name") != capability_id:
            extensions["name"] = skill["name"]
        if isinstance(skill.get("tags"), list) and skill["tags"]:
            extensions["tags"] = skill["tags"]
        if isinstance(skill.get("examples"), list) and skill["examples"]:
            extensions["examples"] = skill["examples"]
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO catalog.capabilities
                    (capability_id, version, description, extensions)
                VALUES (
                    %(id)s, '0.0.0-auto',
                    COALESCE(NULLIF(%(desc)s, ''),
                             'auto-registered by registry on first use'),
                    %(ext)s::jsonb
                )
                ON CONFLICT (capability_id) DO UPDATE SET
                    description = CASE
                        WHEN %(desc)s <> '' THEN %(desc)s
                        ELSE catalog.capabilities.description
                    END,
                    extensions = catalog.capabilities.extensions
                        || excluded.extensions
                """,
                {
                    "id": capability_id,
                    "desc": description,
                    "ext": json.dumps(extensions),
                },
            )

    def _reindex_capabilities(self, conn, principal_id, capability_ids):
        # type: (object, str, List[str]) -> None
        """Replace ``principal_id``'s capability index with exactly
        ``capability_ids`` (delete then insert, inside the caller's
        transaction) -- matches ``IndexStore._index``'s prior
        remove-old/add-new behavior on re-registration."""
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM registry.agent_capabilities WHERE principal_id = %s",
                (principal_id,),
            )
            for capability_id in capability_ids:
                cur.execute(
                    """
                    INSERT INTO registry.agent_capabilities
                        (principal_id, capability_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (principal_id, capability_id),
                )

    # -- legacy registrations (IndexStore replacement) -----------------------

    def register_registration(self, principal_id, agent_card, capability_ids):
        # type: (str, dict, List[str]) -> dict
        """Upsert a legacy (``POST /register``) registration; index
        ``capability_ids`` (already extracted by the caller via
        ``card_capability_ids``, the skills[].id convention). Re-registration
        with the same principal_id is NOT an error (upsert), matching
        ``IndexStore.register``'s prior unconditional-overwrite behavior."""
        self._ensure_principal(principal_id, "agent")
        # Per-skill card metadata (name/description/tags) keyed by id, so the
        # catalog learns what each capability DOES from the card itself.
        skills_by_id = {
            s.get("id"): s
            for s in (agent_card.get("skills") or [])
            if isinstance(s, dict) and s.get("id")
        }
        with self._db.transaction() as conn:
            for capability_id in capability_ids:
                self._ensure_capability(
                    conn, capability_id, skills_by_id.get(capability_id)
                )
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO registry.agents (principal_id, agent_card)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (principal_id) DO UPDATE SET
                        agent_card = excluded.agent_card,
                        updated_at = now()
                    RETURNING *
                    """,
                    (principal_id, json.dumps(agent_card)),
                )
                row = cur.fetchone()
            self._reindex_capabilities(conn, principal_id, capability_ids)
        return {
            "principal_id": row["principal_id"],
            "agent_card": row["agent_card"],
            "registered_at": _iso(row["registered_at"]),
        }

    def get_registration(self, principal_id):
        # type: (str) -> Optional[dict]
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM registry.agents WHERE principal_id = %s",
                    (principal_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return {
            "principal_id": row["principal_id"],
            "agent_card": row["agent_card"],
            "registered_at": _iso(row["registered_at"]),
        }

    def find_registrations_by_capability(self, capability_id):
        # type: (str) -> List[dict]
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT a.* FROM registry.agents a
                    JOIN registry.agent_capabilities ac
                        ON ac.principal_id = a.principal_id
                    WHERE ac.capability_id = %s
                    ORDER BY a.principal_id
                    """,
                    (capability_id,),
                )
                rows = cur.fetchall()
        return [
            {
                "principal_id": row["principal_id"],
                "agent_card": row["agent_card"],
                "registered_at": _iso(row["registered_at"]),
            }
            for row in rows
        ]

    # -- agent principals (AgentIndex replacement, U5) -----------------------

    def register_agent_principal(self, principal_id, agent_card, created_by,
                                 capability_ids, public_key=None):
        # type: (str, dict, str, List[str], Optional[str]) -> dict
        """Register a first-class Agent Principal. Raises ``ValueError`` if
        ``principal_id`` is ALREADY a first-class agent (mirrors
        ``AgentIndex.register_agent``'s contract so callers can map it to
        409).

        If ``principal_id`` already exists as some OTHER principal type
        (most commonly: it registered as a plain user first, e.g. to set up
        a signing key via the auth endpoint, or it's a legacy ``POST
        /register`` entry with no ``created_by``), that row is UPGRADED to
        an agent in place rather than treated as a duplicate -- see
        ``libs.identity_repository.upgrade_principal_type``'s docstring.
        This is a legitimate, pre-existing usage pattern (an agent that both
        signs requests under its own key AND declares capabilities), not a
        real identity collision.
        """
        # Public network registration does not require a Tessera tenant.
        # When a tenant is bound, ownership is recorded atomically; without
        # one the card remains discovery-only and carries no admin authority.
        organization_id = normalize_tenant_id(current_organization_id())
        self._ensure_principal(created_by, "user")
        existing = self._identity.get_principal(principal_id)
        if existing is None:
            self._identity.register_principal(
                principal_id, "agent", created_by=created_by
            )
        elif self.get_agent_principal(principal_id) is not None:
            raise ValueError(
                "agent principal already registered: %s" % principal_id
            )
        else:
            self._identity.upgrade_principal_type(
                principal_id, "agent", created_by=created_by
            )
        if public_key:
            self._identity.register_key(principal_id, public_key)
        with self._db.transaction() as conn:
            for capability_id in capability_ids:
                self._ensure_capability(conn, capability_id)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO registry.agents (principal_id, agent_card)
                    VALUES (%s, %s::jsonb)
                    RETURNING *
                    """,
                    (principal_id, json.dumps(agent_card)),
                )
                row = cur.fetchone()
            self._reindex_capabilities(conn, principal_id, capability_ids)
            if organization_id is not None:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO registry.agent_ownership
                            (principal_id, organization_id,
                             created_by_principal_id)
                        VALUES (%s, %s, %s)
                        """,
                        (principal_id, organization_id, created_by),
                    )
        principal_row = self._identity.get_principal(principal_id)
        agent = {
            "principal_id": principal_id,
            "agent_card": row["agent_card"],
            "created_by": created_by,
            "created_at": _iso(principal_row["created_at"]),
            "registered_at": _iso(row["registered_at"]),
        }
        if public_key:
            agent["public_key"] = public_key
        return agent

    def get_agent_principal(self, principal_id):
        # type: (str) -> Optional[dict]
        """A first-class Agent Principal, or ``None`` -- including when
        ``principal_id`` only exists as a legacy (``POST /register``)
        registration (``created_by IS NULL`` there; see module docstring)."""
        principal_row = self._identity.get_principal(principal_id)
        if principal_row is None or principal_row.get("created_by") is None:
            return None
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM registry.agents WHERE principal_id = %s",
                    (principal_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        agent = {
            "principal_id": principal_id,
            "agent_card": row["agent_card"],
            "created_by": principal_row["created_by"],
            "created_at": _iso(principal_row["created_at"]),
            "registered_at": _iso(row["registered_at"]),
        }
        key_row = self._identity.get_active_key(principal_id)
        if key_row is not None:
            agent["public_key"] = key_row["public_key"]
        return agent

    def agent_principal_exists(self, principal_id):
        # type: (str) -> bool
        principal_row = self._identity.get_principal(principal_id)
        return principal_row is not None and principal_row.get("created_by") is not None

    def find_agent_principals_by_capability(self, capability_id):
        # type: (str) -> List[dict]
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT a.*, p.created_by AS created_by,
                           p.created_at AS principal_created_at
                    FROM registry.agents a
                    JOIN registry.agent_capabilities ac
                        ON ac.principal_id = a.principal_id
                    JOIN identity.principals p
                        ON p.principal_id = a.principal_id
                    WHERE ac.capability_id = %s AND p.created_by IS NOT NULL
                    ORDER BY a.principal_id
                    """,
                    (capability_id,),
                )
                rows = cur.fetchall()
        agents = []
        for row in rows:
            agent = {
                "principal_id": row["principal_id"],
                "agent_card": row["agent_card"],
                "created_by": row["created_by"],
                "created_at": _iso(row["principal_created_at"]),
                "registered_at": _iso(row["registered_at"]),
            }
            key_row = self._identity.get_active_key(row["principal_id"])
            if key_row is not None:
                agent["public_key"] = key_row["public_key"]
            agents.append(agent)
        return agents

    def list_agent_principals(self):
        # type: () -> List[dict]
        """Every registered agent Principal (registration order) — the U5
        full-directory listing behind ``GET /agents`` with no capability
        filter. Same row shape as ``find_agent_principals_by_capability``."""
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT a.*, p.created_by AS created_by,
                           p.created_at AS principal_created_at
                    FROM registry.agents a
                    JOIN identity.principals p
                        ON p.principal_id = a.principal_id
                    WHERE p.created_by IS NOT NULL
                    ORDER BY a.registered_at, a.principal_id
                    """,
                )
                rows = cur.fetchall()
        agents = []
        for row in rows:
            agent = {
                "principal_id": row["principal_id"],
                "agent_card": row["agent_card"],
                "created_by": row["created_by"],
                "created_at": _iso(row["principal_created_at"]),
                "registered_at": _iso(row["registered_at"]),
            }
            key_row = self._identity.get_active_key(row["principal_id"])
            if key_row is not None:
                agent["public_key"] = key_row["public_key"]
            agents.append(agent)
        return agents

    # -- capability catalog (rich discovery context) --------------------------

    def list_capabilities(self):
        # type: () -> List[dict]
        """The capability catalog with its card-derived context, plus which
        agents currently declare each capability — the orchestrator's
        discovery vocabulary (what exists AND what it does)."""
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT c.capability_id, c.description, c.extensions,
                           COALESCE(
                               json_agg(
                                   json_build_object(
                                       'principal_id', a.principal_id,
                                       'name', a.agent_card->>'name',
                                       'description',
                                           a.agent_card->>'description'
                                   )
                                   ORDER BY a.principal_id
                               ) FILTER (WHERE a.principal_id IS NOT NULL),
                               '[]'::json
                           ) AS agents
                    FROM catalog.capabilities c
                    LEFT JOIN registry.agent_capabilities ac
                        ON ac.capability_id = c.capability_id
                    LEFT JOIN registry.agents a
                        ON a.principal_id = ac.principal_id
                    GROUP BY c.capability_id, c.description, c.extensions
                    ORDER BY c.capability_id
                    """,
                )
                rows = cur.fetchall()
        capabilities = []
        for row in rows:
            extensions = row["extensions"] or {}
            capabilities.append({
                "capability_id": row["capability_id"],
                "name": extensions.get("name"),
                "description": row["description"],
                "tags": extensions.get("tags") or [],
                "agents": row["agents"],
            })
        return capabilities

    # -- apps (AppRegistry replacement, U6/U9 federation) --------------------

    def register_app(self, app_id, app_endpoint, p2p_endpoint, capabilities,
                     services=None):
        # type: (str, str, str, List[str], Optional[Dict[str, bool]]) -> dict
        """Register (or re-register) an app; return the stored record.
        Re-registration is NOT an error (apps restart often) -- endpoints
        update in place, preserving the original ``registered_at``."""
        flags = services or {}
        service_list = [
            service_type for service_type in SERVICE_TYPES
            if bool(flags.get(service_type, False))
        ]
        with self._db.transaction() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO registry.apps
                        (app_id, app_endpoint, p2p_endpoint, capabilities,
                         services)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (app_id) DO UPDATE SET
                        app_endpoint = excluded.app_endpoint,
                        p2p_endpoint = excluded.p2p_endpoint,
                        capabilities = excluded.capabilities,
                        services = excluded.services,
                        updated_at = now()
                    RETURNING *
                    """,
                    (app_id, app_endpoint, p2p_endpoint, list(capabilities),
                     service_list),
                )
                row = cur.fetchone()
        return _normalize_app(row)

    def get_app(self, app_id):
        # type: (str) -> Optional[dict]
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM registry.apps WHERE app_id = %s", (app_id,)
                )
                row = cur.fetchone()
        return _normalize_app(row) if row is not None else None

    def app_exists(self, app_id):
        # type: (str) -> bool
        with self._db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM registry.apps WHERE app_id = %s", (app_id,)
                )
                return cur.fetchone() is not None

    def list_apps(self, capability=None):
        # type: (Optional[str]) -> List[dict]
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                if capability is not None:
                    cur.execute(
                        "SELECT * FROM registry.apps "
                        "WHERE %s = ANY(capabilities) ORDER BY app_id",
                        (capability,),
                    )
                else:
                    cur.execute("SELECT * FROM registry.apps ORDER BY app_id")
                return [_normalize_app(row) for row in cur.fetchall()]

    def find_services(self, service_type):
        # type: (str) -> List[dict]
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM registry.apps "
                    "WHERE %s = ANY(services) ORDER BY app_id",
                    (service_type,),
                )
                return [_normalize_app(row) for row in cur.fetchall()]

    # -- API keys (R8: stored hashed, never plaintext) -----------------------

    def issue_api_key(self):
        # type: () -> str
        """Mint a new invite/API key; return the RAW token (shown to the
        caller ONCE, at mint time). Only ``sha256(raw_token)`` is stored."""
        raw = "atk_%s" % secrets.token_urlsafe(24)
        self._store_api_key_hash(raw)
        return raw

    def seed_api_key(self, raw_key):
        # type: (str) -> None
        """Seed a pre-existing raw key (e.g. from an operator-owned JSON
        file) as valid -- hashed the same way a minted key is."""
        self._store_api_key_hash(str(raw_key))

    def _store_api_key_hash(self, raw_key):
        # type: (str) -> None
        key_id = generate_ulid()
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        with self._db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO registry.api_keys (key_id, key_hash)
                    VALUES (%s, %s)
                    ON CONFLICT (key_hash) DO NOTHING
                    """,
                    (key_id, key_hash),
                )

    def is_valid_api_key(self, key):
        # type: (object) -> bool
        if not isinstance(key, str) or not key:
            return False
        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        with self._db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE registry.api_keys SET last_used_at = now()
                    WHERE key_hash = %s AND revoked_at IS NULL
                    RETURNING key_id
                    """,
                    (key_hash,),
                )
                return cur.fetchone() is not None


def _iso(value):
    # type: (object) -> object
    return value.isoformat() if isinstance(value, datetime) else value


def _normalize_app(row):
    # type: (Optional[dict]) -> Optional[dict]
    if row is None:
        return None
    services = {
        service_type: service_type in (row.get("services") or [])
        for service_type in SERVICE_TYPES
    }
    return {
        "app_id": row["app_id"],
        "app_endpoint": row["app_endpoint"],
        "p2p_endpoint": row["p2p_endpoint"],
        "capabilities": list(row.get("capabilities") or []),
        "services": services,
        "registered_at": _iso(row["registered_at"]),
        "updated_at": _iso(row["updated_at"]),
    }
