"""The HTTP contract for deciding one effect of a compound request.

This route authorises a real Slack write, so the checks that matter are the
ones a caller could otherwise skip: a session, a CSRF token, ownership of the
conversation, and a decision a person is actually allowed to take. Dispatch and
outcome belong to the server; a client must not be able to declare an effect
succeeded by naming it.
"""

import io
import json

import pytest

from web.concierge import _make_handler


class _Sessions:
    def __init__(self, principal="user:1", csrf="csrf-1"):
        self._principal, self._csrf = principal, csrf

    def resolve(self, session_id, _now):
        return {"principal_id": self._principal, "tenant_id": "org:1"} \
            if session_id == "s1" else None

    def csrf_matches(self, session_id, token):
        return session_id == "s1" and token == self._csrf


class _Store:
    def __init__(self, conversation):
        self._conversation = conversation

    def get(self, conversation_id, tenant_id, principal_id, include_terminal=False):
        if conversation_id != self._conversation["conversation_id"]:
            return None
        if principal_id != "user:1" or tenant_id != "org:1":
            return None
        return self._conversation


class _Service:
    def __init__(self, conversation, decide_error=None):
        self.conversation_store = _Store(conversation)
        self.decisions, self.dispatches = [], []
        self._decide_error = decide_error

    def decide_compound_effect(self, conversation_id, tenant_id, principal_id,
                               effect_id, decision):
        if self._decide_error is not None:
            raise self._decide_error
        self.decisions.append((conversation_id, effect_id, decision))
        return {}

    def dispatch_approved_effects(self, conversation_id, tenant_id, principal_id):
        self.dispatches.append(conversation_id)
        return []


def _conversation():
    return {
        "conversation_id": "conversation:c1",
        "status": "awaiting_approval",
        "state_version": 3,
        "effect_group": {
            "group_id": "group:1",
            "effects": [{
                "effect_id": "effect:1", "capability_id": "slack.reaction.add",
                "summary": "add reaction #general", "status": "awaiting_approval",
            }],
        },
    }


class _Recorder(io.BytesIO):
    """Captures the response bytes the handler writes."""


def _call(service, body, cookie="tessera_session=s1", csrf="csrf-1",
          path="/conversations/conversation%3Ac1/effects/effect%3A1"):
    handler_class = _make_handler(
        agent=None, label="test", runner_url=None,
        workflow_repository=object(), session_repository=_Sessions(),
        dynamic_workflow_service=service,
        tenant_resolver=lambda principal: "org:1",
        clock=lambda: 0,
    )
    raw = json.dumps(body).encode("utf-8")
    handler = handler_class.__new__(handler_class)
    handler.path = path
    handler.rfile = io.BytesIO(raw)
    handler.wfile = _Recorder()
    handler.headers = {
        "Content-Length": str(len(raw)),
        "Cookie": cookie, "X-CSRF-Token": csrf,
    }
    captured = {}

    def _send(status, payload):
        captured["status"], captured["body"] = status, payload

    handler._send = _send
    handler.do_POST()
    return captured


def test_an_approval_decides_one_effect_and_then_dispatches_what_it_freed():
    service = _Service(_conversation())
    result = _call(service, {"decision": "approve"})

    assert result["status"] == 200
    assert service.decisions == [("conversation:c1", "effect:1", "approve")]
    # Dispatch runs after the decision, because approving one effect can free
    # another that was only waiting on it.
    assert service.dispatches == ["conversation:c1"]
    assert result["body"]["effectGroup"]["effects"][0]["effectId"] == "effect:1"


def test_a_missing_csrf_token_decides_nothing():
    service = _Service(_conversation())
    result = _call(service, {"decision": "approve"}, csrf="wrong")

    assert result["status"] == 403
    assert service.decisions == []


def test_an_unauthenticated_caller_decides_nothing():
    service = _Service(_conversation())
    result = _call(service, {"decision": "approve"}, cookie="tessera_session=other")

    assert result["status"] == 401
    assert service.decisions == []


@pytest.mark.parametrize("decision", ["succeeded", "dispatched", "failed", "", None])
def test_a_client_cannot_declare_an_outcome_it_does_not_own(decision):
    service = _Service(_conversation())
    result = _call(service, {"decision": decision})

    assert result["status"] == 422
    assert service.decisions == []


def test_a_malformed_effect_reference_is_refused_before_any_lookup():
    service = _Service(_conversation())
    result = _call(
        service, {"decision": "approve"},
        path="/conversations/conversation%3Ac1/effects/..%2F..%2Fetc",
    )

    assert result["status"] == 400
    assert service.decisions == []


def test_a_conversation_belonging_to_someone_else_is_not_found():
    service = _Service(dict(_conversation(), conversation_id="conversation:other"))
    result = _call(service, {"decision": "approve"})

    assert result["status"] == 404
    assert service.decisions == []


def test_an_unknown_effect_reports_not_found_rather_than_a_silent_success():
    service = _Service(_conversation(), decide_error=KeyError("no such effect"))
    result = _call(service, {"decision": "approve"})

    assert result["status"] == 404
    assert service.dispatches == []
