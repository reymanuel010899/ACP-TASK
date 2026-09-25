"""Vendor boundary for the xAI realtime voice WebSocket protocol."""

from __future__ import annotations

import json
import re
from urllib.parse import quote


_PINNED = re.compile(r"^grok-voice-[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class GrokRealtimeProtocol:
    def __init__(self, model, voice, conversation_id=None):
        if not _PINNED.match(model or ""):
            raise ValueError("Grok realtime model must be pinned")
        if not voice:
            raise ValueError("a voice is required")
        self.model = model
        self.voice = voice
        self.conversation_id = conversation_id

    def url(self):
        value = "wss://api.x.ai/v1/realtime?model=" + quote(self.model)
        if self.conversation_id:
            value += "&conversation_id=" + quote(self.conversation_id)
        return value

    def session_update(self, instructions, tools):
        return {"type": "session.update", "session": {
            "voice": self.voice, "instructions": instructions,
            "turn_detection": {"type": "server_vad"},
            "audio": {
                "input": {"format": {"type": "audio/pcmu"}, "transcription": {"model": "grok-transcribe"}},
                "output": {"format": {"type": "audio/pcmu"}},
            },
            "tools": list(tools), "resumption": {"enabled": True},
        }}

    @staticmethod
    def input_audio(payload):
        return {"type": "input_audio_buffer.append", "audio": payload}

    @staticmethod
    def tool_output(call_id, result):
        return {"type": "conversation.item.create", "item": {
            "type": "function_call_output", "call_id": call_id,
            "output": json.dumps(result, separators=(",", ":"), ensure_ascii=False),
        }}


class GrokRealtimeClient:
    """Small async adapter; transport is injected to keep vendor I/O testable."""

    def __init__(self, websocket, protocol):
        self.websocket = websocket
        self.protocol = protocol

    async def configure(self, instructions, tools):
        await self.websocket.send(json.dumps(self.protocol.session_update(instructions, tools)))

    async def append_audio(self, payload):
        await self.websocket.send(json.dumps(self.protocol.input_audio(payload)))

    async def events(self):
        async for raw in self.websocket:
            yield json.loads(raw)

