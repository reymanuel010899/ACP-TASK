"""Bounded, catalog-grounded decomposition for simple multi-step goals."""

import unicodedata


_CAPABILITY_MARKERS = {
    "calendar.create": (
        "calendar",
        "event",
        "meeting",
        "calendario",
        "evento",
        "reunión",
        "reunion",
    ),
    "gmail.send": (
        "email",
        "e-mail",
        "invitation",
        "invite",
        "correo",
        "invitación",
        "invitacion",
    ),
    "drive.upload": ("upload", "drive", "subir", "archivo", "file"),
    "shipping.package": (
        "package",
        "shipping",
        "shipment",
        "paquete",
        "envío",
        "envio",
    ),
}


def _plain_text(value):
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(
        char for char in normalized if not unicodedata.combining(char)
    ).lower()


def decompose_goal(goal, available_capabilities, max_subtasks=5):
    """Return a conservative ordered plan over capabilities in the catalog."""
    available = []
    for raw in available_capabilities or []:
        if isinstance(raw, str):
            capability = raw
        elif isinstance(raw, dict):
            capability = raw.get("id") or raw.get("capability_id")
        else:
            capability = None
        if (
            isinstance(capability, str)
            and capability
            and capability not in available
        ):
            available.append(capability)

    plain_goal = _plain_text(goal)
    requested = []
    positions = {}
    for capability, markers in _CAPABILITY_MARKERS.items():
        position = min(
            (
                plain_goal.find(_plain_text(marker))
                for marker in markers
                if _plain_text(marker) in plain_goal
            ),
            default=-1,
        )
        if position >= 0:
            requested.append(capability)
            positions[capability] = position
    requested.sort(key=lambda item: (positions[item], item))

    if not requested and len(available) == 1:
        requested = [available[0]]
    missing = [item for item in requested if item not in available]
    if missing:
        return {
            "status": "unsatisfiable",
            "missing_capabilities": missing,
            "message": "No hay una capacidad disponible para: %s."
            % ", ".join(missing),
        }
    if not requested:
        return {
            "status": "unsatisfiable",
            "missing_capabilities": [],
            "message": (
                "No pude vincular el objetivo con una capacidad disponible."
            ),
        }
    if len(requested) > int(max_subtasks):
        return {
            "status": "invalid",
            "message": "El objetivo excede el límite de subtareas.",
        }

    subtasks = []
    for index, capability in enumerate(requested):
        subtasks.append(
            {
                "id": "step-%d" % (index + 1),
                "capability": capability,
                "input": {},
                "depends_on": (
                    [] if index == 0 else ["step-%d" % index]
                ),
            }
        )
    return {"status": "ready", "subtasks": subtasks}
