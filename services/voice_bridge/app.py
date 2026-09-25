"""Twilio Media Streams ↔ Grok bridge with a closed local tool surface."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time

import requests

from libs.grok_realtime import GrokRealtimeClient, GrokRealtimeProtocol


PUBLIC_VOICE_CAPABILITIES = frozenset({"public.lookup", "transfer.request", "suppression.create"})


class VoiceBridgeTicketCodec:
    def __init__(self, secret, clock=None):
        if not secret:
            raise ValueError("voice bridge ticket secret is required")
        self.secret = secret.encode("utf-8")
        self.clock = clock or time.time

    def encode(self, claims):
        raw = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self.secret, raw, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=") + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")

    def decode(self, token):
        try:
            body, supplied = token.split(".", 1)
            raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
            signature = base64.urlsafe_b64decode(supplied + "=" * (-len(supplied) % 4))
            expected = hmac.new(self.secret, raw, hashlib.sha256).digest()
            claims = json.loads(raw)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PermissionError("voice bridge ticket is invalid") from exc
        if not hmac.compare_digest(signature, expected) or int(claims.get("expires_at", 0)) <= int(self.clock()):
            raise PermissionError("voice bridge ticket is invalid or expired")
        return claims


class HTTPVoiceToolExecutor:
    def __init__(self, endpoint, token, timeout=5):
        self.endpoint, self.token, self.timeout = endpoint, token, timeout

    def __call__(self, name, arguments):
        response = requests.post(self.endpoint, json={"capability_id": name, "input": arguments},
                                 headers={"Authorization": "Bearer " + self.token}, timeout=self.timeout)
        response.raise_for_status()
        return response.json()


class VoiceSessionStore:
    def __init__(self, database_path):
        self.connection = sqlite3.connect(str(database_path), check_same_thread=False)
        self.lock = threading.RLock()
        self.connection.execute("""CREATE TABLE IF NOT EXISTS voice_transcript (
            tenant_id TEXT NOT NULL, call_sid TEXT NOT NULL, sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            speaker TEXT NOT NULL, content TEXT NOT NULL, expires_at INTEGER NOT NULL
        )""")

    def append(self, tenant_id, call_sid, speaker, content, now=None, ttl_seconds=86400):
        now = int(time.time() if now is None else now)
        with self.lock:
            self.connection.execute(
                "INSERT INTO voice_transcript(tenant_id,call_sid,speaker,content,expires_at) VALUES(?,?,?,?,?)",
                (tenant_id, call_sid, speaker, content, now + ttl_seconds),
            )
            self.connection.commit()

    def transcript(self, tenant_id, call_sid, now=None):
        now = int(time.time() if now is None else now)
        rows = self.connection.execute(
            "SELECT speaker,content FROM voice_transcript WHERE tenant_id=? AND call_sid=? AND expires_at>? ORDER BY sequence",
            (tenant_id, call_sid, now),
        ).fetchall()
        return [{"speaker": row[0], "content": row[1]} for row in rows]

    def purge_expired(self, now=None):
        now = int(time.time() if now is None else now)
        with self.lock:
            cursor = self.connection.execute("DELETE FROM voice_transcript WHERE expires_at<=?", (now,))
            self.connection.commit()
            return cursor.rowcount


class VoiceBridgeSession:
    def __init__(self, tenant_id, call_sid, stream_sid, grok, capability_projection,
                 tool_executor=None, maximum_duration_seconds=300, now=None):
        projection = frozenset(capability_projection)
        if any(item.startswith("contacts.") for item in projection):
            raise PermissionError("voice sessions cannot receive contact capabilities")
        if not projection.issubset(PUBLIC_VOICE_CAPABILITIES):
            raise PermissionError("voice capability projection is not trusted")
        self.tenant_id, self.call_sid, self.stream_sid = tenant_id, call_sid, stream_sid
        self.grok, self.capability_projection = grok, projection
        self.tool_executor = tool_executor or (lambda _name, _args: {"accepted": False})
        self.maximum_duration_seconds = maximum_duration_seconds
        self.started_at = time.monotonic() if now is None else now
        self.disclosure_complete = False
        self.closed = False

    def receive_twilio(self, event):
        kind = event.get("event")
        if kind == "media":
            payload = (event.get("media") or {}).get("payload")
            if payload:
                return self.grok.append_audio(payload)
        if kind == "stop":
            self.closed = True
        return None

    def twilio_audio(self, payload):
        return {"event": "media", "streamSid": self.stream_sid, "media": {"payload": payload}}

    def execute_tool(self, name, arguments):
        if name not in self.capability_projection:
            raise PermissionError("tool is outside the voice session projection")
        return self.tool_executor(name, arguments)

    def mark_disclosed(self):
        self.disclosure_complete = True

    def expired(self, now=None):
        now = time.monotonic() if now is None else now
        return now - self.started_at >= self.maximum_duration_seconds


async def _serve(host, port, api_key, ticket_secret, tool_endpoint, tool_token, transcript_database):
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError("install requirements.txt to run the voice bridge") from exc

    codec = VoiceBridgeTicketCodec(ticket_secret)
    transcript_store = VoiceSessionStore(transcript_database)

    async def handler(socket):
        first = json.loads(await asyncio.wait_for(socket.recv(), timeout=10))
        if first.get("event") == "connected":
            first = json.loads(await asyncio.wait_for(socket.recv(), timeout=10))
        if first.get("event") != "start":
            await socket.close(code=1008, reason="start event required"); return
        start = first.get("start") or {}
        token = (start.get("customParameters") or {}).get("Ticket")
        claims = codec.decode(token)
        if claims.get("call_sid") != start.get("callSid"):
            await socket.close(code=1008, reason="call binding mismatch"); return
        protocol = GrokRealtimeProtocol(claims["model"], claims["voice"], claims.get("conversation_id"))
        projection = frozenset(claims.get("capabilities") or ())
        executor = HTTPVoiceToolExecutor(tool_endpoint, tool_token)
        async with websockets.connect(protocol.url(), additional_headers={"Authorization": "Bearer " + api_key}) as grok_socket:
            grok = GrokRealtimeClient(grok_socket, protocol)
            tools = [{"type": "function", "name": name, "parameters": {"type": "object", "additionalProperties": True}} for name in sorted(projection)]
            await grok.configure(claims["instructions"], tools)
            session = VoiceBridgeSession(claims["tenant_id"], start["callSid"], start["streamSid"], grok,
                                         projection, executor, int(claims["maximum_duration_seconds"]))

            async def from_twilio():
                async for raw in socket:
                    event = json.loads(raw)
                    if event.get("event") == "media":
                        await grok.append_audio(event["media"]["payload"])
                    elif event.get("event") == "stop":
                        return

            async def from_grok():
                async for event in grok.events():
                    kind = event.get("type")
                    if kind in {"response.output_audio.delta", "response.audio.delta"} and event.get("delta"):
                        await socket.send(json.dumps(session.twilio_audio(event["delta"])))
                    elif kind == "conversation.item.input_audio_transcription.updated" and event.get("transcript"):
                        transcript_store.append(session.tenant_id, session.call_sid, "caller", event["transcript"])
                    elif kind == "response.function_call_arguments.done":
                        arguments = json.loads(event.get("arguments") or "{}")
                        result = await asyncio.to_thread(session.execute_tool, event["name"], arguments)
                        await grok_socket.send(json.dumps(protocol.tool_output(event["call_id"], result)))
                        await grok_socket.send(json.dumps({"type": "response.create"}))

            tasks = [asyncio.create_task(from_twilio()), asyncio.create_task(from_grok())]
            done, pending = await asyncio.wait(tasks, timeout=session.maximum_duration_seconds,
                                               return_when=asyncio.FIRST_COMPLETED)
            for task in pending: task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    async with websockets.serve(handler, host, port, ping_interval=20, ping_timeout=20):
        await asyncio.Future()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8150)
    args = parser.parse_args()
    if not os.environ.get("XAI_API_KEY"):
        raise RuntimeError("XAI_API_KEY is required")
    required = ("VOICE_BRIDGE_TICKET_SECRET", "VOICE_TOOL_ENDPOINT", "VOICE_TOOL_TOKEN")
    if any(not os.environ.get(name) for name in required):
        raise RuntimeError("voice bridge ticket and tool configuration are required")
    asyncio.run(_serve(args.host, args.port, os.environ["XAI_API_KEY"],
                       os.environ["VOICE_BRIDGE_TICKET_SECRET"], os.environ["VOICE_TOOL_ENDPOINT"],
                       os.environ["VOICE_TOOL_TOKEN"], os.environ.get("VOICE_TRANSCRIPT_DATABASE", "tessera-voice.db")))


if __name__ == "__main__":
    main()
