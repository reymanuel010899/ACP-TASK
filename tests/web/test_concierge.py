import http.client
import json
import threading

import pytest

from libs.tenancy import UnmappedPrincipalError
from libs.contacts_repository import record_version
from libs.contacts_import import StaleContactRecord
from web.concierge import (
    _contact_branch_tree, _make_handler,
    _classified_recovery, _conversation_response, _is_slack_turn,
    _request_tenant, _slack_turn_text, _tenant_resolver, _turn_response,
)


class _Directory:
    def children(self, tenant_id, parent_branch_id=None):
        assert tenant_id == "org:local"
        rows = {
            None: [{"branch_id": "branch:root", "parent_branch_id": None,
                    "name": "General", "path": "/general",
                    "kind": "organization", "depth": 0}],
            "branch:root": [{"branch_id": "branch:clients",
                              "parent_branch_id": "branch:root",
                              "name": "Clientes", "path": "/general/clientes",
                              "kind": "folder", "depth": 1}],
            "branch:clients": [],
        }
        return rows[parent_branch_id]

    def contacts_in_branch(self, tenant_id, branch_id):
        assert tenant_id == "org:local"
        return [{
            "contact_id": "contact:1", "display_name": "Rey Ferreras",
            "given_name": "Rey", "family_name": "Ferreras",
            "company_name": "Tessera", "job_title": "AI Engineer",
            "status": "active", "source": "manual",
        }] if branch_id == "branch:clients" else []

    def addresses(self, tenant_id, contact_id):
        assert tenant_id == "org:local"
        assert contact_id == "contact:1"
        return []


def test_contact_branch_tree_is_tenant_bound_and_browser_safe():
    tree = _contact_branch_tree(_Directory(), "org:local")

    assert tree == [{
        "branchId": "branch:root", "parentBranchId": None,
        "name": "General", "path": "/general", "kind": "organization",
        "depth": 0, "contactCount": 0,
        "children": [{
            "branchId": "branch:clients", "parentBranchId": "branch:root",
            "name": "Clientes", "path": "/general/clientes", "kind": "folder",
            "depth": 1, "contactCount": 1, "children": [],
        }],
    }]
    assert "tenant" not in str(tree).lower()


class _ContactSessions:
    def __init__(self, principal_id="principal:margo"):
        self.principal_id = principal_id

    def resolve(self, session_id, _now):
        if session_id == "valid-session":
            return {"principal_id": self.principal_id}
        return None

    def csrf_matches(self, session_id, token):
        return session_id == "valid-session" and token == "valid-csrf"


class _WritableDirectory(_Directory):
    def __init__(self):
        self.created = []

    def children(self, tenant_id, parent_branch_id=None):
        assert tenant_id == "org:local"
        return []

    def create_branch(
        self, tenant_id, name, kind, parent_branch_id=None, slug=None,
        owner_principal_id=None,
    ):
        self.created.append((
            tenant_id, name, kind, parent_branch_id, slug, owner_principal_id,
        ))
        return {
            "branch_id": "branch:new", "parent_branch_id": parent_branch_id,
            "name": name, "slug": slug or "general",
            "path": "/%s" % (slug or "general"), "kind": kind, "depth": 0,
        }


def _contacts_request(
    method, path, directory, body=None, csrf=None, cookie=True, permissions=None,
    contact_directory=None, principal_id="principal:margo",
):
    handler = _make_handler(
        None, "rule", "http://runner.invalid",
        session_repository=_ContactSessions(principal_id), contacts_repository=directory,
        contacts_permissions=permissions,
        contact_directory=contact_directory,
        tenant_resolver=lambda principal_id: "org:local",
    )
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection(*server.server_address)
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = "tessera_session=valid-session"
        if csrf:
            headers["X-CSRF-Token"] = csrf
        connection.request(
            method, path, body=json.dumps(body).encode() if body else None,
            headers=headers,
        )
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        server.shutdown()
        server.server_close()


class _ContactDirectoryWriter:
    def __init__(self):
        self.created = []
        self.updated = []

    def create_contact(self, tenant_id, actor, branch_id, display_name, **values):
        self.created.append((tenant_id, actor.principal_id, branch_id, display_name, values))
        return {"contact_id": "contact:new", "address_id": "address:new"}

    def update_contact(
        self, tenant_id, actor, contact_id, record_version, changes,
    ):
        self.updated.append((
            tenant_id, actor.principal_id, contact_id, record_version, changes,
        ))
        return {"contact_id": contact_id, "record_version": "version:new"}


def test_manual_contact_endpoint_creates_inside_the_selected_branch():
    writer = _ContactDirectoryWriter()
    status, payload = _contacts_request(
        "POST", "/contacts", _Directory(), csrf="valid-csrf",
        contact_directory=writer,
        body={
            "branchId": "branch:clients",
            "values": {"displayName": "Ana", "givenName": "Ana"},
            "channel": "sms",
            "address": "+15165550100",
        },
    )

    assert status == 201
    assert payload == {"contactId": "contact:new", "addressId": "address:new"}
    assert writer.created[0][:4] == (
        "org:local", "principal:margo", "branch:clients", "Ana",
    )


def test_contact_edit_endpoint_updates_identity_with_the_read_version():
    writer = _ContactDirectoryWriter()
    status, payload = _contacts_request(
        "PATCH", "/contacts/contact%3A1", _Directory(), csrf="valid-csrf",
        contact_directory=writer,
        body={
            "recordVersion": "version:read",
            "values": {
                "displayName": "Rey M. Ferreras",
                "givenName": "Rey",
                "familyName": "Ferreras",
                "companyName": "Tessera",
                "jobTitle": "AI Lead",
            },
        },
    )

    assert status == 200
    assert payload == {
        "contactId": "contact:1", "recordVersion": "version:new",
    }
    assert writer.updated == [(
        "org:local", "principal:margo", "contact:1", "version:read",
        {
            "display_name": "Rey M. Ferreras",
            "given_name": "Rey",
            "family_name": "Ferreras",
            "company_name": "Tessera",
            "job_title": "AI Lead",
        },
    )]


def test_contact_edit_requires_csrf_before_calling_the_directory():
    writer = _ContactDirectoryWriter()
    status, payload = _contacts_request(
        "PATCH", "/contacts/contact%3A1", _Directory(),
        contact_directory=writer,
        body={"recordVersion": "version:read", "values": {"displayName": "Rey"}},
    )

    assert status == 403
    assert payload == {"error": "invalid CSRF token"}
    assert writer.updated == []


def test_stale_contact_edit_is_a_conflict_that_requires_a_fresh_read():
    class StaleWriter(_ContactDirectoryWriter):
        def update_contact(self, *args, **kwargs):
            raise StaleContactRecord()

    status, payload = _contacts_request(
        "PATCH", "/contacts/contact%3A1", _Directory(), csrf="valid-csrf",
        contact_directory=StaleWriter(),
        body={"recordVersion": "version:old", "values": {"displayName": "Rey"}},
    )

    assert status == 409
    assert "Vuelve a abrirlo" in payload["error"]


def test_manual_contact_endpoint_converts_local_consent_time_to_utc():
    writer = _ContactDirectoryWriter()
    status, _payload = _contacts_request(
        "POST", "/contacts", _Directory(), csrf="valid-csrf",
        contact_directory=writer,
        body={
            "branchId": "branch:clients",
            "values": {"displayName": "Ana"},
            "channel": "sms",
            "address": "+15165550100",
            "consent": {
                "purposes": ["service"],
                "evidence": {
                    "captureMethod": "verbal_recorded",
                    "capturedAtLocal": "2026-08-08T12:25",
                    "captureTimezone": "America/New_York",
                    "jurisdiction": "US",
                    "disclosureText": "Autorizo mensajes de servicio.",
                    "legalBasis": "consent",
                    "defaultUnchecked": True,
                },
            },
        },
    )

    assert status == 201
    consent = writer.created[0][4]["consent"]
    assert consent["captured_at"].isoformat() == "2026-08-08T16:25:00+00:00"
    assert consent["captured_at_local"] == "2026-08-08T12:25"


def test_contacts_branches_require_a_session_and_return_the_tenant_tree():
    assert _contacts_request("GET", "/contacts/branches", _Directory(), cookie=False) == (
        401, {"error": "authentication required"},
    )
    status, payload = _contacts_request("GET", "/contacts/branches", _Directory())
    assert status == 200
    assert payload["branches"][0]["branchId"] == "branch:root"


def test_creating_a_branch_requires_csrf_and_uses_the_session_tenant():
    directory = _WritableDirectory()
    assert _contacts_request(
        "POST", "/contacts/branches", directory,
        body={"name": "General", "kind": "organization"},
    ) == (403, {"error": "invalid CSRF token"})

    status, payload = _contacts_request(
        "POST", "/contacts/branches", directory,
        body={"name": "General", "kind": "organization"}, csrf="valid-csrf",
    )
    assert status == 201
    assert payload["branch"]["branchId"] == "branch:new"
    assert directory.created[0][:4] == (
        "org:local", "General", "organization", None,
    )
    assert directory.created[0][4].startswith("general-")
    assert directory.created[0][5] == "principal:margo"


class _PersonalDirectories:
    def __init__(self):
        self.roots = []

    def children(self, tenant_id, parent_branch_id=None):
        assert tenant_id == "org:local"
        if parent_branch_id is not None:
            return []
        return list(self.roots)

    def create_branch(
        self, tenant_id, name, kind, parent_branch_id=None, slug=None,
        owner_principal_id=None,
    ):
        branch = {
            "branch_id": "branch:%s" % (len(self.roots) + 1),
            "parent_branch_id": parent_branch_id,
            "name": name,
            "slug": slug,
            "path": "/%s" % slug,
            "kind": kind,
            "depth": 0,
            "owner_principal_id": owner_principal_id,
        }
        self.roots.append(branch)
        return branch


class _PersonalDirectoryPermissions:
    def __init__(self):
        self.decisions = []

    def decisions_on_branch(self, tenant_id, branch_id):
        return [
            row for row in self.decisions
            if row["tenant_id"] == tenant_id and row["branch_id"] == branch_id
        ]

    def grant(
        self, tenant_id, branch_id, principal_id, dimension, _actor, reason=None,
    ):
        self.decisions.append({
            "tenant_id": tenant_id,
            "branch_id": branch_id,
            "principal_id": principal_id,
            "dimension": dimension,
            "effect": "grant",
            "reason": reason,
        })


def test_two_users_can_create_personal_roots_with_the_same_visible_name():
    directory = _PersonalDirectories()
    permissions = _PersonalDirectoryPermissions()

    first = _contacts_request(
        "POST", "/contacts/branches", directory,
        body={"name": "Contactos", "kind": "organization"},
        csrf="valid-csrf", permissions=permissions,
        principal_id="principal:margo",
    )
    second = _contacts_request(
        "POST", "/contacts/branches", directory,
        body={"name": "Contactos", "kind": "organization"},
        csrf="valid-csrf", permissions=permissions,
        principal_id="principal:lucia",
    )

    assert first[0] == 201
    assert second[0] == 201
    assert first[1]["branch"]["path"] == "/contactos"
    assert second[1]["branch"]["path"] == "/contactos"
    assert [root["name"] for root in directory.roots] == ["Contactos", "Contactos"]
    assert len({root["slug"] for root in directory.roots}) == 2


def test_one_user_cannot_accidentally_create_a_second_personal_root():
    directory = _PersonalDirectories()
    permissions = _PersonalDirectoryPermissions()
    request = dict(
        method="POST", path="/contacts/branches", directory=directory,
        body={"name": "Contactos", "kind": "organization"},
        csrf="valid-csrf", permissions=permissions,
        principal_id="principal:margo",
    )

    assert _contacts_request(**request)[0] == 201
    assert _contacts_request(**request) == (
        409, {"error": "a personal directory root already exists"},
    )


class _DeniedBranchAdministration:
    def require(self, tenant_id, principal_id, branch_id, dimension):
        from libs.contacts_permissions import PermissionDenied
        raise PermissionDenied(dimension)


class _AllowedBranchView:
    def require(self, tenant_id, principal_id, branch_id, dimension):
        return True

    def authorized_branches(self, tenant_id, principal_id, dimension):
        return []

    def effective(self, tenant_id, principal_id, branch_id):
        return {"edit": True}


def test_another_users_hidden_root_looks_like_an_empty_personal_directory():
    status, payload = _contacts_request(
        "GET", "/contacts/branches", _Directory(),
        permissions=_AllowedBranchView(),
    )

    assert status == 200
    assert payload == {"branches": []}


def test_contacts_table_endpoint_lists_only_the_named_visible_branch():
    status, payload = _contacts_request(
        "GET", "/contacts?branchId=branch%3Aclients", _Directory(),
        permissions=_AllowedBranchView(),
    )

    assert status == 200
    contact = _Directory().contacts_in_branch(
        "org:local", "branch:clients"
    )[0]
    assert payload == {"contacts": [{
        "contactId": "contact:1", "displayName": "Rey Ferreras",
        "givenName": "Rey", "familyName": "Ferreras",
        "companyName": "Tessera", "jobTitle": "AI Engineer",
        "status": "active", "source": "manual",
        "recordVersion": record_version(contact, []),
        "canEdit": True,
    }]}


def test_creating_a_subbranch_requires_inherited_administration_permission():
    directory = _WritableDirectory()
    status, payload = _contacts_request(
        "POST", "/contacts/branches", directory,
        body={"name": "Clientes", "kind": "folder", "parentBranchId": "branch:root"},
        csrf="valid-csrf", permissions=_DeniedBranchAdministration(),
    )

    assert status == 403
    assert payload == {"error": "branch administration permission required"}
    assert directory.created == []


def test_a_rotated_principal_no_longer_inherits_the_local_tenant(monkeypatch):
    """The inverse of what this asserted until U5.

    It used to prove that a principal absent from the configured mapping
    still resolved -- to `TESSERA_LOCAL_TENANT_ID`. That was the behaviour
    that made a rotated identifier keep working, and it is the same behaviour
    that would hand the local tenant's contact directory to any principal
    nobody had mapped (KTD11). Rotation now has to be configured, and an
    unmapped principal is refused.
    """
    monkeypatch.setenv("TESSERA_PRINCIPAL_TENANTS_JSON", "{}")
    monkeypatch.setenv("TESSERA_LOCAL_TENANT_ID", "org:local")

    with pytest.raises(UnmappedPrincipalError):
        _tenant_resolver()("new-principal")


def test_the_local_tenant_is_reached_by_being_mapped_like_any_other(monkeypatch):
    monkeypatch.setenv(
        "TESSERA_PRINCIPAL_TENANTS_JSON", '{"new-principal": "org:local"}',
    )
    monkeypatch.delenv("TESSERA_LOCAL_TENANT_ID", raising=False)

    assert _tenant_resolver()("new-principal") == "org:local"


def test_an_unmapped_principal_reaches_the_handlers_no_tenant_branch(monkeypatch):
    """Refused, and refused in the shape the caller cannot learn from.

    Every call site guards on a falsy tenant and answers not-found. Letting
    the exception escape instead would surface as a 500, which is its own
    signal, and letting it through as a tenant would be the leak.
    """
    monkeypatch.setenv("TESSERA_PRINCIPAL_TENANTS_JSON", "{}")
    monkeypatch.setenv("TESSERA_LOCAL_TENANT_ID", "org:local")
    resolver = _tenant_resolver()

    assert _request_tenant(resolver, {"principal_id": "new-principal"}) is None
    assert _request_tenant(
        None, {"principal_id": "p", "tenant_id": "org:acme"},
    ) == "org:acme"


def test_natural_channel_message_is_routed_to_typed_slack_conversation():
    assert _is_slack_turn("envía un mensaje al canal tessera-test")
    assert _is_slack_turn("quiero publicar en el canal general")


def test_slack_followup_recovers_channel_and_message_from_user_history():
    history = [
        {"role": "user", "text": "quiero enviar algo por Slack"},
        {"role": "concierge", "text": "¿En qué canal?"},
        {"role": "user", "text": "en el canal tessera-test"},
        {"role": "concierge", "text": "¿Cuál mensaje?"},
        {"role": "user", "text": "que diga estoy aquí, ¿quién es?"},
    ]

    recovered = _slack_turn_text("sí, mándalo", history, None)

    assert _is_slack_turn(recovered)
    assert "canal tessera-test" in recovered
    assert "que diga estoy aquí" in recovered


def test_slack_history_preserves_exact_quoted_message_through_confirmation():
    from agents.orchestrator.slack_conversation import interpret_slack_turn

    history = [
        {"role": "user", "text": "quiero enviar un mensaje por Slack"},
        {"role": "user", "text": "en el canal tessera-test"},
        {"role": "user", "text": 'mándame el mensaje que diga "estoy aquí, ¿quién es?"'},
    ]

    recovered = _slack_turn_text("sí, mándalo", history, None)
    turn = interpret_slack_turn(recovered)

    assert turn.operation == "post"
    assert turn.channel_name == "tessera-test"
    assert turn.message_text == "estoy aquí, ¿quién es?"


def test_orphan_resolving_conversation_becomes_actionable_need():
    from web.concierge import _conversation_response

    response = _conversation_response({
        "conversation_id": "conversation:orphan",
        "status": "resolving",
        "workflow_run_id": None,
        "workflow_revision_id": None,
    })

    assert response["state"] == "needs_input"
    assert response["need"]["field"] == "operation"


def test_needs_input_contract_has_one_question_and_opaque_conversation_id():
    response = _turn_response({
        "state": "needs_input", "conversation_id": "conversation:1",
        "need": {"field": "message_text", "question": "¿Qué mensaje quieres enviar?"},
        "resolved": {"active_channel": {"id": "C-secret"}},
    })
    assert response == {
        "state": "needs_input", "conversationId": "conversation:1",
        "need": {"field": "message_text", "question": "¿Qué mensaje quieres enviar?"},
    }
    assert "C-secret" not in str(response)


def test_poll_contract_returns_grounded_answer_and_safe_exact_draft():
    completed = _conversation_response({
        "status": "ready", "conversation_id": "conversation:1",
        "presentation": {"answer": "Resumen", "citations": [{"permalink": "https://slack/source"}], "partial": True,
                         "period": {"oldest": "1", "latest": "2"},
                         "partial_reason": "rate_limit"},
        "workflow_run_id": "workflow:1", "workflow_revision_id": "revision:1",
    })
    assert completed["answer"] == "Resumen"
    assert completed["citations"] == [{"permalink": "https://slack/source"}]
    assert completed["period"] == {"oldest": "1", "latest": "2"}
    assert completed["partialReason"] == "rate_limit"
    draft = _conversation_response({
        "status": "awaiting_approval", "conversation_id": "conversation:2",
        "pending_draft": {"draft_hash": "hash", "destination_label": "#general",
                          "text": "Hola", "workflow_run_id": "workflow:2",
                          "workflow_revision_id": "revision:2", "channel_id": "C-secret"},
    })
    assert draft["draft"]["destination"] == "#general"
    assert draft["draft"]["text"] == "Hola"
    assert "C-secret" not in str(draft)


def test_known_recovery_is_structured_and_redacts_exception_details():
    response = _classified_recovery(
        PermissionError("missing_scope:users:read xoxb-secret"), "conversation:1"
    )
    assert response["error"] == {"code": "missing_scope"}
    assert response["recovery"] == {"action": "upgrade_scopes"}
    assert "xoxb" not in str(response)


def test_conversation_polling_projects_state_without_resuming_the_turn():
    import inspect

    import web.concierge as concierge

    get_source = inspect.getsource(concierge._make_handler).split(
        "def do_GET", 1
    )[1].split("def do_POST", 1)[0]
    for mutator in (
        "resume_resolved_slack_turn", "coordinate_slack_turn",
        "advance_slack_turn", "apply_slack_resolver_completion",
        "continue_slack_resolver_run", ".update(",
    ):
        assert mutator not in get_source

    pending = _conversation_response({
        "status": "resolving", "conversation_id": "conversation:3",
        "resolution_request": {
            "field": "channel", "resolver_run_id": "slack-resolver:1",
            "text": "Manda en #general que Hola equipo",
        },
        "workflow_run_id": "workflow:3", "workflow_revision_id": "revision:3",
    })

    assert pending["state"] == "resolving"
    assert pending["workflow"] == {
        "workflowId": "workflow:3", "revisionId": "revision:3",
    }
    assert "resolver_run_id" not in str(pending)
    assert "Hola equipo" not in str(pending)
