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
import base64
import dataclasses
import hashlib
import json
import logging
import os
import secrets
import urllib.request
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import parse_qs, unquote, urlsplit
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from psycopg.errors import UniqueViolation

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
from agents.orchestrator.campaign_repository import (
    CampaignEnvelopeChanged,
    CampaignPermissionDenied,
    CampaignRepository,
    CampaignStateConflict,
)
from agents.orchestrator.campaign_service import CampaignService
from agents.orchestrator.slack_conversation import normalize_name
from libs.integrations.catalog import provider_definitions
from libs.integrations.control_plane import build_tenant_control_plane
from libs.contacts_repository import (
    BranchNotFound,
    ContactsRepository,
    InvalidBranchPlacement,
    record_version,
    slugify,
)
from libs.contacts_import import ContactDirectory, StaleContactRecord
from libs.contacts_consent import AUTHORITY_ADMINISTER, Actor
from libs.contacts_permissions import (
    BranchPermissionsRepository,
    ContactsAccess,
    DIMENSIONS,
    DIMENSION_ADMINISTER,
    DIMENSION_EDIT,
    DIMENSION_VIEW,
    PermissionDenied,
)
from libs.contacts_consent import ContactsConsentRepository
from libs.aws_kms import AWSKMSClient
from libs.db import Database
from libs.identity_repository import IdentityRepository
from libs.tenancy import MembershipTenantResolver, UnmappedPrincipalError
from services.oauth.repository import OAuthRepository
from services.session.app import session_cookie_value
from services.session.repository import SessionRepository
from vault.app import VaultService
from vault.managed_oauth_crypto import ManagedOAuthCrypto
from vault.repository import VaultRepository

MAX_HISTORY_TURNS = 24
MAX_TURN_CHARS = 2000
MAX_CONTACT_EDIT_BYTES = 32 * 1024
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


#: Where this service keeps the ed25519 key it proves its identity with. The
#: key is generated locally on first start and never transmitted.
DEFAULT_KEYS_DIR = os.path.join(".local", "runtime", "concierge-keys")


def concierge_identity(keys_dir=None):
    """This service's signing key and the principal id derived from it.

    The broker refuses any side-effecting dispatch from an agent that cannot
    re-prove its identity, and identity here means possession of the key the
    principal id was derived from. An agent id chosen by configuration can
    never satisfy that, however carefully it is spelled, so the id is computed
    from the public key using the same convention every other agent uses.
    """
    from agents.provider.agent import load_or_create_keypair

    signing_key = load_or_create_keypair(
        keys_dir or os.environ.get("TESSERA_CONCIERGE_KEYS_DIR")
        or DEFAULT_KEYS_DIR
    )
    public_key = base64.b64encode(
        bytes(signing_key.verify_key)
    ).decode("ascii")
    label = os.environ.get("TESSERA_CONCIERGE_AGENT_LABEL", "concierge")
    principal_id = "atp:principal:%s:%s" % (
        label, hashlib.sha256(public_key.encode("ascii")).hexdigest()[:16],
    )
    return signing_key, public_key, principal_id


def trust_proof(signing_key, public_key, principal_id, nonce):
    """Sign the verifier's nonce. Possession of the key is the whole claim."""
    if not isinstance(nonce, str) or not nonce:
        raise ValueError("trust.challenge requires a string nonce")
    signature = signing_key.sign(nonce.encode("utf-8")).signature
    return {
        "type": "trust.proof",
        "principal_id": principal_id,
        "public_key": public_key,
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def build_agent(registry_url, agent_marketplace_url=None, vault_url=None,
                auto_approve_under="1000", hard_ceiling="1000000",
                action_broker_url=None, action_broker_token=None,
                agent_id=None):
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
        agent_principal_id=agent_id or DEFAULT_AGENT_ID,
        action_broker=action_broker,
    )
    agent = OrchestratorAgent(
        registry_url=registry_url,
        brain=brain,
        tools=tools,
        gate=gate,
        agent_id=agent_id or DEFAULT_AGENT_ID,
    )
    agent.register()
    return agent, brain_label(brain)


def _make_handler(agent, label, runner_url, registry_url=None,
                  workflow_repository=None, session_repository=None,
                  dynamic_workflow_service=None, tenant_resolver=None,
                  clock=None, identity=None, contacts_repository=None,
                  contacts_permissions=None, contact_directory=None,
                  campaign_service=None):
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

        def _trust_challenge(self):
            """Answer the broker's identity challenge over A2A JSON-RPC.

            The broker will not dispatch anything with an effect until the
            agent proves it holds the key its principal id was derived from.
            Without this the whole write path is refused as untrusted, which
            reads to a person as a security pause with nothing to act on.
            """
            length = int(self.headers.get("Content-Length") or 0)
            try:
                envelope = json.loads(
                    self.rfile.read(length).decode("utf-8")
                ) if length else {}
            except ValueError:
                return self._send(400, {"error": "invalid JSON"})
            message = (envelope.get("params") or {}).get("message") or {}
            data = next((
                part.get("data") or {}
                for part in (message.get("parts") or [])
                if part.get("kind") == "data"
            ), {})
            if data.get("type") != "trust.challenge":
                return self._send(404, {"error": "not found"})
            signing_key, public_key, principal_id = identity
            try:
                proof = trust_proof(
                    signing_key, public_key, principal_id, data.get("nonce"),
                )
            except ValueError:
                return self._send(400, {"error": "nonce is required"})
            return self._send(200, {
                "jsonrpc": "2.0",
                "id": envelope.get("id"),
                "result": {
                    "kind": "message",
                    "messageId": "proof-%s" % (envelope.get("id") or "0"),
                    "role": "agent",
                    "parts": [{"kind": "data", "data": proof}],
                },
            })

        def do_GET(self):
            if self.path == "/healthz":
                return self._send(200, {"status": "ok", "brain": label})
            path = self.path.split("?", 1)[0]
            if (path == "/campaigns" or path.startswith("/campaigns/")) and session_repository:
                current = session_repository.resolve(
                    session_cookie_value(self.headers.get("Cookie")), clock()
                )
                if current is None:
                    return self._send(401, {"error": "authentication required"})
                tenant_id = _request_tenant(tenant_resolver, current)
                if not tenant_id or campaign_service is None:
                    return self._send(404, {"error": "campaign service not found"})
                try:
                    if path == "/campaigns":
                        return self._send(200, {"campaigns": campaign_service.list(tenant_id)})
                    campaign_id = unquote(path[len("/campaigns/"):])
                    if "/" in campaign_id or not campaign_id.startswith("campaign:"):
                        return self._send(404, {"error": "campaign not found"})
                    return self._send(200, campaign_service.detail(tenant_id, campaign_id))
                except LookupError:
                    return self._send(404, {"error": "campaign not found"})
            if path == "/contacts" and session_repository:
                current = session_repository.resolve(
                    session_cookie_value(self.headers.get("Cookie")), clock()
                )
                if current is None:
                    return self._send(401, {"error": "authentication required"})
                tenant_id = _request_tenant(tenant_resolver, current)
                if not tenant_id or contacts_repository is None:
                    return self._send(404, {"error": "directory not found"})
                branch_id = (parse_qs(urlsplit(self.path).query).get(
                    "branchId"
                ) or [None])[0]
                if not branch_id:
                    return self._send(422, {"error": "branchId is required"})
                if contacts_permissions is None:
                    return self._send(503, {
                        "error": "directory permissions unavailable"
                    })
                try:
                    contacts_permissions.require(
                        tenant_id, current["principal_id"], branch_id,
                        DIMENSION_VIEW,
                    )
                except PermissionDenied:
                    return self._send(404, {"error": "branch not found"})
                contacts = contacts_repository.contacts_in_branch(
                    tenant_id, branch_id
                )
                can_edit = contacts_permissions.effective(
                    tenant_id, current["principal_id"], branch_id,
                )[DIMENSION_EDIT]
                return self._send(200, {
                    "contacts": [
                        _contact_summary(
                            contact,
                            record_version(
                                contact,
                                contacts_repository.addresses(
                                    tenant_id, contact["contact_id"]
                                ),
                            ),
                            can_edit,
                        )
                        for contact in contacts
                    ]
                })
            if path == "/contacts/branches" and session_repository:
                current = session_repository.resolve(
                    session_cookie_value(self.headers.get("Cookie")), clock()
                )
                if current is None:
                    return self._send(401, {"error": "authentication required"})
                tenant_id = _request_tenant(tenant_resolver, current)
                if not tenant_id or contacts_repository is None:
                    return self._send(404, {"error": "directory not found"})
                visible = set(contacts_permissions.authorized_branches(
                    tenant_id, current["principal_id"], DIMENSION_VIEW,
                )) if contacts_permissions else None
                tree = _contact_branch_tree(
                    contacts_repository, tenant_id, visible_branch_ids=visible,
                )
                return self._send(200, {"branches": tree})
            if path.startswith("/conversations/") and workflow_repository and session_repository:
                conversation_id = _conversation_id_from_path(path)
                if not _valid_conversation_id(conversation_id):
                    return self._send(400, {"error": "invalid conversation ID"})
                current = session_repository.resolve(
                    session_cookie_value(self.headers.get("Cookie")), clock()
                )
                if current is None:
                    return self._send(401, {"error": "authentication required"})
                tenant_id = _request_tenant(tenant_resolver, current)
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

        def do_PATCH(self):
            path = self.path.split("?", 1)[0]
            prefix = "/contacts/"
            if not path.startswith(prefix):
                return self._send(404, {"error": "not found"})
            contact_id = unquote(path[len(prefix):])
            if not contact_id or "/" in contact_id:
                return self._send(404, {"error": "contact not found"})
            if not session_repository or contact_directory is None:
                return self._send(503, {"error": "directory unavailable"})
            session_id = session_cookie_value(self.headers.get("Cookie"))
            current = session_repository.resolve(session_id, clock())
            if current is None:
                return self._send(401, {"error": "authentication required"})
            if not session_repository.csrf_matches(
                session_id, self.headers.get("X-CSRF-Token")
            ):
                return self._send(403, {"error": "invalid CSRF token"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._send(400, {"error": "invalid Content-Length"})
            if length < 0:
                return self._send(400, {"error": "invalid Content-Length"})
            if length > MAX_CONTACT_EDIT_BYTES:
                return self._send(413, {"error": "contact edit is too large"})
            try:
                payload = json.loads(
                    self.rfile.read(length).decode("utf-8")
                ) if length else {}
            except ValueError:
                return self._send(400, {"error": "invalid JSON"})
            tenant_id = _request_tenant(tenant_resolver, current)
            values = payload.get("values")
            version = payload.get("recordVersion")
            if (
                not tenant_id or not isinstance(values, dict)
                or not isinstance(version, str) or not version
            ):
                return self._send(422, {
                    "error": "contact values and recordVersion are required"
                })
            changes = {
                "display_name": values.get("displayName"),
                "given_name": values.get("givenName") or None,
                "family_name": values.get("familyName") or None,
                "company_name": values.get("companyName") or None,
                "job_title": values.get("jobTitle") or None,
            }
            try:
                updated = contact_directory.update_contact(
                    tenant_id,
                    Actor.human(
                        current["principal_id"], [AUTHORITY_ADMINISTER]
                    ),
                    contact_id,
                    version,
                    changes,
                )
            except PermissionDenied:
                return self._send(404, {"error": "contact not found"})
            except StaleContactRecord:
                return self._send(409, {
                    "error": "El contacto cambió mientras lo editabas. Vuelve a abrirlo."
                })
            except ValueError as exc:
                return self._send(422, {"error": str(exc)})
            if updated is None:
                return self._send(404, {"error": "contact not found"})
            return self._send(200, {
                "contactId": updated["contact_id"],
                "recordVersion": updated["record_version"],
            })

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "") and identity is not None:
                return self._trust_challenge()
            workflow_operation = next((
                operation for operation in ("approve", "cancel", "retry")
                if path.startswith("/workflows/") and path.endswith("/%s" % operation)
            ), None)
            conversation_close = (
                path.startswith("/conversations/") and path.endswith("/close")
            )
            effect_decision = (
                path.startswith("/conversations/") and "/effects/" in path
            )
            if (
                path not in ("/concierge", "/contacts", "/contacts/branches", "/campaigns/preview")
                and workflow_operation is None
                and not conversation_close and not effect_decision
                and not (path.startswith("/campaigns/") and path.endswith("/authorize"))
            ):
                return self._send(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except ValueError:
                return self._send(400, {"error": "invalid JSON"})
            if path == "/campaigns/preview" or (
                path.startswith("/campaigns/") and path.endswith("/authorize")
            ):
                if not session_repository or campaign_service is None:
                    return self._send(503, {"error": "campaign service unavailable"})
                session_id = session_cookie_value(self.headers.get("Cookie"))
                current = session_repository.resolve(session_id, clock())
                if current is None:
                    return self._send(401, {"error": "authentication required"})
                if not session_repository.csrf_matches(
                    session_id, self.headers.get("X-CSRF-Token")
                ):
                    return self._send(403, {"error": "invalid CSRF token"})
                tenant_id = _request_tenant(tenant_resolver, current)
                if not tenant_id:
                    return self._send(404, {"error": "campaign service not found"})
                try:
                    if path == "/campaigns/preview":
                        preview = campaign_service.create_preview(
                            tenant_id, current["principal_id"], payload
                        )
                        return self._send(201, preview)
                    campaign_id = unquote(
                        path[len("/campaigns/"):-len("/authorize")].rstrip("/")
                    )
                    campaign = campaign_service.authorize(
                        tenant_id, current["principal_id"], campaign_id,
                        payload.get("envelopeHash"),
                    )
                    return self._send(202, {
                        "campaignId": campaign["campaign_id"],
                        "status": campaign["status"],
                    })
                except PermissionDenied:
                    return self._send(403, {"error": "campaign permission is required"})
                except CampaignPermissionDenied as exc:
                    return self._send(403, {"error": str(exc)})
                except (CampaignEnvelopeChanged, CampaignStateConflict, ValueError) as exc:
                    return self._send(422, {"error": str(exc)})
                except LookupError:
                    return self._send(404, {"error": "campaign not found"})
            if path == "/contacts":
                if not session_repository or contact_directory is None:
                    return self._send(503, {"error": "directory unavailable"})
                session_id = session_cookie_value(self.headers.get("Cookie"))
                current = session_repository.resolve(session_id, clock())
                if current is None:
                    return self._send(401, {"error": "authentication required"})
                if not session_repository.csrf_matches(
                    session_id, self.headers.get("X-CSRF-Token")
                ):
                    return self._send(403, {"error": "invalid CSRF token"})
                tenant_id = _request_tenant(tenant_resolver, current)
                values = payload.get("values")
                branch_id = payload.get("branchId")
                if not tenant_id or not isinstance(values, dict) or not isinstance(branch_id, str):
                    return self._send(422, {"error": "contact and branch are required"})
                consent = payload.get("consent")
                if consent:
                    evidence = consent.get("evidence") or {}
                    captured_at_local = evidence.get("capturedAtLocal")
                    capture_timezone = evidence.get("captureTimezone")
                    try:
                        local_moment = datetime.fromisoformat(captured_at_local)
                        if local_moment.tzinfo is None:
                            local_moment = local_moment.replace(
                                tzinfo=ZoneInfo(capture_timezone)
                            )
                        captured_at = local_moment.astimezone(timezone.utc)
                    except (TypeError, ValueError, ZoneInfoNotFoundError):
                        return self._send(422, {
                            "error": "consent date and time zone are invalid"
                        })
                    consent = {
                        "purposes": consent.get("purposes") or [],
                        "capture_method": evidence.get("captureMethod"),
                        "captured_at": captured_at,
                        "captured_at_local": captured_at_local,
                        "capture_timezone": capture_timezone,
                        "jurisdiction": evidence.get("jurisdiction"),
                        "disclosure_text": evidence.get("disclosureText"),
                        "legal_basis": evidence.get("legalBasis"),
                        "default_unchecked": evidence.get("defaultUnchecked"),
                        "source": "manual_form",
                    }
                try:
                    created = contact_directory.create_contact(
                        tenant_id,
                        Actor.human(current["principal_id"], [AUTHORITY_ADMINISTER]),
                        branch_id,
                        values.get("displayName"),
                        channel=payload.get("channel"),
                        address=payload.get("address"),
                        consent=consent,
                        given_name=values.get("givenName") or None,
                        family_name=values.get("familyName") or None,
                        company_name=values.get("companyName") or None,
                        job_title=values.get("jobTitle") or None,
                    )
                except (PermissionDenied, ValueError) as exc:
                    return self._send(422, {"error": str(exc)})
                return self._send(201, {
                    "contactId": created["contact_id"],
                    "addressId": created["address_id"],
                })
            if path == "/contacts/branches":
                if not session_repository or contacts_repository is None:
                    return self._send(503, {"error": "directory unavailable"})
                session_id = session_cookie_value(self.headers.get("Cookie"))
                current = session_repository.resolve(session_id, clock())
                if current is None:
                    return self._send(401, {"error": "authentication required"})
                if not session_repository.csrf_matches(
                    session_id, self.headers.get("X-CSRF-Token")
                ):
                    return self._send(403, {"error": "invalid CSRF token"})
                tenant_id = _request_tenant(tenant_resolver, current)
                if not tenant_id:
                    return self._send(404, {"error": "directory not found"})
                name = payload.get("name")
                if not isinstance(name, str) or not name.strip():
                    return self._send(422, {"error": "name is required"})
                if len(name.strip()) > 120:
                    return self._send(422, {"error": "name is too long"})
                parent_id = payload.get("parentBranchId")
                if parent_id is not None and (
                    not isinstance(parent_id, str) or not parent_id
                ):
                    return self._send(422, {
                        "error": "parentBranchId must be a branch identifier"
                    })
                kind = payload.get("kind") or (
                    "folder" if parent_id else "organization"
                )
                try:
                    if parent_id:
                        if contacts_permissions is None:
                            return self._send(503, {
                                "error": "directory permissions unavailable"
                            })
                        contacts_permissions.require(
                            tenant_id, current["principal_id"], parent_id,
                            DIMENSION_ADMINISTER,
                        )
                    else:
                        roots = contacts_repository.children(tenant_id)
                        if _principal_owns_root(
                            contacts_permissions, tenant_id,
                            current["principal_id"], roots,
                        ):
                            return self._send(409, {
                                "error": "a personal directory root already exists"
                            })
                        root_slug = _available_root_slug(
                            name.strip(),
                        )
                    branch = contacts_repository.create_branch(
                        tenant_id, name.strip(), kind=kind,
                        parent_branch_id=parent_id,
                        slug=root_slug if not parent_id else None,
                        owner_principal_id=(
                            current["principal_id"] if not parent_id else None
                        ),
                    )
                    if not parent_id and contacts_permissions is not None:
                        actor = Actor.human(
                            current["principal_id"], [AUTHORITY_ADMINISTER]
                        )
                        for dimension in DIMENSIONS:
                            contacts_permissions.grant(
                                tenant_id, branch["branch_id"],
                                current["principal_id"], dimension, actor,
                                reason="initial directory owner",
                            )
                except BranchNotFound:
                    return self._send(404, {"error": "parent branch not found"})
                except PermissionDenied:
                    return self._send(403, {
                        "error": "branch administration permission required"
                    })
                except InvalidBranchPlacement as exc:
                    return self._send(422, {"error": str(exc)})
                except UniqueViolation:
                    return self._send(409, {
                        "error": "a directory with that placement already exists"
                    })
                return self._send(201, {"branch": _contact_branch(
                    branch,
                    display_path=(
                        "/%s" % slugify(branch["name"])
                        if not parent_id else branch["path"]
                    ),
                )})
            if effect_decision:
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
                conversation_id, effect_id = _effect_path_parts(path)
                if not _valid_conversation_id(conversation_id) or not _valid_effect_id(effect_id):
                    return self._send(400, {"error": "invalid effect reference"})
                decision = payload.get("decision")
                if decision not in EFFECT_DECISIONS:
                    return self._send(422, {"error": "unsupported effect decision"})
                tenant_id = _request_tenant(tenant_resolver, current)
                store = getattr(dynamic_workflow_service, "conversation_store", None)
                owned = store.get(
                    conversation_id, tenant_id, current["principal_id"]
                ) if store and tenant_id else None
                if owned is None:
                    return self._send(404, {"error": "conversation not found"})
                try:
                    dynamic_workflow_service.decide_compound_effect(
                        conversation_id, tenant_id, current["principal_id"],
                        effect_id, decision,
                    )
                    # Approving one effect frees whatever was only waiting on
                    # it. Dispatch is the server's call, and it runs each
                    # freed effect on its own — never the group as a unit.
                    dynamic_workflow_service.dispatch_approved_effects(
                        conversation_id, tenant_id, current["principal_id"],
                    )
                except KeyError:
                    return self._send(404, {"error": "effect not found"})
                except ValueError:
                    return self._send(422, {"error": "unsupported effect decision"})
                except PermissionError:
                    return self._send(403, {"error": "effect not permitted"})
                refreshed = store.get(
                    conversation_id, tenant_id, current["principal_id"],
                    include_terminal=True,
                )
                if refreshed is None:
                    return self._send(404, {"error": "conversation not found"})
                return self._send(200, _conversation_response(refreshed))
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
                tenant_id = _request_tenant(tenant_resolver, current)
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
                    tenant_id = _request_tenant(tenant_resolver, current)
                    if not tenant_id:
                        return self._send(404, {"error": "conversation not found"})
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
            turns = []
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
            slack_message = _slack_turn_text(
                message, turns, requested_conversation_id
            )
            if requested_conversation_id and not _valid_conversation_id(requested_conversation_id):
                return self._send(400, {"error": "invalid conversation ID"})
            if _is_slack_turn(slack_message, requested_conversation_id) and current is None:
                return self._send(401, {"error": "authentication required"})
            if current and dynamic_workflow_service and tenant_resolver:
                tenant_id = _request_tenant(tenant_resolver, current)
                if _is_slack_turn(slack_message, requested_conversation_id) and not tenant_id:
                    return self._send(409, {"error": "tenant membership is required"})
                if tenant_id:
                    conversation_id = requested_conversation_id
                    if _is_slack_turn(slack_message, conversation_id):
                        try:
                            turn = dynamic_workflow_service.coordinate_slack_turn(
                                tenant_id, current["principal_id"], slack_message,
                                conversation_id=conversation_id,
                            )
                            turn = dynamic_workflow_service.advance_slack_turn(
                                turn.get("conversation_id") or conversation_id,
                                tenant_id, current["principal_id"], slack_message, turn,
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


def _effect_path_parts(path):
    """Split ``/conversations/<id>/effects/<effect_id>`` into its two halves.

    Returns ``(None, None)`` for anything that is not that shape, so the
    caller decides on a well-formed pair rather than on string prefixes.
    """
    remainder = path[len("/conversations/"):].rstrip("/")
    conversation, separator, effect = remainder.partition("/effects/")
    if not separator or not effect or "/" in effect:
        return None, None
    return unquote(conversation), unquote(effect)


def _valid_effect_id(value):
    return (
        isinstance(value, str) and value.startswith("effect:")
        and 1 <= len(value) <= 160
        and all(character.isalnum() or character in ":_-" for character in value)
    )


#: Decisions a person may take on a single effect. Dispatch and outcome
#: transitions belong to the server, so they are deliberately absent: a client
#: must not be able to declare an effect succeeded.
EFFECT_DECISIONS = frozenset({"approve", "reject", "correct", "cancel"})


def _is_slack_turn(message, conversation_id=None):
    text = normalize_name(message)
    return bool(conversation_id or "slack" in text or "#" in text or any(
        marker in text for marker in (
            "manda un mensaje", "mándale", "mandale", "qué dijo", "que dijo",
            "envia un mensaje", "enviar un mensaje", "canal ", "channel ",
            "reply there", "send a direct message", "post in ",
        )
    ))


def _slack_turn_text(message, history=None, conversation_id=None):
    """Recover one typed Slack intake from user-authored conversational context."""
    if conversation_id:
        return str(message or "")
    user_turns = [
        item.get("text", "") for item in (history or [])
        if isinstance(item, dict) and item.get("role") == "user"
        and isinstance(item.get("text"), str)
    ][-6:]
    combined = " ".join(user_turns + [str(message or "")]).strip()
    return combined if _is_slack_turn(combined) else str(message or "")


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
    if turn.get("draft"):
        draft = turn["draft"]
        response["draft"] = {
            "draftHash": draft.get("draft_hash"),
            "destination": draft.get("destination_label"),
            "text": draft.get("text"),
            "workflowId": draft.get("workflow_run_id"),
            "revisionId": draft.get("workflow_revision_id"),
        }
    if turn.get("workflow"):
        response["workflow"] = turn["workflow"]
    return {key: value for key, value in response.items() if value is not None}


def _conversation_response(conversation):
    if (conversation.get("status") == "resolving"
            and not conversation.get("resolution_request")
            and not conversation.get("workflow_revision_id")):
        locale = conversation.get("locale", "es")
        return {
            "state": "needs_input",
            "conversationId": conversation["conversation_id"],
            "need": {
                "kind": "missing", "field": "operation", "options": [],
                "question": ("¿Qué quieres hacer en Slack?" if locale == "es"
                             else "What would you like to do in Slack?"),
            },
        }
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
        if presentation.get("period") is not None:
            result["period"] = presentation["period"]
        if presentation.get("partial_reason"):
            result["partialReason"] = presentation["partial_reason"]
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
    result.update(_projection_envelope(conversation))
    group = _effect_group_projection(conversation)
    if group is not None:
        result["effectGroup"] = group
    return result


#: Statuses from which nothing further can happen on this conversation.
TERMINAL_STATES = frozenset({
    "succeeded", "ready", "failed", "retryable_failure", "unknown_outcome",
    "cancelled", "expired", "closed",
})

#: What the server will accept next, keyed by where the conversation is. The
#: client renders from this rather than inferring, so it can never offer an
#: action the server would refuse.
ALLOWED_ACTIONS = {
    "awaiting_approval": ("approve", "reject", "correct"),
    "needs_input": ("answer", "correct"),
    "interpreting": ("correct",),
    "resolving": ("correct",),
    "retrieving": ("cancel",),
}


def _projection_envelope(conversation):
    """State the client needs to trust a snapshot, not just render it."""
    status = conversation["status"]
    state_version = int(conversation.get("state_version") or 1)
    projected = conversation.get("projected_version")
    return {
        "stateVersion": state_version,
        "terminal": status in TERMINAL_STATES,
        "allowedActions": list(ALLOWED_ACTIONS.get(status, ())),
        # A read model can lag its source. Saying so lets the client show
        # "catching up" instead of presenting stale state as settled.
        "projectionLag": (
            projected is not None and int(projected) < state_version
        ),
    }


def _effect_group_projection(conversation):
    """One row per effect, each answerable on its own.

    A group is not a transaction. Approving one effect must never authorise
    another, and a mixed outcome must not be flattened into a verdict the
    group never had.
    """
    group = conversation.get("effect_group")
    if not isinstance(group, dict) or not group.get("effects"):
        return None
    effects, completed = [], 0
    for effect in group["effects"]:
        status = effect.get("status")
        if status in ("succeeded", "completed"):
            completed += 1
        reinforced = bool(effect.get("reinforced"))
        row = {
            "effectId": effect.get("effect_id"),
            "capabilityId": effect.get("capability_id"),
            "summary": effect.get("summary"),
            "status": status,
            "reinforced": reinforced,
            "allowedActions": (
                ["approve", "reject"] if status == "awaiting_approval" else []
            ),
            # Risk should not be one click away from invisible: an effect that
            # needs reinforced approval opens its details by default.
            "detailsExpanded": reinforced,
        }
        if effect.get("recovery"):
            row["recovery"] = effect["recovery"]
        effects.append(row)
    return {
        "groupId": group.get("group_id"),
        "effects": effects,
        "summary": "%d of %d completed" % (completed, len(effects)),
    }


def _classified_recovery(exc, conversation_id=None):
    code = str(exc).split(":", 1)[0]
    action = "upgrade_scopes" if code == "missing_scope" else "reconnect"
    return {
        "state": "retryable_failure", "conversationId": conversation_id,
        "error": {"code": code}, "recovery": {"action": action},
    }


def _request_tenant(tenant_resolver, current):
    """The account this request acts for, or ``None`` when nobody mapped it.

    An unmapped principal is folded into the same "no tenant" branch each
    caller already has, and every one of those answers not-found. That shape
    is deliberate: forbidden would tell a caller that the conversation it
    named is real and merely out of reach, which is most of what enumerating
    identifiers is trying to learn. Not-found says the same thing to a bad
    identifier and to someone else's.

    The log line names neither the principal nor the tenant, for the same
    reason the response does not.
    """
    if tenant_resolver is None:
        return current.get("tenant_id")
    try:
        return tenant_resolver(current["principal_id"])
    except UnmappedPrincipalError:
        logger.warning("refused a request from a principal bound to no tenant")
        return None


def _contact_branch(
    branch, children=None, contact_count=0, display_path=None,
):
    """Browser contract for one directory branch; tenant ids never leave."""
    return {
        "branchId": branch["branch_id"],
        "parentBranchId": branch.get("parent_branch_id"),
        "name": branch["name"],
        "path": display_path or branch["path"],
        "kind": branch["kind"],
        "depth": branch["depth"],
        "contactCount": contact_count,
        "children": children or [],
    }


def _principal_owns_root(permissions, tenant_id, principal_id, roots):
    """Whether this principal already received a root's initial owner grant.

    A tenant can contain several personal directories.  A grant inherited or
    delegated later does not turn somebody else's directory into the user's
    own root, so ownership is identified by the direct grants written when the
    root was created.
    """
    if permissions is None:
        return bool(roots)
    for root in roots:
        if root.get("owner_principal_id") == principal_id:
            return True
    decisions_on_branch = getattr(permissions, "decisions_on_branch", None)
    if not callable(decisions_on_branch):
        return False
    for root in roots:
        for decision in decisions_on_branch(tenant_id, root["branch_id"]):
            if (
                decision.get("principal_id") == principal_id
                and decision.get("dimension") == DIMENSION_ADMINISTER
                and decision.get("effect") == "grant"
                and decision.get("reason") == "initial directory owner"
            ):
                return True
    return False


def _available_root_slug(name):
    """Return a tenant-unique technical slug without changing the visible name."""
    return "%s-%s" % (slugify(name), secrets.token_hex(6))


def _contact_summary(contact, version, can_edit=False):
    """The branch table's bounded identity projection; no destinations."""
    return {
        "contactId": contact["contact_id"],
        "displayName": contact["display_name"],
        "givenName": contact.get("given_name"),
        "familyName": contact.get("family_name"),
        "companyName": contact.get("company_name"),
        "jobTitle": contact.get("job_title"),
        "status": contact["status"],
        "source": contact["source"],
        "recordVersion": version,
        "canEdit": can_edit,
    }


def _contact_branch_tree(
    repository, tenant_id, parent_branch_id=None, visible_branch_ids=None,
    parent_display_path="",
):
    branches = repository.children(tenant_id, parent_branch_id)
    result = []
    for branch in branches:
        display_path = "%s/%s" % (
            parent_display_path, slugify(branch["name"]),
        )
        children = _contact_branch_tree(
            repository, tenant_id, branch["branch_id"], visible_branch_ids,
            parent_display_path=display_path,
        )
        if visible_branch_ids is not None and \
                branch["branch_id"] not in visible_branch_ids:
            result.extend(children)
            continue
        result.append(_contact_branch(
            branch, children=children,
            contact_count=len(repository.contacts_in_branch(
                tenant_id, branch["branch_id"]
            )),
            display_path=display_path,
        ))
    return result


def _tenant_resolver(identity_repository=None):
    """Which account a principal acts for, or a refusal.

    This used to end in ``or local_tenant``, so a principal absent from
    ``TESSERA_PRINCIPAL_TENANTS_JSON`` -- a rotated identifier, a fresh
    deployment, a typo in the configured JSON -- landed in
    ``TESSERA_LOCAL_TENANT_ID`` and acted there as a member. That was
    tolerable while conversation state was the only thing behind the
    boundary. It is not tolerable now that a directory of other people's
    names and phone numbers sits behind the same one, because the fallback
    would be the leak: whoever holds the local tenant's contacts would be
    handing them to every principal nobody had mapped (KTD11).

    Unmapped is now a refusal. ``TESSERA_LOCAL_TENANT_ID`` still names a
    tenant for local work -- it just has to be mapped to a principal like any
    other, rather than catching everything that falls through.
    """
    try:
        mapping = json.loads(os.environ.get("TESSERA_PRINCIPAL_TENANTS_JSON", "{}"))
    except ValueError:
        mapping = {}
    if not isinstance(mapping, dict):
        mapping = {}

    return MembershipTenantResolver(
        mapping, identity_repository or IdentityRepository()
    )


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

    identity = concierge_identity()
    agent, label = build_agent(
        registry_url=args.registry_url,
        agent_marketplace_url=args.agent_marketplace_url,
        vault_url=args.vault_url,
        action_broker_url=args.action_broker_url,
        action_broker_token=args.action_broker_token,
        agent_id=identity[2],
    )
    # Printed once at boot: the trusted-endpoint map and the worker both name
    # this principal, and it is derived from a key this process generates.
    logger.warning("concierge agent principal: %s", identity[2])
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
    contacts_repository = ContactsRepository(Database())
    contacts_permissions = BranchPermissionsRepository(
        contacts_repository.db, contacts=contacts_repository,
    )
    contact_directory = ContactDirectory(
        contacts_repository.db,
        contacts=contacts_repository,
        permissions=contacts_permissions,
    )
    contacts_consent = ContactsConsentRepository(contacts_repository.db)
    campaign_repository = CampaignRepository(
        os.environ.get("CAMPAIGN_DATABASE", "tessera-campaigns.db")
    )
    broker_identity = os.environ.get(
        "CREDENTIAL_BROKER_IDENTITY", "service:credential-broker"
    )
    ingestion_identity = os.environ.get(
        "OAUTH_INGESTION_IDENTITY", "service:oauth-ingestion"
    )
    managed_crypto = ManagedOAuthCrypto(
        AWSKMSClient(), os.environ["MANAGED_OAUTH_KMS_KEY_ID"],
        ingestion_identities={ingestion_identity},
        broker_identity=broker_identity,
    )
    campaign_service = CampaignService(
        campaign_repository, contacts_repository,
        ContactsAccess(
            contacts_repository.db, contacts=contacts_repository,
            permissions=contacts_permissions, consent=contacts_consent,
        ),
        contacts_permissions, contacts_consent, connection_repository,
        VaultService(
            repository=VaultRepository(), managed_oauth_crypto=managed_crypto
        ),
        broker_identity=broker_identity,
        callback_base=os.environ.get("TWILIO_PUBLIC_CALLBACK_BASE"),
    )
    tenant_resolver = _tenant_resolver()
    dynamic_service = DynamicWorkflowService(
        agent.brain,
        provider_definitions(),
        connection_repository,
        workflow_repository,
        rollout_version=os.environ.get("TESSERA_CAPABILITY_ROLLOUT_VERSION", "production-v1"),
        shadow_mode=os.environ.get("TESSERA_DYNAMIC_PLANNER_SHADOW", "true").lower() != "false",
        conversation_store=ConciergeConversationStore(workflow_repository),
        # Family state and the account-wide emergency stop are durable
        # per-tenant records, so an administrator changes them without a
        # restart and two accounts on this process can hold different answers.
        control_plane=build_tenant_control_plane(
            connection_repository, provider_definitions()
        ),
    )
    httpd = ThreadingHTTPServer(
        (args.host, args.port),
        _make_handler(
            agent, label, args.runner_url, args.registry_url,
            workflow_repository, session_repository, dynamic_service,
            tenant_resolver, identity=identity,
            contacts_repository=contacts_repository,
            contacts_permissions=contacts_permissions,
            contact_directory=contact_directory,
            campaign_service=campaign_service,
        ),
    )
    print("Concierge on http://%s:%d  (brain: %s)" % (args.host, args.port, label))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
