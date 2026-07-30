"""Process supervisor for the runner (U3).

Spawns/kills the template process for a managed agent, tracks its runtime
(pid/port/url), and computes LIVE status from process liveness AND a health
check to the agent's ``url`` (KTD4). Mints the registry invite api-key on start
(KTD6). Local-dev only: binds children to localhost ports, captures their
stdout/stderr to the definition's ``log_path``.
"""

import contextlib
import json
import os
import signal
import socket
import subprocess
import threading
import time
import urllib.request

from runner.templates import build_command

_HEALTH_PATH = "/.well-known/agent-card.json"


def _free_localhost_port():
    # type: () -> int
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with contextlib.closing(sock):
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _extract_principal(card):
    # type: (dict) -> str
    """Pull principal_id out of the trust extension declared on the card."""
    if not isinstance(card, dict):
        return None
    caps = card.get("capabilities") or {}
    for ext in caps.get("extensions", []) or []:
        params = (ext or {}).get("params") or {}
        pid = params.get("principal_id")
        if isinstance(pid, str) and pid:
            return pid
    return None


class Supervisor(object):
    def __init__(self, registry_url, verification_url, http_timeout=3.0,
                 mint_key_fn=None):
        # type: (str, str, float, object) -> None
        self.registry_url = registry_url.rstrip("/")
        self._registry_url = self.registry_url
        self._verification_url = verification_url.rstrip("/")
        self._timeout = http_timeout
        self._lock = threading.RLock()
        # agent_id -> {proc, port, url, status, started_at, principal_id, error}
        self._procs = {}  # type: dict
        # Injectable so tests don't need a live registry.
        self._mint_key = mint_key_fn or self._mint_api_key

    # -- registry api-key (KTD6) ---------------------------------------------

    def _mint_api_key(self):
        # type: () -> str
        req = urllib.request.Request(
            self._registry_url + "/admin/api-keys", data=b"", method="POST"
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body["api_key"]

    def mint_api_key(self):
        # type: () -> str
        """Public: obtain a registry invite api-key (used by connect too)."""
        return self._mint_key()

    # -- lifecycle ------------------------------------------------------------

    def start(self, definition):
        # type: (dict) -> dict
        agent_id = definition["id"]
        with self._lock:
            existing = self._procs.get(agent_id)
            if existing and existing.get("proc") and existing["proc"].poll() is None:
                return self._runtime(agent_id)  # already running -> idempotent

            port = _free_localhost_port()
            api_key = self._mint_key()
            argv = build_command(
                definition, port, api_key,
                self._registry_url, self._verification_url,
            )
            os.makedirs(definition["keys_dir"], exist_ok=True)
            log_fh = open(definition["log_path"], "ab", buffering=0)
            try:
                proc = subprocess.Popen(
                    argv, stdout=log_fh, stderr=subprocess.STDOUT,
                )
            except Exception as exc:  # spawn failed
                log_fh.close()
                self._procs[agent_id] = {
                    "proc": None, "port": None, "url": None,
                    "status": "error", "error": str(exc),
                    "started_at": None, "principal_id": None,
                }
                return self._runtime(agent_id)

            self._procs[agent_id] = {
                "proc": proc, "log_fh": log_fh, "port": port,
                "url": "http://127.0.0.1:%d" % port,
                "status": "starting", "error": None,
                "started_at": time.time(), "principal_id": None,
            }
            return self._runtime(agent_id)

    def stop(self, agent_id):
        # type: (str) -> dict
        with self._lock:
            entry = self._procs.get(agent_id)
            if not entry or not entry.get("proc"):
                if entry:
                    entry["status"] = "stopped"
                return self._runtime(agent_id)
            proc = entry["proc"]
        # terminate outside the lock (waits can be slow)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        with self._lock:
            entry = self._procs.get(agent_id)
            if entry:
                fh = entry.get("log_fh")
                if fh:
                    with contextlib.suppress(Exception):
                        fh.close()
                entry.update({"proc": None, "log_fh": None, "port": None,
                              "url": None, "status": "stopped",
                              "principal_id": None})
            return self._runtime(agent_id)

    def restart(self, definition):
        # type: (dict) -> dict
        self.stop(definition["id"])
        return self.start(definition)

    # -- status / logs --------------------------------------------------------

    def _health(self, url):
        # type: (str) -> dict
        try:
            with urllib.request.urlopen(url + _HEALTH_PATH, timeout=self._timeout) as resp:
                if resp.status != 200:
                    return None
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def runtime(self, agent_id):
        # type: (str) -> dict
        """Compute LIVE status: process alive AND health-check ok -> online."""
        with self._lock:
            entry = self._procs.get(agent_id)
            if entry is None:
                return {"status": "stopped", "pid": None, "port": None,
                        "url": None, "principal_id": None, "error": None}
            proc = entry.get("proc")
            url = entry.get("url")
        if proc is None:
            return self._runtime(agent_id)
        if proc.poll() is not None:  # process died
            with self._lock:
                self._procs[agent_id]["status"] = "error"
                self._procs[agent_id]["error"] = "process exited"
            return self._runtime(agent_id)
        card = self._health(url) if url else None
        with self._lock:
            entry = self._procs.get(agent_id)
            if entry is not None:
                if card is not None:
                    entry["status"] = "online"
                    entry["principal_id"] = _extract_principal(card) or entry.get("principal_id")
                else:
                    entry["status"] = "starting"
            return self._runtime(agent_id)

    def _runtime(self, agent_id):
        # type: (str) -> dict
        entry = self._procs.get(agent_id) or {}
        proc = entry.get("proc")
        return {
            "status": entry.get("status", "stopped"),
            "pid": proc.pid if proc else None,
            "port": entry.get("port"),
            "url": entry.get("url"),
            "principal_id": entry.get("principal_id"),
            "error": entry.get("error"),
        }

    def logs(self, definition, tail=200):
        # type: (dict, int) -> list
        path = definition["log_path"]
        if not os.path.exists(path):
            return []
        with open(path, "r", errors="replace") as fh:
            lines = fh.readlines()
        return [ln.rstrip("\n") for ln in lines[-tail:]]

    def shutdown_all(self):
        # type: () -> None
        with self._lock:
            ids = list(self._procs.keys())
        for agent_id in ids:
            with contextlib.suppress(Exception):
                self.stop(agent_id)
