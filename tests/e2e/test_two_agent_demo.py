"""End-to-end two-agent demo (unit U7) — the real success criterion (R6).

Unlike the per-unit tests, which run collaborators in-process, this test
launches the registry, the verification service, and both agents as
*separate OS processes* via ``python -m ...``. Nothing is shared between the
requester and provider implementations beyond the published spec and schemas
— the whole point of R6. The requester itself is driven as a subprocess and
its JSON outcome is read from stdout, exactly as an operator would run it.

Scenarios (from the plan):

- Happy path: the full discover -> negotiate -> execute -> verify cycle
  completes with a ``verified`` outcome, and the provider's Reputation Record
  is updated and visible in the registry afterwards.
- Failure smoke: with the provider gone, the requester surfaces a clean
  ``provider_error`` in bounded time instead of hanging forever (the RUNNING
  liveness gap noted during ideation — a minimal timeout, not full
  heartbeat design).
"""

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
CAPABILITY_ID = "terraform.generate"

READY_TIMEOUT = 20.0


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def launch(module, *args):
    """Start ``python -m <module> <args>`` as a separate process at repo root."""
    return subprocess.Popen(
        [sys.executable, "-m", module, *args],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def wait_http(url, timeout=READY_TIMEOUT):
    """Poll ``url`` until it answers 200, or fail after ``timeout`` seconds."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=1.0)
            if resp.status_code == 200:
                return
            last = "status %d" % resp.status_code
        except requests.RequestException as exc:
            last = str(exc)
        time.sleep(0.1)
    raise AssertionError("%s never became ready (last: %s)" % (url, last))


def wait_searchable(registry_url, capability, timeout=READY_TIMEOUT):
    """Wait until the provider has registered and shows up in /search."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(
            registry_url + "/search", params={"capability": capability},
            timeout=1.0,
        )
        if resp.status_code == 200 and resp.json().get("candidates"):
            return
        time.sleep(0.1)
    raise AssertionError("provider never became searchable in the registry")


class Demo(object):
    """The four-process demo topology; started on demand, torn down in full."""

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.procs = []
        self.verification_url = None
        self.registry_url = None
        self.provider = None
        self.provider_url = None
        self.api_key = None

    def _track(self, proc):
        self.procs.append(proc)
        return proc

    def start_backends(self):
        vport, rport = free_port(), free_port()
        self.verification_url = "http://127.0.0.1:%d" % vport
        self.registry_url = "http://127.0.0.1:%d" % rport

        self._track(launch("services.verification.app", "--port", str(vport)))
        self._track(
            launch(
                "registry.app",
                "--port", str(rport),
                "--verification-url", self.verification_url,
            )
        )
        wait_http(self.verification_url + "/healthz")
        wait_http(self.registry_url + "/healthz")

        self.api_key = requests.post(
            self.registry_url + "/admin/api-keys", timeout=5
        ).json()["api_key"]

    def start_provider(self):
        pport = free_port()
        self.provider_url = "http://127.0.0.1:%d" % pport
        self.provider = self._track(
            launch(
                "agents.provider.agent",
                "--port", str(pport),
                "--verification-url", self.verification_url,
                "--registry-url", self.registry_url,
                "--api-key", self.api_key,
                "--keys-dir", str(self.tmp_path / "provider-keys"),
            )
        )
        wait_http(self.provider_url + "/healthz")
        wait_searchable(self.registry_url, CAPABILITY_ID)

    def run_requester(self, *extra, timeout=30):
        """Run the requester CLI as a subprocess; return its parsed outcome."""
        proc = subprocess.run(
            [
                sys.executable, "-m", "agents.requester.agent",
                "--registry-url", self.registry_url, *extra,
            ],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        assert proc.stdout, proc.stderr.decode("utf-8", "replace")
        return json.loads(proc.stdout.decode("utf-8")), proc.returncode

    def stop_provider(self):
        if self.provider is not None:
            self.provider.terminate()
            self.provider.wait(timeout=10)

    def teardown(self):
        for proc in self.procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in self.procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


@pytest.fixture
def demo(tmp_path):
    d = Demo(tmp_path)
    try:
        yield d
    finally:
        d.teardown()


def test_two_agent_demo_completes_verified(demo):
    demo.start_backends()
    demo.start_provider()

    outcome, returncode = demo.run_requester()
    assert outcome["status"] == "verified", outcome
    assert outcome["verified"] is True
    assert returncode == 0
    assert outcome["evidence_status"] == "verified"
    assert 'resource "aws_lb"' in outcome["artifacts"]["main.tf"]

    # Reputation Record updated and visible in the registry afterwards.
    resp = requests.get(
        demo.registry_url + "/search",
        params={"capability": CAPABILITY_ID, "min_reputation": "0.9"},
        timeout=5,
    )
    candidates = resp.json()["candidates"]
    assert candidates, "verified task should leave a >=0.9 reputation record"
    summary = candidates[0]["reputation_summary"]
    assert summary["tasks_verified"] >= 1
    assert summary["verification_rate"] == 1.0


def test_requester_does_not_hang_when_provider_is_gone(demo):
    demo.start_backends()
    demo.start_provider()
    # Provider is registered; now it dies. The requester still discovers its
    # stale card but must fail cleanly, not hang.
    demo.stop_provider()

    start = time.time()
    outcome, returncode = demo.run_requester(timeout=30)
    elapsed = time.time() - start

    assert outcome["status"] == "provider_error", outcome
    assert returncode == 1
    assert elapsed < 25, "requester should fail fast, not hang (%.1fs)" % elapsed
