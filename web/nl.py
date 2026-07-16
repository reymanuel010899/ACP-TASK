"""Natural-language -> task translator (unit W4).

Turns free text a person types into a structured task for the
``terraform.generate`` capability, plus a human-readable interpretation the UI
echoes back so the user sees what their agent understood.

This is deliberately a **rule-based** parser: no LLM, no API key, no new
dependency — it recognises the one capability the demo can verify and extracts
a container count. The public seam is a single function, so a real
LLM-backed intent parser can replace it later without touching callers.

Contract: ``parse_request(text) -> (task_input_or_None, message)``.
- success: ``(dict, interpretation_str)``
- decline: ``(None, reason_str)``
"""

import re

from typing import Optional, Tuple

MAX_CONTAINERS = 10

# Words that signal an infrastructure / terraform request (the one capability
# the demo can independently verify today).
_INFRA_WORDS = (
    "infra",
    "infraestructura",
    "terraform",
    "contenedor",
    "container",
    "desplegar",
    "despliegue",
    "deploy",
    "deployar",
    "servidor",
    "servicio",
    "balanceador",
    "alb",
    "aws",
    "nube",
    "cloud",
    "app",
    "aplicacion",
    "aplicación",
    "web",
)

_SPELLED = {
    "un": 1,
    "una": 1,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
}

_DECLINE = (
    "Por ahora tu agente solo sabe generar infraestructura Terraform "
    "(contenedores detrás de un balanceador). Probá con algo como: "
    '"necesito infra para una app web con 3 contenedores".'
)


def _extract_count(text):
    # type: (str) -> Optional[int]
    """First explicit count in the text: a digit run, else a spelled number."""
    digits = re.search(r"\d+", text)
    if digits:
        return int(digits.group())
    for word in re.findall(r"[a-záéíóú]+", text):
        if word in _SPELLED:
            return _SPELLED[word]
    return None


def parse_request(text):
    # type: (str) -> Tuple[Optional[dict], str]
    """Map free text to a terraform.generate task, or decline with a reason."""
    if not text or not text.strip():
        return None, "Escribí qué necesitás."

    lowered = text.lower()
    if not any(word in lowered for word in _INFRA_WORDS):
        return None, _DECLINE

    count = _extract_count(lowered)
    if count is None:
        count = 2  # sensible default when no number was given
    count = max(1, min(count, MAX_CONTAINERS))

    task_input = {"containers": count, "load_balancer": "alb"}
    plural = "contenedor" if count == 1 else "contenedores"
    interpretation = (
        "generar Terraform · %d %s · detrás de un ALB (AWS)" % (count, plural)
    )
    return task_input, interpretation
