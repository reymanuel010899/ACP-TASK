"""Bounded Slack evidence collection and one-shot grounded presentation."""

from datetime import datetime, timezone


class BoundedSlackRead:
    def __init__(self, max_pages=5, max_messages=100, max_thread_messages=50,
                 max_citations=10):
        self.max_pages = int(max_pages)
        self.max_messages = int(max_messages)
        self.max_thread_messages = int(max_thread_messages)
        self.max_citations = int(max_citations)

    def collect(self, fetch_page, channel_id, oldest, latest=None,
                user_id=None, thread_ts=None, permalink=None):
        cursor = None
        messages = []
        pages = 0
        provider_partial = False
        truncated = False
        limit = self.max_thread_messages if thread_ts else self.max_messages
        while pages < self.max_pages and len(messages) < limit:
            page = fetch_page({
                "channel_id": channel_id, "oldest": oldest, "latest": latest,
                "cursor": cursor, "limit": min(100, limit - len(messages)),
                **({"thread_ts": thread_ts} if thread_ts else {}),
            })
            pages += 1
            batch = page.get("messages") if isinstance(page, dict) else []
            for index, message in enumerate(batch or []):
                if not isinstance(message, dict):
                    continue
                if user_id and message.get("user") != user_id:
                    continue
                messages.append({
                    "channel_id": channel_id, "message_ts": message.get("ts"),
                    "author_id": message.get("user"), "text": message.get("text", ""),
                    "thread_ts": message.get("thread_ts"),
                    "relation": "parent" if thread_ts and message.get("ts") == thread_ts
                    else "reply" if thread_ts else "message",
                })
                if len(messages) >= limit:
                    truncated = any(
                        isinstance(rest, dict)
                        and (not user_id or rest.get("user") == user_id)
                        for rest in (batch or [])[index + 1:]
                    )
                    break
            cursor = page.get("next_cursor") if isinstance(page, dict) else None
            provider_partial = bool(page.get("partial")) if isinstance(page, dict) else False
            if not cursor:
                break
        budget_partial = bool(cursor) or pages >= self.max_pages and provider_partial
        citations = []
        if permalink:
            for message in messages[:self.max_citations]:
                if not message.get("message_ts"):
                    continue
                source = permalink(channel_id, message["message_ts"])
                citations.append({
                    "citation_id": "slack:%s:%s" % (channel_id, message["message_ts"]),
                    "channel_id": channel_id, "message_ts": message["message_ts"],
                    "permalink": source["permalink"],
                    "author_id": message.get("author_id"),
                })
        return {
            "messages": messages, "citations": citations,
            "period": {"oldest": oldest, "latest": latest},
            "partial": budget_partial or truncated,
            "partial_reason": (
                "thread_budget" if thread_ts and truncated
                else "message_or_page_budget" if budget_partial or truncated
                else None
            ),
        }


class GroundedResultPresenter:
    """Present only supplied evidence; it has no tool or planner surface."""

    def __init__(self, model=None):
        self.model = model

    def present(self, question, evidence, locale="es", author_labels=None):
        author_labels = dict(author_labels or {})
        messages = list(evidence.get("messages") or [])
        citations = list(evidence.get("citations") or [])
        if self.model is not None:
            answer = self.model.present_grounded({
                "question": question, "locale": locale,
                "period": evidence.get("period"),
                "partial": bool(evidence.get("partial")),
                "evidence": messages,
            })
            if not isinstance(answer, str):
                raise ValueError("result presenter must return text only")
        else:
            lines = []
            for message in messages:
                author = author_labels.get(message.get("author_id"), message.get("author_id") or "Slack")
                lines.append("%s (%s): %s" % (
                    author, _localized_timestamp(message.get("message_ts"), locale),
                    message.get("text", ""),
                ))
            answer = "\n".join(lines) if lines else (
                "No encontré mensajes en ese período."
                if locale == "es" else "I found no messages in that period."
            )
        return {
            "locale": locale, "answer": answer, "citations": citations,
            "partial": bool(evidence.get("partial")),
            "partial_reason": evidence.get("partial_reason"),
            "period": evidence.get("period"),
        }


def _localized_timestamp(value, locale):
    try:
        instant = datetime.fromtimestamp(float(value), timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return str(value or "unknown")
    return instant.strftime("%d/%m/%Y %H:%M UTC" if locale == "es" else "%Y-%m-%d %H:%M UTC")
