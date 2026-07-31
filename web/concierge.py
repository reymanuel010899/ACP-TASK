"""HTTP surface for the LLM concierge orchestrator (``agents/orchestrator``).

Wraps :class:`OrchestratorAgent` behind ``POST /concierge {message}`` ->
``{status, reply, evidence}`` so the marketplace's floating client console can
talk to the real concierge: it turns a natural-language request into intent,
discovers candidate agents, negotiates terms, gates spend, executes, and
replies courteously.

Brain selection is automatic (``make_brain``): ClaudeBrain (claude-opus-4-8)
when ``ANTHROPIC_API_KEY`` is set, else the offline RuleBrain so the service
never crashes without credentials. Spend is auto-approved under a ceiling —
the web console has no interactive stdin gate.

Run: ``python -m web.concierge --port 8130 --registry-url http://127.0.0.1:8090
[--agent-marketplace-url URL] [--vault-url URL]``
"""

import argparse
import dataclasses
import json
import logging
import os
import urllib.request
import time
from urllib.parse import unquote
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agents.orchestrator.agent import DEFAULT_AGENT_ID, OrchestratorAgent
from agents.orchestrator.approval import (
    ApprovalGate,
    SpendPolicy,
    always_approve_callback,
)
from agents.orchestrator.brain import ClaudeBrain, GroqBrain, make_brain
from agents.orchestrator.broker_client import ActionBrokerClient
from agents.orchestrator.tools import OrchestratorTools
from agents.orchestrator.workflow_repository import WorkflowRepository
from agents.orchestrator.conversation_state import ConciergeConversationStore
from agents.orchestrator.dynamic_workflow_service import DynamicWorkflowService
from libs.integrations.catalog import google_definitions, slack_definitions
from services.oauth.repository import OAuthRepository
from services.session.app import session_cookie_value
from services.session.repository import SessionRepository

MAX_HISTORY_TURNS = 24
MAX_TURN_CHARS = 2000
logger = logging.getLogger(__name__)


def brain_label(brain):
    # type: (object) -> str
    if isinstance(brain, ClaudeBrain):
        return "claude"
    if isinstance(brain, GroqBrain):
        return "groq"
    return "rule"


def fetch_capabilities(runner_url, registry_url=None, timeout=4.0):
    # type: (str, str, float) -> list
    """The live capability vocabulary the brain maps requests onto.

    Preferred source: the registry's enriched catalog (GET /capabilities —
    card-derived name/description/tags plus who offers it), persisted to the
    database at registration time, so matching is by MEANING, not just id.
    Fallback: bare capability ids from the runner's agent list. Best-effort:
    returns [] when neither is reachable."""
    if registry_url:
        try:
            with urllib.request.urlopen(
                registry_url.rstrip("/") + "/capabilities", timeout=timeout
            ) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            catalog = []
            for cap in data.get("capabilities", []):
                if not cap.get("agents"):
                    continue  # nobody offers it right now — not actionable
                entry = {"id": cap["capability_id"]}
                if cap.get("name"):
                    entry["name"] = cap["name"]
                description = (cap.get("description") or "").strip()
                if description and not description.startswith("auto-registered"):
                    entry["description"] = description
                if cap.get("tags"):
                    entry["tags"] = cap["tags"]
                agents = [a.get("name") for a in cap["agents"] if a.get("name")]
                if agents:
                    entry["offered_by"] = agents
                catalog.append(entry)
            if catalog:
                return catalog
        except Exception:
            pass  # fall through to the runner
    if not runner_url:
        return []
    try:
        with urllib.request.urlopen(runner_url.rstrip("/") + "/agents", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    caps, seen = [], set()
    for agent in data.get("agents", []) if isinstance(data, dict) else []:
        for cap in agent.get("capabilities") or []:
            if cap and cap not in seen:
                seen.add(cap)
                caps.append(cap)
    return caps


def build_agent(registry_url, agent_marketplace_url=None, vault_url=None,
                auto_approve_under="1000", hard_ceiling="1000000",
                action_broker_url=None, action_broker_token=None):
    brain = make_brain()
    policy = SpendPolicy(
        auto_approve_under=Decimal(auto_approve_under),
        hard_ceiling=Decimal(hard_ceiling),
    )
    gate = ApprovalGate(policy, always_approve_callback)
    action_broker = None
    if action_broker_url or action_broker_token:
        action_broker = ActionBrokerClient(
            action_broker_url, action_broker_token
        )
    tools = OrchestratorTools(
        registry_url=registry_url,
        agent_marketplace_url=agent_marketplace_url,
        vault_url=vault_url,
        gate=gate,
        agent_principal_id=DEFAULT_AGENT_ID,
        action_broker=action_broker,
    )
    agent = OrchestratorAgent(
        registry_url=registry_url,
        brain=brain,
        tools=tools,
        gate=gate,
        agent_id=DEFAULT_AGENT_ID,
    )
    agent.register()
    return agent, brain_label(brain)


def _make_handler(agent, label, runner_url, registry_url=None,
                  workflow_repository=None, session_repository=None,
                  dynamic_workflow_service=None, tenant_resolver=None,
                  clock=None):
    clock = clock or time.time
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _send(self, status, body):
            raw = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/healthz":
                return self._send(200, {"status": "ok", "brain": label})
            path = self.path.split("?", 1)[0]
            if path.startswith("/conversations/") and workflow_repository and session_repository:
                conversation_id = _conversation_id_from_path(path)
                if not _valid_conversation_id(conversation_id):
                    return self._send(400, {"error": "invalid conversation ID"})
                current = session_repository.resolve(
                    session_cookie_value(self.headers.get("Cookie")), clock()
                )
                if current is None:
                    return self._send(401, {"error": "authentication required"})
                tenant_id = tenant_resolver(current["principal_id"]) if tenant_resolver else current.get("tenant_id")
                store = getattr(dynamic_workflow_service, "conversation_store", None)
                conversation = store.get(
                    conversation_id, tenant_id, current["principal_id"]
                ) if store and tenant_id else None
                if conversation is None:
                    return self._send(404, {
                        "state": "expired", "conversationId": conversation_id,
                        "recovery": {"action": "start_new_conversation"},
                    })
                return self._send(200, _conversation_response(conversation))
            if path.startswith("/workflows/") and workflow_repository and session_repository:
                workflow_id = _workflow_id_from_path(path)
                current = session_repository.resolve(
                    session_cookie_value(self.headers.get("Cookie")), clock()
                )
                if current is None:
                    return self._send(401, {"error": "authentication required"})
                run = workflow_repository.get_run_for_principal(
                    workflow_id, current["principal_id"]
                )
                if run is None:
                    return self._send(404, {"error": "workflow not found"})
                revision = workflow_repository.get_revision(
                    workflow_id, run["current_revision_id"], run["tenant_id"]
                )
                return self._send(200, {
                    "run": run, "revision": revision,
                    "recovery": workflow_repository.recovery_options(revision),
                })
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            workflow_operation = next((
                operation for operation in ("approve", "cancel", "retry")
                if path.startswith("/workflows/") and path.endswith("/%s" % operation)
            ), None)
            conversation_close = (
                path.startswith("/conversations/") and path.endswith("/close")
            )
            if path != "/concierge" and workflow_operation is None and not conversation_close:
                return self._send(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except ValueError:
                return self._send(400, {"error": "invalid JSON"})
            if conversation_close:
                if not session_repository or not dynamic_workflow_service:
                    return self._send(503, {"error": "conversation service unavailable"})
                session_id = session_cookie_value(self.headers.get("Cookie"))
                current = session_repository.resolve(session_id, clock())
                if current is None:
                    return self._send(401, {"error": "authentication required"})
                if not session_repository.csrf_matches(
                    session_id, self.headers.get("X-CSRF-Token")
                ):
                    return self._send(403, {"error": "invalid CSRF token"})
                tenant_id = tenant_resolver(current["principal_id"]) if tenant_resolver else current.get("tenant_id")
                conversation_id = _conversation_id_from_path(path, "close")
                if not _valid_conversation_id(conversation_id):
                    return self._send(400, {"error": "invalid conversation ID"})
                store = getattr(dynamic_workflow_service, "conversation_store", None)
                owned = store.get(
                    conversation_id, tenant_id, current["principal_id"],
                    include_terminal=True,
                ) if store and tenant_id else None
                if owned is None:
                    return self._send(404, {"error": "conversation not found"})
                changed = bool(store and tenant_id and store.close(
                    conversation_id, tenant_id, current["principal_id"]
                ))
                # Closing is idempotent and does not disclose foreign IDs.
                return self._send(200, {
                    "state": "expired", "conversationId": conversation_id,
                    "closed": changed or True,
                })
            if workflow_operation is not None:
                if not workflow_repository or not session_repository:
                    return self._send(503, {"error": "workflow service unavailable"})
                session_id = session_cookie_value(self.headers.get("Cookie"))
                current = session_repository.resolve(session_id, clock())
                if current is None:
                    return self._send(401, {"error": "authentication required"})
                if not session_repository.csrf_matches(
                    session_id, self.headers.get("X-CSRF-Token")
                ):
                    return self._send(403, {"error": "invalid CSRF token"})
                if workflow_operation == "approve" and not isinstance(payload.get("approved"), bool):
                    return self._send(422, {"error": "approved must be boolean"})
                if (
                    workflow_operation == "approve"
                    and payload.get("approved") is True
                    and payload.get("conversationId")
                    and payload.get("draftHash")
                    and dynamic_workflow_service is not None
                ):
                    tenant_id = tenant_resolver(current["principal_id"]) if tenant_resolver else current.get("tenant_id")
                    try:
                        dynamic_workflow_service.approve_slack_draft(
                            payload["conversationId"], tenant_id,
                            current["principal_id"], payload["draftHash"],
                        )
                    except (KeyError, ValueError, PermissionError):
                        return self._send(409, {"error": "workflow revision changed"})
                    return self._send(200, {
                        "state": "executing",
                        "conversationId": payload["conversationId"],
                    })
                workflow_id = _workflow_id_from_path(path, workflow_operation)
                run = workflow_repository.get_run_for_principal(
                    workflow_id, current["principal_id"]
                )
                if run is None:
                    return self._send(404, {"error": "workflow not found"})
                revision = workflow_repository.get_revision(
                    workflow_id, payload.get("revisionId"), run["tenant_id"]
                )
                if revision is None or revision["revision_number"] != payload.get("revision"):
                    return self._send(409, {"error": "workflow revision changed"})
                if workflow_operation == "cancel":
                    changed = workflow_repository.cancel_revision(
                        workflow_id, revision["workflow_revision_id"], run["tenant_id"]
                    )
                    return self._send(
                        200 if changed else 409,
                        {"status": "cancelled"} if changed else {"error": "workflow cannot be cancelled"},
                    )
                if workflow_operation == "retry":
                    step_id = payload.get("stepId")
                    if not isinstance(step_id, str) or not step_id:
                        return self._send(422, {"error": "stepId is required"})
                    changed = workflow_repository.retry_safe_read(
                        workflow_id, revision["workflow_revision_id"], step_id,
                        run["tenant_id"],
                    )
                    if not changed and payload.get("reconciledSafe") is True:
                        changed = workflow_repository.retry_corrected_write(
                            revision["workflow_revision_id"], step_id, run["tenant_id"]
                        )
                    return self._send(
                        200 if changed else 409,
                        {"status": "queued"} if changed else {"error": "step is not safely retryable"},
                    )
                if payload.get("approved") is not True:
                    workflow_repository.cancel_revision(
                        workflow_id, revision["workflow_revision_id"], run["tenant_id"]
                    )
                    return self._send(200, {"status": "rejected"})
                try:
                    workflow_repository.record_approval(
                        workflow_id, revision["workflow_revision_id"], run["tenant_id"],
                        revision["plan_graph_hash"], current["principal_id"], int(clock())
                    )
                except ValueError:
                    return self._send(409, {"error": "workflow revision changed"})
                return self._send(200, {"status": "approved"})
            message = (payload.get("message") or payload.get("text") or "").strip()
            if not message:
                return self._send(400, {"error": "a 'message' is required"})
            context = {}
            # Conversation memory: the client sends prior turns so the brain can
            # accumulate details across messages instead of restarting each time.
            history = payload.get("history")
            if isinstance(history, list) and history:
                turns = [
                    {
                        "role": t.get("role"),
                        "text": t.get("text")[:MAX_TURN_CHARS],
                    }
                    for t in history[-MAX_HISTORY_TURNS:]
                    if (
                        isinstance(t, dict)
                        and t.get("role") in ("user", "concierge")
                        and isinstance(t.get("text"), str)
                        and t.get("text").strip()
                    )
                ]
                if turns:
                    context["conversation"] = turns
            # Live capability vocabulary: what real agents actually offer —
            # enriched from the DB-backed catalog (names/descriptions/tags) so
            # the brain matches requests by meaning, not just id.
            caps = fetch_capabilities(runner_url, registry_url)
            if caps:
                context["available_capabilities"] = caps
            current = None
            if session_repository is not None:
                current = session_repository.resolve(
                    session_cookie_value(self.headers.get("Cookie")), clock()
                )
            requested_conversation_id = payload.get("conversationId") or payload.get("conversation_id")
            if requested_conversation_id and not _valid_conversation_id(requested_conversation_id):
                return self._send(400, {"error": "invalid conversation ID"})
            if _is_slack_turn(message, requested_conversation_id) and current is None:
                return self._send(401, {"error": "authentication required"})
            if current and dynamic_workflow_service and tenant_resolver:
                tenant_id = tenant_resolver(current["principal_id"])
                if _is_slack_turn(message, requested_conversation_id) and not tenant_id:
                    return self._send(409, {"error": "tenant membership is required"})
                if tenant_id:
                    conversation_id = requested_conversation_id
                    if _is_slack_turn(message, conversation_id):
                        try:
                            turn = dynamic_workflow_service.coordinate_slack_turn(
                                tenant_id, current["principal_id"], message,
                                conversation_id=conversation_id,
                            )
                            return self._send(200, _turn_response(turn))
                        except (KeyError, TimeoutError):
                            return self._send(404, {
                                "state": "expired", "conversationId": conversation_id,
                                "recovery": {"action": "start_new_conversation"},
                            })
                        except PermissionError as exc:
                            return self._send(409, _classified_recovery(exc, conversation_id))
                        except ValueError:
                            return self._send(422, {
                                "state": "needs_input", "conversationId": conversation_id,
                                "need": {"field": "request", "question": "Aclara tu solicitud de Slack."},
                            })
                        except Exception as exc:
                            logger.warning("Slack conversation failed: %s", type(exc).__name__)
                            return self._send(500, {
                                "state": "retryable_failure", "conversationId": conversation_id,
                                "recovery": {"action": "retry"},
                            })
                    try:
                        intent = agent.brain.understand(message, context or None)
                        if intent.conversation_act in ("request", "clarification", "modify"):
                            workflow = dynamic_workflow_service.plan(
                                tenant_id, current["principal_id"], message, context
                            )
                            if not dynamic_workflow_service.shadow_mode:
                                return self._send(200, {
                                    "status": "workflow_preview",
                                    "reply": "Preparé un plan seguro para que lo revises antes de ejecutar.",
                                    "workflow": workflow["preview"],
                                    "brain": label,
                                })
                    except Exception as exc:
                        logger.warning(
                            "dynamic workflow planning failed: %s",
                            type(exc).__name__,
                        )
                        if not dynamic_workflow_service.shadow_mode:
                            return self._send(200, {
                                "status": "needs_info",
                                "reply": "Aún no puedo construir un plan seguro con las conexiones disponibles.",
                                "brain": label,
                            })
                        # Shadow planning must never break the established concierge path.
            try:
                result = agent.handle_request(message, context=context or None)
            except Exception as exc:  # never leak a stack trace
                logger.warning("concierge request failed: %s", type(exc).__name__)
                return self._send(200, {"status": "failed", "reply": "Lo siento, ocurrió un problema."})
            body = dataclasses.asdict(result) if dataclasses.is_dataclass(result) else {
                "status": getattr(result, "status", None),
                "reply": getattr(result, "reply", None),
                "evidence": getattr(result, "evidence", None),
            }
            body["brain"] = label
            return self._send(200, body)

    return Handler


def _workflow_id_from_path(path, operation=None):
    suffix = "/%s" % operation if operation else ""
    end = -len(suffix) if suffix else None
    encoded = path[len("/workflows/"):end].rstrip("/")
    return unquote(encoded)


def _conversation_id_from_path(path, operation=None):
    suffix = "/%s" % operation if operation else ""
    end = -len(suffix) if suffix else None
    encoded = path[len("/conversations/"):end].rstrip("/")
    return unquote(encoded)


def _is_slack_turn(message, conversation_id=None):
    text = str(message or "").lower()
    return bool(conversation_id or "slack" in text or "#" in text or any(
        marker in text for marker in (
            "manda un mensaje", "mándale", "mandale", "qué dijo", "que dijo",
            "reply there", "send a direct message", "post in ",
        )
    ))


def _valid_conversation_id(value):
    return (
        isinstance(value, str) and value.startswith("conversation:")
        and 1 <= len(value) <= 160
        and all(character.isalnum() or character in ":_-" for character in value)
    )


def _turn_response(turn):
    state = turn.get("state", "interpreting")
    response = {
        "state": state,
        "conversationId": turn.get("conversation_id") or turn.get("conversationId"),
    }
    if turn.get("need"):
        response["need"] = turn["need"]
    if turn.get("message"):
        response["message"] = turn["message"]
    return {key: value for key, value in response.items() if value is not None}


def _conversation_response(conversation):
    result = {
        "state": conversation["status"],
        "conversationId": conversation["conversation_id"],
    }
    if conversation.get("blocking_need"):
        result["need"] = conversation["blocking_need"]
    presentation = conversation.get("presentation")
    if presentation:
        result["answer"] = presentation.get("answer")
        result["citations"] = presentation.get("citations", [])
        result["partial"] = bool(presentation.get("partial"))
    draft = conversation.get("pending_draft")
    if draft:
        result["draft"] = {
            "draftHash": draft.get("draft_hash"),
            "destination": draft.get("destination_label"),
            "text": draft.get("text"),
            "workflowId": draft.get("workflow_run_id"),
            "revisionId": draft.get("workflow_revision_id"),
        }
    if conversation.get("workflow_run_id"):
        result["workflow"] = {
            "workflowId": conversation["workflow_run_id"],
            "revisionId": conversation.get("workflow_revision_id"),
        }
    return result


def _classified_recovery(exc, conversation_id=None):
    code = str(exc).split(":", 1)[0]
    action = "upgrade_scopes" if code == "missing_scope" else "reconnect"
    return {
        "state": "retryable_failure", "conversationId": conversation_id,
        "error": {"code": code}, "recovery": {"action": action},
    }


def _tenant_resolver():
    try:
        mapping = json.loads(os.environ.get("TESSERA_PRINCIPAL_TENANTS_JSON", "{}"))
    except ValueError:
        mapping = {}
    if not isinstance(mapping, dict):
        mapping = {}
    return lambda principal_id: mapping.get(principal_id)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Concierge orchestrator HTTP service")
    parser.add_argument("--port", type=int, default=8130)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--registry-url", default="http://127.0.0.1:8090")
    parser.add_argument("--agent-marketplace-url", default=None)
    parser.add_argument("--vault-url", default=None)
    parser.add_argument(
        "--action-broker-url",
        default=os.environ.get("TESSERA_ACTION_BROKER_URL"),
    )
    parser.add_argument(
        "--action-broker-token",
        default=os.environ.get("TESSERA_ACTION_BROKER_INTERNAL_TOKEN"),
    )
    parser.add_argument("--runner-url", default="http://127.0.0.1:8110",
                        help="Runner used to read the live capability vocabulary.")
    args = parser.parse_args(argv)

    agent, label = build_agent(
        registry_url=args.registry_url,
        agent_marketplace_url=args.agent_marketplace_url,
        vault_url=args.vault_url,
        action_broker_url=args.action_broker_url,
        action_broker_token=args.action_broker_token,
    )
    workflow_repository = WorkflowRepository.from_environment(
        os.environ.get("WORKFLOW_DATABASE", "tessera-workflows.db"),
        os.environ.get("TESSERA_CONCIERGE_IDENTITY", "service:concierge"),
    )
    session_repository = SessionRepository(
        os.environ.get("SESSION_DATABASE", "tessera-sessions.db")
    )
    connection_repository = OAuthRepository(
        os.environ.get("OAUTH_DATABASE", "tessera-oauth.db")
    )
    tenant_resolver = _tenant_resolver()
    dynamic_service = DynamicWorkflowService(
        agent.brain,
        google_definitions() + slack_definitions(),
        connection_repository,
        workflow_repository,
        rollout_version=os.environ.get("TESSERA_CAPABILITY_ROLLOUT_VERSION", "production-v1"),
        shadow_mode=os.environ.get("TESSERA_DYNAMIC_PLANNER_SHADOW", "true").lower() != "false",
        conversation_store=ConciergeConversationStore(workflow_repository),
    )
    httpd = ThreadingHTTPServer(
        (args.host, args.port),
        _make_handler(
            agent, label, args.runner_url, args.registry_url,
            workflow_repository, session_repository, dynamic_service,
            tenant_resolver,
        ),
    )
    print("Concierge on http://%s:%d  (brain: %s)" % (args.host, args.port, label))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
