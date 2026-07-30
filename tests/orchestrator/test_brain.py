"""Tests for the orchestrator brain (unit U21).

Covers both brain implementations behind the ``Brain`` protocol:

* ``RuleBrain`` -- deterministic offline keyword mapping: capability
  detection (shipping / marketplace / gig-board), destination extraction
  from "a/hacia/para <place>" phrases, courteous clarification on
  unrecognized requests, and templated reply composition.
* ``ClaudeBrain`` -- LLM-backed parsing via an *injected fake client*
  (tests never touch the network): ``messages.parse`` is called with
  model ``claude-opus-4-8`` and ``output_format=Intent``, and the
  validated ``parsed_output`` is returned as-is; ``compose_reply`` joins
  the text blocks of ``messages.create``.
* ``make_brain`` -- factory selection driven by ANTHROPIC_API_KEY
  presence, never crashing when the key is absent.
* ``Intent`` -- pydantic validation (``capability`` is required).
"""

import pytest
from pydantic import ValidationError

from agents.orchestrator.brain import (
    ClaudeBrain,
    GroqBrain,
    Intent,
    MODEL_ID,
    RuleBrain,
    make_brain,
)


# -- test doubles ----------------------------------------------------------


class _FakeParseResponse(object):
    def __init__(self, parsed_output):
        self.parsed_output = parsed_output


class _FakeBlock(object):
    def __init__(self, type, text=""):
        self.type = type
        self.text = text


class _FakeCreateResponse(object):
    def __init__(self, blocks):
        self.content = blocks


class _FakeMessages(object):
    """Records every call; returns canned parse/create responses."""

    def __init__(self, parse_response=None, create_response=None):
        self.parse_response = parse_response
        self.create_response = create_response
        self.parse_calls = []
        self.create_calls = []

    def parse(self, **kwargs):
        self.parse_calls.append(kwargs)
        return self.parse_response

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return self.create_response


class _FakeClient(object):
    def __init__(self, parse_response=None, create_response=None):
        self.messages = _FakeMessages(parse_response, create_response)


# -- Intent model ----------------------------------------------------------


def test_intent_requires_capability():
    with pytest.raises(ValidationError):
        Intent(params={}, missing_info=[], user_message="hola")


def test_intent_defaults_are_safe():
    intent = Intent(capability="shipping.package")
    assert intent.params == {}
    assert intent.constraints == {}
    assert intent.preferences == {}
    assert intent.missing_info == []
    assert intent.user_message == ""
    assert intent.can_search() is True


# -- RuleBrain.understand --------------------------------------------------


def test_rulebrain_parses_shipping_request_with_destination():
    intent = RuleBrain().understand(
        "necesito enviar un paquete a Santiago", context={}
    )
    assert intent.capability == "shipping.package"
    assert intent.params.get("destination") == "Santiago"
    assert intent.missing_info == []


def test_rulebrain_shipping_without_destination_asks_for_it():
    intent = RuleBrain().understand("quiero hacer un envío", context={})
    assert intent.capability == "shipping.package"
    assert "destination" not in intent.params
    assert intent.missing_info  # asks where to ship


@pytest.mark.parametrize("request_text, expected_destination", [
    ("enviar un paquete hacia Valparaiso", "Valparaiso"),
    ("un envío para Concepcion", "Concepcion"),
])
def test_rulebrain_destination_prepositions(request_text, expected_destination):
    intent = RuleBrain().understand(request_text, context={})
    assert intent.capability == "shipping.package"
    assert intent.params.get("destination") == expected_destination


def test_rulebrain_maps_task_keywords_to_marketplace():
    intent = RuleBrain().understand(
        "publicar una tarea en el marketplace", context={}
    )
    assert intent.capability == "marketplace.tasks"


def test_rulebrain_maps_gig_keyword_to_gig_board():
    intent = RuleBrain().understand("busco un gig de diseño", context={})
    assert intent.capability == "gig-board.gigs"


def test_rulebrain_unrecognized_request_asks_for_clarification():
    intent = RuleBrain().understand("xyzzy plugh", context={})
    assert intent.capability == ""
    assert intent.missing_info
    assert all(q.strip() for q in intent.missing_info)
    # No context is ever silently guessed into a wrong capability.
    assert intent.params == {}


def test_rulebrain_understand_accepts_missing_context():
    intent = RuleBrain().understand("enviar paquete a Santiago", context=None)
    assert intent.capability == "shipping.package"


def test_rulebrain_merges_follow_up_answer_from_conversation_memory():
    context = {
        "conversation": [
            {"role": "user", "text": "Necesito enviar un paquete"},
            {"role": "concierge", "text": "¿A qué destino desea enviarlo?"},
        ]
    }

    intent = RuleBrain().understand("Santo Domingo", context=context)

    assert intent.capability == "shipping.package"
    assert intent.params["destination"] == "Santo Domingo"
    assert intent.missing_info == []
    assert intent.ready_to_search is True
    assert intent.can_search() is True


def test_rulebrain_matches_new_capability_from_live_catalog():
    context = {
        "available_capabilities": [{
            "id": "terraform.generate",
            "name": "Terraform Infrastructure Generator",
            "description": "Generates deployable infrastructure as code.",
            "tags": ["terraform", "iac", "cloud"],
        }]
    }

    intent = RuleBrain().understand(
        "Necesito que alguien genere Terraform para mi aplicación",
        context=context,
    )

    assert intent.capability == "terraform.generate"
    assert intent.ready_to_search is True
    assert intent.confidence >= 0.9


def test_rulebrain_extracts_hard_budget_and_soft_priority():
    intent = RuleBrain().understand(
        "Quiero enviar un paquete a Santiago, máximo 25 y lo más rápido posible",
        context={},
    )

    assert intent.constraints["max_budget"] == "25"
    assert intent.preferences["priority"] == "fastest"


def test_rulebrain_latest_correction_wins_over_old_destination():
    context = {
        "conversation": [{
            "role": "user",
            "text": "Necesito enviar un paquete a Santiago",
        }]
    }

    intent = RuleBrain().understand(
        "Mejor envíalo a Puerto Plata",
        context=context,
    )

    assert intent.params["destination"] == "Puerto Plata"
    assert intent.conversation_act == "modify"
    assert intent.ready_to_search is True


def test_rulebrain_social_turn_never_replays_prior_request():
    context = {
        "conversation": [{
            "role": "user",
            "text": "Necesito enviar un paquete a Santiago",
        }]
    }

    intent = RuleBrain().understand("Muchas gracias", context=context)

    assert intent.conversation_act == "social"
    assert intent.ready_to_search is False
    assert intent.can_search() is False


def test_rulebrain_is_honest_about_other_conversation_memory():
    intent = RuleBrain().understand(
        "¿Te acuerdas de lo que hablamos en la otra conversación?",
        context={"conversation": []},
    )

    assert intent.conversation_act == "memory"
    assert intent.ready_to_search is False
    assert intent.missing_info == []
    assert "No puedo ver otras conversaciones" in RuleBrain().converse(
        "¿Te acuerdas de lo que hablamos en la otra conversación?",
        {"conversation": []},
    )


def test_rulebrain_recalls_latest_substantive_turn_in_current_chat():
    context = {
        "conversation": [
            {"role": "user", "text": "Necesito enviar un paquete a Santiago"},
            {"role": "concierge", "text": "Estoy buscando opciones."},
        ]
    }

    intent = RuleBrain().understand(
        "¿De qué estábamos hablando?",
        context=context,
    )

    assert intent.conversation_act == "memory"
    assert "enviar un paquete a Santiago" in RuleBrain().converse(
        "¿De qué estábamos hablando?",
        context,
    )
    assert intent.can_search() is False


def test_rulebrain_answers_assistant_question_without_requesting_details():
    intent = RuleBrain().understand("¿Qué puedes hacer?", context={})

    assert intent.conversation_act == "conversation"
    assert intent.missing_info == []
    assert "buscar agentes" in RuleBrain().converse(
        "¿Qué puedes hacer?",
        {},
    )
    assert intent.can_search() is False


# -- RuleBrain.compose_reply ----------------------------------------------


def test_rulebrain_compose_reply_success_mentions_outcome():
    reply = RuleBrain().compose_reply(
        {"status": "completed", "outcome": "paquete entregado en Santiago"}
    )
    assert reply
    assert "paquete entregado en Santiago" in reply


def test_rulebrain_compose_reply_handles_empty_state():
    reply = RuleBrain().compose_reply({})
    assert reply.strip()


def test_both_brains_expose_same_authority_free_slack_turn_contract():
    rule = RuleBrain().understand_slack(
        "What did María write in #canal-espanol?", {}
    )
    claude = ClaudeBrain(client=None).understand_slack(
        "What did María write in #canal-espanol?", {}
    )
    assert rule == claude
    assert rule.operation == "read"
    assert rule.locale == "en"
    assert rule.channel_name == "canal-espanol"
    assert not {"channel_id", "user_id", "connection_id"}.intersection(
        rule.model_dump()
    )


# -- make_brain factory ----------------------------------------------------


def test_make_brain_without_key_returns_rulebrain(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    brain = make_brain()
    assert isinstance(brain, RuleBrain)


def test_make_brain_with_key_returns_claudebrain(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    brain = make_brain()
    assert isinstance(brain, ClaudeBrain)  # construction only, no network


# -- ClaudeBrain (injected fake client — no network) -----------------------


def test_claudebrain_understand_returns_parsed_intent():
    expected = Intent(
        capability="shipping.package",
        params={"destination": "Santiago"},
        user_message="Con gusto le ayudo con su envío.",
    )
    fake = _FakeClient(parse_response=_FakeParseResponse(expected))
    brain = ClaudeBrain(client=fake)

    intent = brain.understand("necesito enviar un paquete a Santiago", {})

    assert intent is expected
    assert len(fake.messages.parse_calls) == 1
    call = fake.messages.parse_calls[0]
    assert call["model"] == "claude-opus-4-8"
    assert call["model"] == MODEL_ID
    assert call["output_format"] is Intent
    assert "temperature" not in call and "top_p" not in call
    # The natural-language request reaches the model as the user turn.
    assert call["messages"][-1]["role"] == "user"
    assert "Santiago" in call["messages"][-1]["content"]


def test_claudebrain_compose_reply_joins_text_blocks():
    fake = _FakeClient(create_response=_FakeCreateResponse([
        _FakeBlock("thinking"),
        _FakeBlock("text", "Su paquete fue "),
        _FakeBlock("text", "entregado con éxito."),
    ]))
    brain = ClaudeBrain(client=fake)

    reply = brain.compose_reply({"status": "completed"})

    assert reply == "Su paquete fue entregado con éxito."
    assert len(fake.messages.create_calls) == 1
    assert fake.messages.create_calls[0]["model"] == "claude-opus-4-8"


def test_groqbrain_uses_same_model_to_write_conversational_reply(monkeypatch):
    brain = GroqBrain(api_key="test-key")
    calls = []

    def fake_chat(system, user, json_mode=False):
        calls.append((system, user, json_mode))
        return "No veo el otro chat, pero sí puedo seguir este contigo."

    monkeypatch.setattr(brain, "_chat", fake_chat)
    context = {
        "conversation": [
            {"role": "user", "text": "¿Recuerdas nuestra conversación?"},
        ]
    }

    reply = brain.converse(
        "Me refiero a la conversación anterior",
        context,
    )

    assert reply == "No veo el otro chat, pero sí puedo seguir este contigo."
    assert len(calls) == 1
    assert "chat_history" in calls[0][1]
    assert "conversación anterior" in calls[0][1]


def test_claudebrain_construction_without_client_is_lazy():
    # No ANTHROPIC_API_KEY needed and no network hit just to construct.
    brain = ClaudeBrain(client=None)
    assert isinstance(brain, ClaudeBrain)
