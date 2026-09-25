"""Persistent state for multi-turn collaboration with one selected agent.

The store deliberately owns no LLM or transport.  It records enough context
to resume a typed agent need without repeating discovery, resolves facts in a
fixed order, and invokes an injected ``task.continue`` sender idempotently.
"""

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from libs.db import current_organization_id

from libs.protocol import (
    TASK_CONTINUE,
    TASK_NEEDS_APPROVAL,
    TASK_NEEDS_PERMISSION,
    validate_collaboration_envelope,
)


DEFAULT_TIMEOUT_SECONDS = 1800


def _json(value):
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def _field_label(field):
    labels = {
        "contact": "contacto",
        "duration": "duración",
        "start_time": "hora de inicio",
        "time": "hora",
    }
    return labels.get(field, field.replace("_", " "))


def _permission_label(permission):
    labels = {
        "contacts.read": "tus contactos",
        "profile.read": "tu perfil",
        "provider.read": "los datos de tu proveedor",
    }
    return labels.get(permission, permission.replace(".", " "))


class ConversationStateStore(object):
    """SQLite-backed task conversation state with deterministic resolution."""

    def __init__(
        self,
        database_path=":memory:",
        clock=None,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    ):
        self.clock = clock or time.time
        self.timeout_seconds = int(timeout_seconds)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            database_path, check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS orchestrator_conversations (
                task_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL UNIQUE,
                agent_id TEXT NOT NULL,
                capability TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            )
            """
        )

    def close(self):
        with self._lock:
            self._connection.close()

    def create_task(
        self,
        task_id,
        agent_id,
        capability,
        conversation_id=None,
        known_inputs=None,
        permissions=None,
        answers=None,
        preferences=None,
    ):
        """Create once, or merge context into the same task/agent identity."""
        if not all(
            isinstance(value, str) and value
            for value in (task_id, agent_id, capability)
        ):
            raise ValueError("task_id, agent_id and capability are required")
        conversation_id = conversation_id or task_id
        now = int(self.clock())
        with self._lock:
            current = self._load(task_id)
            if current is not None:
                if self._expire_if_needed(current):
                    raise TimeoutError("task conversation expired")
                if (
                    current["agent_id"] != agent_id
                    or current["capability"] != capability
                    or current["conversation_id"] != conversation_id
                ):
                    raise ValueError(
                        "an existing task cannot change agent, capability, "
                        "or conversation"
                    )
                state = current
                for key, incoming in (
                    ("known_inputs", known_inputs),
                    ("permissions", permissions),
                    ("answers", answers),
                    ("preferences", preferences),
                ):
                    if incoming:
                        state[key].update(dict(incoming))
                state["status"] = "active"
                self._save(state, now, now + self.timeout_seconds)
                return self.get_task(task_id)

            state = {
                "task_id": task_id,
                "conversation_id": conversation_id,
                "agent_id": agent_id,
                "capability": capability,
                "status": "active",
                "known_inputs": dict(known_inputs or {}),
                "unresolved_needs": [],
                "permissions": dict(permissions or {}),
                "answers": dict(answers or {}),
                "preferences": dict(preferences or {}),
                "proposal": {},
                "continuation_receipts": {},
                "created_at": now,
                "updated_at": now,
                "expires_at": now + self.timeout_seconds,
            }
            self._insert(state)
        return self.get_task(task_id)

    def get_task(self, task_id, include_expired=False):
        with self._lock:
            state = self._load(task_id)
            if state is None:
                return None
            if self._expire_if_needed(state):
                if not include_expired:
                    return None
                state = self._load(task_id)
            return json.loads(_json(state))

    def record_need(self, task_id, need):
        validate_collaboration_envelope(need)
        with self._lock:
            state = self._active(task_id)
            self._assert_need_identity(state, need)
            state["unresolved_needs"] = [dict(need)]
            state["status"] = "waiting"
            self._save(state)
            return self.get_task(task_id)

    def resolve_need(
        self,
        task_id,
        need,
        conversation=None,
        authorized_data=None,
        preferences=None,
        confirmations=None,
    ):
        """Resolve one need using the mandated least-friction precedence."""
        validate_collaboration_envelope(need)
        conversation = dict(conversation or {})
        authorized_data = dict(authorized_data or {})
        confirmations = dict(confirmations or {})
        with self._lock:
            state = self._active(task_id)
            self._assert_need_identity(state, need)
            state["unresolved_needs"] = [dict(need)]
            if preferences:
                state["preferences"].update(dict(preferences))

            if need["type"] == TASK_NEEDS_PERMISSION:
                permission = need["permission"]
                if state["permissions"].get(permission) is True:
                    state["unresolved_needs"] = []
                    state["status"] = "active"
                    self._save(state)
                    return {
                        "status": "resolved",
                        "resolved_fields": {"permission": permission},
                    }
                state["status"] = "waiting_permission"
                self._save(state)
                return {
                    "status": "needs_permission",
                    "question": "¿Me autorizas a usar %s para %s?"
                    % (_permission_label(permission), need["reason"].rstrip("?")),
                }

            if need["type"] == TASK_NEEDS_APPROVAL:
                state["proposal"] = dict(need["proposal"])
                if confirmations.get("approved") is True:
                    state["unresolved_needs"] = []
                    state["status"] = "active"
                    self._save(state)
                    return {
                        "status": "resolved",
                        "resolved_fields": {"approved": True},
                    }
                state["status"] = "waiting_confirmation"
                self._save(state)
                return {
                    "status": "needs_confirmation",
                    "question": "¿Confirmas esta propuesta?",
                    "proposal": dict(state["proposal"]),
                }

            resolved = {}
            unresolved = []
            recommended = need.get("recommended_default")
            for field in need["missing_fields"]:
                if field in conversation:
                    resolved[field] = conversation[field]
                elif field in state["known_inputs"]:
                    resolved[field] = state["known_inputs"][field]
                elif field in authorized_data:
                    resolved[field] = authorized_data[field]
                elif field in state["preferences"]:
                    resolved[field] = state["preferences"][field]
                elif isinstance(recommended, dict) and field in recommended:
                    if confirmations.get(field) is True:
                        resolved[field] = recommended[field]
                    else:
                        unresolved.append(field)
                        state["known_inputs"].update(resolved)
                        pending = dict(need)
                        pending["missing_fields"] = list(unresolved)
                        state["unresolved_needs"] = [pending]
                        state["status"] = "waiting_confirmation"
                        self._save(state)
                        return {
                            "status": "needs_confirmation",
                            "resolved_fields": dict(resolved),
                            "question": "¿Confirmas una %s de %s?"
                            % (_field_label(field), recommended[field]),
                        }
                else:
                    unresolved.append(field)

            state["known_inputs"].update(resolved)
            if unresolved:
                pending = dict(need)
                pending["missing_fields"] = list(unresolved)
                state["unresolved_needs"] = [pending]
                state["status"] = "waiting"
                self._save(state)
                return {
                    "status": "needs_input",
                    "resolved_fields": dict(resolved),
                    "unresolved_fields": list(unresolved),
                    "question": self._question_for(
                        unresolved[0], need.get("options")
                    ),
                }

            state["unresolved_needs"] = []
            state["status"] = "active"
            self._save(state)
            return {
                "status": "resolved",
                "resolved_fields": dict(resolved),
            }

    def continue_task(
        self, task_id, resolved_fields, sender, permissions=None
    ):
        """Send ``task.continue`` to the same agent exactly once per answer."""
        if not isinstance(resolved_fields, dict) or not resolved_fields:
            raise ValueError("resolved_fields must be a non-empty object")
        with self._lock:
            state = self._active(task_id)
            state["answers"].update(resolved_fields)
            state["known_inputs"].update(resolved_fields)
            state["proposal"].update(resolved_fields)
            if permissions:
                state["permissions"].update(dict(permissions))
            digest = hashlib.sha256(
                _json(
                    {
                        "task_id": task_id,
                        "conversation_id": state["conversation_id"],
                        "resolved_fields": resolved_fields,
                        "permissions": permissions or {},
                    }
                ).encode("utf-8")
            ).hexdigest()
            prior = state["continuation_receipts"].get(digest)
            if prior is not None:
                return json.loads(_json(prior))
            self._save(state)

            envelope = {
                "type": TASK_CONTINUE,
                "task_id": task_id,
                "conversation_id": state["conversation_id"],
                "resolved_fields": dict(resolved_fields),
                "idempotency_key": digest,
            }
            if permissions:
                envelope["permissions"] = dict(permissions)

            try:
                response = sender(state["agent_id"], envelope)
            except Exception:
                state = self._active(task_id)
                state["status"] = "agent_unavailable"
                self._save(state)
                return {
                    "status": "agent_unavailable",
                    "message": (
                        "No pude continuar con el agente seleccionado. "
                        "Puedes intentarlo de nuevo."
                    ),
                }

            state = self._active(task_id)
            result = {
                "status": "continued",
                "task_id": task_id,
                "conversation_id": state["conversation_id"],
                "agent_id": state["agent_id"],
                "response": response,
            }
            state["continuation_receipts"][digest] = result
            state["status"] = "active"
            if isinstance(response, dict) and str(
                response.get("type", "")
            ).startswith("task.needs_"):
                self._assert_need_identity(state, response)
                state["unresolved_needs"] = [dict(response)]
                state["status"] = "waiting"
            else:
                state["unresolved_needs"] = []
            self._save(state)
            return json.loads(_json(result))

    def _question_for(self, field, options):
        values = None
        if isinstance(options, dict):
            values = options.get(field)
        elif isinstance(options, list) and len(options) > 0:
            values = options
        if values:
            return "¿Qué %s prefieres: %s?" % (
                _field_label(field),
                " o ".join(str(value) for value in values),
            )
        return "¿Qué %s prefieres?" % _field_label(field)

    def _assert_need_identity(self, state, need):
        if (
            need["task_id"] != state["task_id"]
            or need["conversation_id"] != state["conversation_id"]
        ):
            raise ValueError("need does not belong to this task conversation")

    def _active(self, task_id):
        state = self._load(task_id)
        if state is None:
            raise KeyError("unknown task")
        if self._expire_if_needed(state):
            raise TimeoutError("task conversation expired")
        return state

    def _expire_if_needed(self, state):
        if (
            state.get("status") != "expired"
            and int(self.clock()) > int(state["expires_at"])
        ):
            state["status"] = "expired"
            state["unresolved_needs"] = []
            self._save(state, expires_at=state["expires_at"])
            return True
        return state.get("status") == "expired"

    def _load(self, task_id):
        row = self._connection.execute(
            """
            SELECT state_json
            FROM orchestrator_conversations
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()
        return json.loads(row["state_json"]) if row is not None else None

    def _insert(self, state):
        self._connection.execute(
            """
            INSERT INTO orchestrator_conversations(
                task_id, conversation_id, agent_id, capability,
                state_json, created_at, updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state["task_id"], state["conversation_id"],
                state["agent_id"], state["capability"], _json(state),
                state["created_at"], state["updated_at"],
                state["expires_at"],
            ),
        )

    def _save(self, state, now=None, expires_at=None):
        now = int(self.clock()) if now is None else int(now)
        state["updated_at"] = now
        if expires_at is not None:
            state["expires_at"] = int(expires_at)
        self._connection.execute(
            """
            UPDATE orchestrator_conversations
            SET state_json = ?, updated_at = ?, expires_at = ?
            WHERE task_id = ?
            """,
            (
                _json(state),
                now,
                int(state["expires_at"]),
                state["task_id"],
            ),
        )


class PostgresConversationStateStore(ConversationStateStore):
    """Shared task-conversation state serialized per tenant and task."""

    def __init__(self, db, clock=None, timeout_seconds=DEFAULT_TIMEOUT_SECONDS):
        self.db = db
        self.clock = clock or time.time
        self.timeout_seconds = int(timeout_seconds)
        self._lock = threading.RLock()
        self._local = threading.local()

    def close(self):
        return None

    @contextmanager
    def _operation(self, task_id):
        active = getattr(self._local, "connection", None)
        if active is not None:
            yield
            return
        tenant_id = current_organization_id()
        if not tenant_id:
            raise ValueError("tenant_id is required")
        with self.db.transaction() as conn:
            conn.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ("%s:%s" % (tenant_id, task_id),),
            )
            self._local.connection = conn
            self._local.tenant_id = tenant_id
            try:
                yield
            finally:
                self._local.connection = None
                self._local.tenant_id = None

    def create_task(self, task_id, *args, **kwargs):
        with self._operation(task_id):
            return super().create_task(task_id, *args, **kwargs)

    def get_task(self, task_id, include_expired=False):
        with self._operation(task_id):
            return super().get_task(task_id, include_expired)

    def record_need(self, task_id, need):
        with self._operation(task_id):
            return super().record_need(task_id, need)

    def resolve_need(self, task_id, need, **kwargs):
        with self._operation(task_id):
            return super().resolve_need(task_id, need, **kwargs)

    def continue_task(self, task_id, resolved_fields, sender, permissions=None):
        with self._operation(task_id):
            return super().continue_task(
                task_id, resolved_fields, sender, permissions
            )

    def _load(self, task_id):
        row = self._local.connection.execute(
            """
            select state_json from orchestrator.task_conversations
            where tenant_id = %s and task_id = %s
            """,
            (self._local.tenant_id, task_id),
        ).fetchone()
        return dict(row[0]) if row is not None else None

    def _insert(self, state):
        self._local.connection.execute(
            """
            insert into orchestrator.task_conversations(
                tenant_id, task_id, conversation_id, agent_id, capability,
                state_json, created_at, updated_at, expires_at
            ) values (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            """,
            (
                self._local.tenant_id, state["task_id"],
                state["conversation_id"], state["agent_id"],
                state["capability"], _json(state), _utc(state["created_at"]),
                _utc(state["updated_at"]), _utc(state["expires_at"]),
            ),
        )

    def _save(self, state, now=None, expires_at=None):
        now = int(self.clock()) if now is None else int(now)
        state["updated_at"] = now
        if expires_at is not None:
            state["expires_at"] = int(expires_at)
        self._local.connection.execute(
            """
            update orchestrator.task_conversations
            set state_json = %s::jsonb, updated_at = %s, expires_at = %s
            where tenant_id = %s and task_id = %s
            """,
            (
                _json(state), _utc(now), _utc(state["expires_at"]),
                self._local.tenant_id, state["task_id"],
            ),
        )


def _utc(value):
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


@dataclass
class ConversationWorkflowState:
    """Small UI-facing pointer to a durable workflow draft."""

    workflow_run_id: Optional[str] = None
    workflow_revision_id: Optional[str] = None
    known_inputs: Dict[str, Any] = field(default_factory=dict)
    blocking_need: Optional[Dict[str, Any]] = None

    def block(self, kind, field_name, question, step_id=None):
        self.blocking_need = {
            "kind": kind,
            "field": field_name,
            "question": question,
            "step_id": step_id,
        }
        return dict(self.blocking_need)

    def answer(self, field_name, value):
        self.known_inputs[field_name] = value
        if self.blocking_need and self.blocking_need.get("field") == field_name:
            self.blocking_need = None


class TenantIdentityResolver:
    """Resolve explicit tenant-scoped identity links; never guess recipients."""

    def __init__(self, links=None):
        self.links = dict(links or {})

    def resolve_email(self, tenant_id, slack_connection_id, slack_user_id):
        return self.links.get((tenant_id, slack_connection_id, slack_user_id))


class ConciergeConversationStore:
    """Clock-bound facade for native, principal-scoped Concierge state.

    This is deliberately not part of ``ConversationStateStore``: native turns
    have no selected agent and must not manufacture collaboration envelopes.
    """

    DEFAULT_TTL_SECONDS = 180

    def __init__(self, repository, clock=None, ttl_seconds=DEFAULT_TTL_SECONDS):
        self.repository = repository
        self.clock = clock or time.time
        self.ttl_seconds = int(ttl_seconds)

    def create(self, tenant_id, principal_id, conversation_id=None, locale=None):
        return self.repository.create_conversation(
            tenant_id, principal_id, int(self.clock()), self.ttl_seconds,
            conversation_id=conversation_id, locale=locale,
        )

    def get(self, conversation_id, tenant_id, principal_id, include_terminal=False):
        return self.repository.get_conversation(
            conversation_id, tenant_id, principal_id, int(self.clock()),
            include_terminal=include_terminal,
        )

    def update(
        self, conversation_id, tenant_id, principal_id,
        expected_version=None, **changes
    ):
        return self.repository.update_conversation(
            conversation_id, tenant_id, principal_id, changes,
            int(self.clock()), self.ttl_seconds,
            expected_version=expected_version,
        )

    def begin_turn(
        self, conversation_id, tenant_id, principal_id, client_turn_id,
        expected_version, request,
    ):
        return self.repository.begin_conversation_turn(
            conversation_id, tenant_id, principal_id, client_turn_id,
            expected_version, request, int(self.clock()), self.ttl_seconds,
        )

    def commit_turn(
        self, conversation_id, tenant_id, principal_id, client_turn_id,
        expected_version, changes, response,
    ):
        return self.repository.commit_conversation_turn(
            conversation_id, tenant_id, principal_id, client_turn_id,
            expected_version, changes, response, int(self.clock()),
            self.ttl_seconds,
        )

    def record_need(self, conversation_id, tenant_id, principal_id, need):
        if hasattr(need, "model_dump"):
            need = need.model_dump()
        elif hasattr(need, "dict"):
            need = need.dict()
        if not isinstance(need, dict) or not all(
            isinstance(need.get(key), str) and need[key]
            for key in ("kind", "field", "question")
        ):
            raise ValueError("blocking need requires kind, field and question")
        return self.update(
            conversation_id, tenant_id, principal_id,
            status="needs_input", blocking_need=dict(need),
        )

    def answer(
        self, conversation_id, tenant_id, principal_id, idempotency_key,
        field_name, value, workflow_run_id=None, workflow_revision_id=None,
    ):
        return self.repository.apply_conversation_answer(
            conversation_id, tenant_id, principal_id, idempotency_key,
            field_name, value, int(self.clock()), workflow_run_id,
            workflow_revision_id,
        )

    def present(self, conversation_id, tenant_id, principal_id, presentation):
        if hasattr(presentation, "model_dump"):
            presentation = presentation.model_dump()
        elif hasattr(presentation, "dict"):
            presentation = presentation.dict()
        return self.repository.store_conversation_presentation(
            conversation_id, tenant_id, principal_id, presentation,
            int(self.clock()), self.ttl_seconds,
        )

    def close(self, conversation_id, tenant_id, principal_id):
        return self.repository.close_conversation(
            conversation_id, tenant_id, principal_id, int(self.clock())
        )

    def purge_expired_content(self):
        return self.repository.purge_expired_conversation_content(
            int(self.clock())
        )
