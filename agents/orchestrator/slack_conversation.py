"""Typed, deterministic intake and entity grounding for Slack turns."""

import re
import unicodedata
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


_OPERATION_ID_TO_TURN = {
    "slack.connection.status": "status",
    "slack.channels.list": "list_channels",
    "slack.private_channels.list": "list_private_channels",
    "slack.conversation.read": "read",
    "slack.conversation.summarize": "summarize",
    "slack.thread.read": "read",
    "slack.private_conversation.read": "read",
    "slack.private_thread.read": "read",
    "slack.message.permalink": "read",
    "slack.message.send": "post",
    "slack.thread.reply": "reply",
    "slack.direct_message.send": "dm",
    "slack.reaction.add": "reaction",
}


class SlackTurn(BaseModel):
    operation: str
    locale: str
    channel_name: Optional[str] = None
    person_name: Optional[str] = None
    message_text: Optional[str] = None
    refers_to_active_target: bool = False
    period_days: Optional[int] = None


class SlackTurnResult(BaseModel):
    state: str
    turn: SlackTurn
    resolved: Dict[str, Any] = Field(default_factory=dict)
    need: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


def normalize_name(value):
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(
        char for char in normalized if not unicodedata.combining(char)
    ).lower().lstrip("#@").split())


def interpret_slack_turn(text, active_state=None):
    """Parse the deliberately supported offline Slack language subset."""
    text = str(text or "").strip()
    plain = normalize_name(text)
    locale = "es" if any(word in plain.split() for word in (
        "que", "dijo", "manda", "mandale", "mensaje", "canal", "responde",
        "respondele", "ahi", "cancelar", "cancela", "tengo", "canales",
        "publicos", "lista", "muestra",
        "acceso", "tienes", "conectado", "conectada",
    )) else "en"
    words = set(plain.split())
    channel_words = {"canal", "canales", "channel", "channels"}
    listing_words = {
        "lista", "listar", "muestra", "tengo", "tenemos", "cuanto", "cuantos",
        "saber", "list", "show", "have", "many",
    }
    asks_for_channels = bool(words & channel_words) and bool(words & listing_words)
    public_channels = asks_for_channels and bool(words & {"publico", "publicos", "public"})
    private_channels = asks_for_channels and bool(words & {"privado", "privados", "private"})
    asks_connection_status = "slack" in plain and any(
        marker in plain for marker in (
            "acceso a slack", "access to slack", "tienes acceso",
            "have access", "slack conectado", "slack connected",
        )
    )
    if asks_connection_status:
        operation = "status"
    elif any(marker in plain for marker in ("cancel", "cancela", "olvida eso")):
        operation = "cancel"
    elif private_channels:
        operation = "list_private_channels"
    elif public_channels:
        operation = "list_channels"
    elif any(marker in plain for marker in (
        "direct message", " dm ", "send a message to", "mandale", "manda a",
    )):
        operation = "dm"
    elif any(marker in plain for marker in (
        "reply", "respond", "responde", "contesta",
    )):
        operation = "reply"
    elif any(marker in plain for marker in (
        "send", "post", "manda", "publica", "escribe", "enviar", "envia",
    )):
        operation = "post"
    elif any(marker in plain for marker in ("summar", "resume", "resumen")):
        operation = "summarize"
    elif any(marker in plain for marker in (
        "what did", "what has", "que dijo", "que escribio", "read", "lee",
    )):
        operation = "read"
    else:
        operation = "clarify" if active_state else "unsupported"

    channel = None
    match = re.search(r"#([\wÀ-ÿ.-]+)", text, re.UNICODE)
    if match:
        channel = match.group(1).rstrip(".")
    else:
        match = re.search(
            r"(?:canal|channel)\s+#?([\wÀ-ÿ.-]+)", text,
            re.IGNORECASE | re.UNICODE,
        )
        if match:
            channel = match.group(1).rstrip(".")

    person = None
    patterns = (
        r"(?:qué dijo|que dijo|qué escribió|que escribio)\s+([\wÀ-ÿ'. -]+?)(?:\s+en\s+#|$)",
        r"(?:what did)\s+([\wÀ-ÿ'. -]+?)\s+(?:write|say)(?:\s+in\s+#|$)",
        r"(?:send (?:a )?(?:direct )?message to|message)\s+@?([\wÀ-ÿ'. -]+?)(?:\s+(?:that|saying)\s+|$)",
        r"(?:m[áa]ndale(?:\s+a)?|manda a)\s+@?([\wÀ-ÿ'. -]+?)(?:\s+que\s+|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.UNICODE)
        if match:
            person = match.group(1).strip(" ,.")
            break

    message = None
    if operation in ("post", "reply", "dm"):
        message_patterns = (
            r"(?:mensaje\s+)?(?:que\s+)?diga\s+[\"“]([^\"”]+)[\"”]",
            r"[\"“]([^\"”]+)[\"”]",
            r"(?:\bque\b|\bdiciendo\b)\s+(.+)$",
            r"(?:\bthat\b|\bsaying\b)\s+(.+)$",
            r"(?:#[\wÀ-ÿ.-]+)\s*:\s*(.+)$",
        )
        for pattern in message_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.UNICODE)
            if match:
                candidate = match.group(1).strip()
                if candidate:
                    message = candidate
                    break

    active_markers = ("ahi", "there", "le", "him", "her", "respondele", "reply")
    refers = any(marker in plain.split() for marker in active_markers)
    return SlackTurn(
        operation=operation, locale=locale, channel_name=channel,
        person_name=person, message_text=message,
        refers_to_active_target=refers,
        period_days=7 if operation in ("read", "summarize") else None,
    )


class SlackConversationCoordinator:
    """Ground human references only against server-authorized projections."""

    def coordinate(
        self, text, active_state=None, installations=None, channels=None,
        users=None, interpretation=None,
    ):
        active = dict(active_state or {})
        turn = (
            self._turn_from_interpretation(interpretation, active)
            if interpretation is not None else interpret_slack_turn(text, active)
        )
        resolved = {
            key: active[key] for key in (
                "active_connection", "active_channel", "active_person",
                "active_thread", "active_message", "active_file",
                "active_reaction", "read_period", "pending_draft",
            ) if active.get(key) is not None
        }
        if turn.message_text is None:
            pending = resolved.get("pending_draft") or {}
            if isinstance(pending.get("text"), str) and pending["text"]:
                turn = turn.model_copy(update={"message_text": pending["text"]})
        if turn.operation == "status":
            usable = [
                item for item in (installations or [])
                if item.get("status") == "connected"
            ]
            if not usable:
                message = (
                    "No. Slack no está conectado."
                    if turn.locale == "es"
                    else "No. Slack is not connected."
                )
            else:
                labels = [
                    item.get("team_name") or item.get("team_id")
                    for item in usable
                    if item.get("team_name") or item.get("team_id")
                ]
                workspace = ", ".join(labels)
                if turn.locale == "es":
                    message = (
                        "Sí. Tengo acceso a Slack"
                        + (" mediante el workspace %s." % workspace if workspace else ".")
                    )
                else:
                    message = (
                        "Yes. I have access to Slack"
                        + (" through the %s workspace." % workspace if workspace else ".")
                    )
            return SlackTurnResult(
                state="completed", turn=turn, resolved={}, message=message
            )
        blocking_need = active.get("blocking_need")
        if isinstance(blocking_need, dict):
            turn, answered = self._answer_blocking_need(
                text, turn, active, blocking_need
            )
            resolved.update(answered)
        if turn.operation == "unsupported":
            return self._need(turn, resolved, "operation")
        if turn.operation == "cancel":
            return SlackTurnResult(state="cancelled", turn=turn, resolved={})

        usable = [item for item in (installations or []) if item.get("status") == "connected"]
        active_connection = resolved.get("active_connection")
        if active_connection and not any(
            item.get("connection_id") == active_connection.get("id") for item in usable
        ):
            resolved.pop("active_connection", None)
            active_connection = None
        if active_connection is None:
            if len(usable) != 1:
                return self._need(turn, resolved, "workspace", usable)
            selected = usable[0]
            resolved["active_connection"] = {
                "id": selected["connection_id"],
                "label": selected.get("team_name") or selected.get("team_id"),
            }

        if turn.channel_name:
            matches = [item for item in (channels or []) if (
                normalize_name(item.get("name")) == normalize_name(turn.channel_name)
                and item.get("is_archived") is not True
                and item.get("is_private") is not True
                and item.get("is_ext_shared") is not True
            )]
            if len(matches) != 1:
                return self._need(turn, resolved, "channel", matches)
            resolved["active_channel"] = {
                "id": matches[0]["id"], "name": matches[0]["name"]
            }

        if turn.person_name:
            wanted = normalize_name(turn.person_name)
            matches = [item for item in (users or []) if wanted in {
                normalize_name(item.get("display_name")),
                normalize_name(item.get("real_name")),
                normalize_name(item.get("handle")),
            }]
            if len(matches) != 1:
                return self._need(turn, resolved, "person", matches)
            selected = matches[0]
            resolved["active_person"] = {
                key: selected[key] for key in (
                    "id", "display_name", "real_name", "handle", "image_url"
                ) if selected.get(key) is not None
            }

        if turn.operation in ("read", "summarize") and "active_channel" not in resolved:
            return self._need(turn, resolved, "channel")
        if turn.operation == "post" and "active_channel" not in resolved:
            return self._need(turn, resolved, "channel")
        if turn.operation == "dm" and "active_person" not in resolved:
            return self._need(turn, resolved, "person")
        if turn.operation == "reply" and "active_thread" not in resolved:
            return self._need(turn, resolved, "thread")
        if turn.operation in ("post", "reply", "dm") and not turn.message_text:
            return self._need(turn, resolved, "message_text")
        if turn.period_days and "read_period" not in resolved:
            resolved["read_period"] = {"days": turn.period_days, "defaulted": True}
        if turn.message_text:
            resolved["message_text"] = turn.message_text
        return SlackTurnResult(state="resolving", turn=turn, resolved=resolved)

    @staticmethod
    def _turn_from_interpretation(interpretation, active):
        operations = list(getattr(interpretation, "operations", ()) or ())
        operation_id = operations[0].operation_id if operations else None
        operation = _OPERATION_ID_TO_TURN.get(operation_id)
        if operation is None:
            operation = active.get("operation") or "unsupported"
        values = {}
        for slot in getattr(interpretation, "slots", ()) or ():
            if getattr(slot, "operation_index", None) in (None, 0):
                values[slot.name] = slot.value
        for correction in getattr(interpretation, "corrections", ()) or ():
            if getattr(correction, "operation_index", None) in (None, 0):
                values[correction.slot] = correction.replacement
        locale = getattr(interpretation, "locale", None) or active.get("locale") or "en"
        if locale == "mixed":
            locale = active.get("locale") if active.get("locale") in ("es", "en") else "es"
        period = values.get("period")
        period_days = None
        if isinstance(period, int):
            period_days = period
        elif isinstance(period, str):
            match = re.search(r"(\d+)", period)
            period_days = int(match.group(1)) if match else None
        return SlackTurn(
            operation=operation,
            locale=locale,
            channel_name=str(values["channel"]) if values.get("channel") else None,
            person_name=str(values["person"]) if values.get("person") else None,
            message_text=str(values["message"]) if values.get("message") else None,
            refers_to_active_target=bool(active),
            period_days=period_days,
        )

    @staticmethod
    def _answer_blocking_need(text, parsed_turn, active, need):
        field = need.get("field")
        operation = active.get("operation") or parsed_turn.operation
        locale = active.get("locale") or parsed_turn.locale
        options = list(need.get("options") or [])
        value = str(text or "").strip()
        answered = {}
        if field == "message_text":
            if isinstance(parsed_turn.message_text, str) and parsed_turn.message_text.strip():
                value = parsed_turn.message_text.strip()
            if not value:
                return parsed_turn, answered
            return SlackTurn(
                operation=operation, locale=locale, message_text=value,
                refers_to_active_target=True,
            ), answered
        if field == "operation" and parsed_turn.operation not in {
            "unsupported", "clarify"
        }:
            return parsed_turn, answered
        if field in {"workspace", "channel", "person"} and options:
            normalized = normalize_name(value.replace("·", " "))
            strong_matches = []
            matches = []
            for option in options:
                if any(normalize_name(option.get(key)) in normalized
                       for key in ("connection_id", "team_id", "id", "handle")
                       if normalize_name(option.get(key))):
                    strong_matches.append(option)
                labels = [option.get(key) for key in (
                    "connection_id", "team_name", "team_id", "id", "name",
                    "display_name", "real_name", "handle",
                )]
                if any(normalize_name(label) and normalize_name(label) in normalized
                       for label in labels):
                    matches.append(option)
            if len(strong_matches) == 1:
                matches = strong_matches
            if len(matches) != 1:
                return parsed_turn, answered
            selected = matches[0]
            if field == "workspace":
                answered["active_connection"] = {
                    "id": selected["connection_id"],
                    "label": selected.get("team_name") or selected.get("team_id"),
                }
            elif field == "channel":
                answered["active_channel"] = {
                    "id": selected["id"], "name": selected["name"],
                }
            else:
                answered["active_person"] = {
                    key: selected[key] for key in (
                        "id", "display_name", "real_name", "handle", "image_url"
                    ) if selected.get(key) is not None
                }
            return SlackTurn(
                operation=operation, locale=locale,
                refers_to_active_target=True,
            ), answered
        return parsed_turn, answered

    @staticmethod
    def _need(turn, resolved, field, candidates=None):
        questions = {
            "es": {
                "operation": "¿Qué quieres hacer en Slack?",
                "workspace": "¿Qué espacio de trabajo de Slack quieres usar?",
                "channel": "¿En qué canal público de Slack?",
                "person": "¿Qué persona de Slack?",
                "thread": "¿En qué hilo quieres responder?",
                "message_text": "¿Qué mensaje quieres enviar?",
            },
            "en": {
                "operation": "What would you like to do in Slack?",
                "workspace": "Which Slack workspace should I use?",
                "channel": "Which public Slack channel?",
                "person": "Which Slack person?",
                "thread": "Which thread should I reply to?",
                "message_text": "What message would you like to send?",
            },
        }
        options = []
        for item in candidates or []:
            options.append({key: item[key] for key in (
                "connection_id", "team_name", "team_id", "id", "name",
                "display_name", "real_name", "handle", "image_url",
            ) if item.get(key) is not None})
        return SlackTurnResult(
            state="needs_input", turn=turn, resolved=resolved,
            need={"kind": "selection" if options else "missing", "field": field,
                  "question": questions[turn.locale][field], "options": options},
        )
