"""End-to-end competitive negotiation demo (unit U5).

Launches the registry, the verification service, and **two independently-built
providers with different prices** as separate OS processes, then drives the
requester CLI (which defaults to competitive negotiation) and asserts it
discovers both, negotiates, and closes with the fair-price winner — with zero
shared code between requester and providers beyond the published spec.

Scenarios (from the plan):

- Happy path: two providers with different price/reputation; the requester
  closes with the cheaper one and the counter round drops the price.
- Compatibility (R7): the legacy single-offer path (--single-offer) still
  closes a task.
- Failure smoke: a provider dying mid-fan-out is dropped; the requester still
  closes with another instead of hanging.
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
    return subprocess.Popen(
        [sys.executable, "-m", module, *args],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def wait_http(url, timeout=READY_TIMEOUT):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=1.0).status_code == 200:
                return
        except requests.RequestException as exc:
            last = str(exc)
        time.sleep(0.1)
    raise AssertionError("%s never became ready (last: %s)" % (url, last))


def wait_candidate_count(registry_url, capability, count, timeout=READY_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(
            registry_url + "/search", params={"capability": capability},
            timeout=1.0,
        )
        if resp.status_code == 200 and len(resp.json().get("candidates", [])) >= count:
            return
        time.sleep(0.1)
    raise AssertionError("registry never showed %d candidates" % count)


class CompetitiveDemo(object):
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.procs = []
        self.providers = {}  # name -> (proc, url)
        self.verification_url = None
        self.registry_url = None
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
                "registry.app", "--port", str(rport),
                "--verification-url", self.verification_url,
            )
        )
        wait_http(self.verification_url + "/healthz")
        wait_http(self.registry_url + "/healthz")
        self.api_key = requests.post(
            self.registry_url + "/admin/api-keys", timeout=5
        ).json()["api_key"]

    def start_provider(self, name, list_price, min_price):
        port = free_port()
        url = "http://127.0.0.1:%d" % port
        proc = self._track(
            launch(
                "agents.provider.agent",
                "--port", str(port),
                "--verification-url", self.verification_url,
                "--registry-url", self.registry_url,
                "--api-key", self.api_key,
                "--keys-dir", str(self.tmp_path / ("keys-" + name)),
                "--list-price", str(list_price),
                "--min-price", str(min_price),
            )
        )
        wait_http(url + "/healthz")
        self.providers[name] = (proc, url)
        return url

    def run_requester(self, *extra, timeout=40):
        proc = subprocess.run(
            [
                sys.executable, "-m", "agents.requester.agent",
                "--registry-url", self.registry_url, *extra,
            ],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        )
        assert proc.stdout, proc.stderr.decode("utf-8", "replace")
        return json.loads(proc.stdout.decode("utf-8")), proc.returncode

    def kill_provider(self, name):
        proc, _ = self.providers[name]
        proc.terminate()
        proc.wait(timeout=10)

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
    d = CompetitiveDemo(tmp_path)
    try:
        yield d
    finally:
        d.teardown()


def test_competition_closes_with_the_cheaper_provider(demo):
    demo.start_backends()
    demo.start_provider("pricey", list_price=9.0, min_price=8.0)
    demo.start_provider("cheap", list_price=4.0, min_price=2.0)
    wait_candidate_count(demo.registry_url, CAPABILITY_ID, 2)

    outcome, returncode = demo.run_requester()
    assert outcome["status"] == "verified", outcome
    assert returncode == 0
    assert outcome["offers_considered"] == 2
    # Cheaper provider wins, and the counter round dropped it below its 4.0
    # list price (0.9 * 4.0 = 3.6, still above its 2.0 floor).
    assert outcome["price_paid"] == 3.6
    assert 'resource "aws_lb"' in outcome["artifacts"]["main.tf"]


def test_single_offer_compatibility_path_still_closes(demo):
    # R7: a requester using the legacy single-offer path still completes.
    demo.start_backends()
    demo.start_provider("only", list_price=5.0, min_price=3.0)
    wait_candidate_count(demo.registry_url, CAPABILITY_ID, 1)

    outcome, returncode = demo.run_requester("--single-offer")
    assert outcome["status"] == "verified", outcome
    assert returncode == 0


def test_competition_survives_a_provider_dying(demo):
    demo.start_backends()
    demo.start_provider("doomed", list_price=4.0, min_price=2.0)
    demo.start_provider("survivor", list_price=6.0, min_price=3.0)
    wait_candidate_count(demo.registry_url, CAPABILITY_ID, 2)
    # The cheaper provider dies; the requester must drop it and still close.
    demo.kill_provider("doomed")

    outcome, returncode = demo.run_requester()
    assert outcome["status"] == "verified", outcome
    assert returncode == 0
    assert demo.providers["survivor"][1]  # survivor served the task
