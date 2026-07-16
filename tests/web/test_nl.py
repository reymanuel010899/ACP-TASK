"""Tests for the natural-language -> task translator (unit W4).

Test-first: defines the contract for ``web.nl.parse_request`` before it exists.
The parser turns free text a person types ("necesito infra para una app web
con 3 contenedores") into a structured task for the terraform.generate
capability, plus a human-readable interpretation the UI shows back. It is
rule-based (no LLM dependency) but has a clean seam so an LLM backend can
replace it later.

Contract: ``parse_request(text) -> (task_input_or_None, message)``.
- On success: ``task_input`` is a dict, ``message`` is the interpretation.
- On failure: ``task_input`` is None, ``message`` is a helpful reason.
"""

import pytest

from web.nl import parse_request


@pytest.mark.parametrize(
    "text,expected_containers",
    [
        ("necesito infra para una app web con 3 contenedores", 3),
        ("desplegar 5 contenedores detrás de un balanceador", 5),
        ("quiero infraestructura terraform", 2),  # no number -> default 2
        ("un contenedor para mi servicio web", 1),  # spelled-out
        ("dos servicios en aws", 2),
        ("necesito deployar diez contenedores", 10),
    ],
)
def test_parses_container_count(text, expected_containers):
    task_input, message = parse_request(text)
    assert task_input is not None, message
    assert task_input["containers"] == expected_containers
    assert task_input["load_balancer"] == "alb"
    assert isinstance(message, str) and message


def test_clamps_absurd_counts():
    task_input, _ = parse_request("desplegar 9999 contenedores")
    assert task_input is not None
    assert task_input["containers"] <= 10  # clamped to a sane demo range


def test_non_infra_request_is_declined_with_a_reason():
    # The only capability today is terraform.generate; unrelated requests get a
    # clear explanation, not a wrong task.
    task_input, message = parse_request("editame este video para instagram")
    assert task_input is None
    assert "terraform" in message.lower() or "infra" in message.lower()


def test_empty_text_is_declined():
    task_input, message = parse_request("   ")
    assert task_input is None
    assert message


def test_interpretation_mentions_what_it_understood():
    _, message = parse_request("infra con 4 contenedores")
    assert "4" in message
    assert "alb" in message.lower() or "balanceador" in message.lower()
