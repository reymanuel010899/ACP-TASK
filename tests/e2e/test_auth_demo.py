"""End-to-end authentication demo (unit U7).

Launches verification, a registry (with an admin token), and an
**authenticating** provider as separate OS processes, then drives the requester
CLI to show the full auth story:

- with the right token, the auth provider competes and wins verified;
- without it, the auth provider is not eligible (no_candidates);
- the admin key surface is gated (401 without the admin token);
- a rate-limited registry returns 429 past its cap.
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
READY = 20.0
ADMIN = "adm-token"
PROV_TOKEN = "prov-token"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def launch(module, *args):
    return subprocess.Popen(
        [sys.executable, "-m", module, *args],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def wait_http(url, timeout=READY):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=1.0).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.1)
    raise AssertionError("%s never became ready" % url)


def principal_id_of(provider_url):
    card = requests.get(
        provider_url + "/.well-known/agent-card.json", timeout=5
    ).json()
    for ext in card["capabilities"]["extensions"]:
        if ext.get("params", {}).get("principal_id"):
            return ext["params"]["principal_id"]
    raise AssertionError("no principal_id in card")


class AuthDemo(object):
    def __init__(self, tmp_path, admin_token=ADMIN):
        self.tmp_path = tmp_path
        self.procs = []
        vport, rport = free_port(), free_port()
        self.verification_url = "http://127.0.0.1:%d" % vport
        self.registry_url = "http://127.0.0.1:%d" % rport
        self.procs.append(launch("services.verification.app", "--port", str(vport)))
        self.procs.append(
            launch(
                "registry.app", "--port", str(rport),
                "--verification-url", self.verification_url,
                "--admin-token", admin_token,
            )
        )
        wait_http(self.verification_url + "/healthz")
        wait_http(self.registry_url + "/healthz")
        self.api_key = requests.post(
            self.registry_url + "/admin/api-keys",
            headers={"Authorization": "Bearer %s" % admin_token},
            timeout=5,
        ).json()["api_key"]

    def start_auth_provider(self):
        pport = free_port()
        url = "http://127.0.0.1:%d" % pport
        self.procs.append(
            launch(
                "agents.provider.agent",
                "--port", str(pport),
                "--verification-url", self.verification_url,
                "--registry-url", self.registry_url,
                "--api-key", self.api_key,
                "--keys-dir", str(self.tmp_path / "prov-keys"),
                "--list-price", "3", "--min-price", "1",
                "--auth-token", PROV_TOKEN,
            )
        )
        wait_http(url + "/healthz")
        # wait until searchable
        deadline = time.time() + READY
        while time.time() < deadline:
            if requests.get(
                self.registry_url + "/search",
                params={"capability": CAPABILITY_ID}, timeout=1.0
            ).json().get("candidates"):
                break
            time.sleep(0.1)
        return url

    def run_requester(self, *extra, timeout=40):
        proc = subprocess.run(
            [
                sys.executable, "-m", "agents.requester.agent",
                "--registry-url", self.registry_url,
                "--verification-url", self.verification_url, *extra,
            ],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        )
        assert proc.stdout, proc.stderr.decode("utf-8", "replace")
        return json.loads(proc.stdout.decode("utf-8")), proc.returncode

    def teardown(self):
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
        for p in self.procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


@pytest.fixture
def demo(tmp_path):
    d = AuthDemo(tmp_path)
    try:
        yield d
    finally:
        d.teardown()


def test_auth_provider_wins_with_the_right_token(demo):
    prov_url = demo.start_auth_provider()
    principal = principal_id_of(prov_url)
    outcome, code = demo.run_requester(
        "--provider-token", "%s=%s" % (principal, PROV_TOKEN)
    )
    assert outcome["status"] == "verified", outcome
    assert code == 0
    assert outcome["provider_principal_id"] == principal


def test_auth_provider_not_eligible_without_token(demo):
    demo.start_auth_provider()
    outcome, code = demo.run_requester()  # no token configured
    assert outcome["status"] == "no_candidates", outcome
    assert code == 1


def test_admin_surface_is_gated(demo):
    # Minting without the admin token is refused.
    resp = requests.post(demo.registry_url + "/admin/api-keys", timeout=5)
    assert resp.status_code == 401


def test_rate_limited_registry_returns_429(tmp_path):
    rport = free_port()
    proc = launch(
        "registry.app", "--port", str(rport), "--rate-limit", "3"
    )
    url = "http://127.0.0.1:%d" % rport
    try:
        wait_http(url + "/healthz")  # 1st request
        search = url + "/search?capability=" + CAPABILITY_ID
        codes = [requests.get(search, timeout=2).status_code for _ in range(3)]
        # /healthz used 1 of the 3-per-window budget; the 3rd search exceeds it.
        assert 429 in codes
    finally:
        proc.terminate()
        proc.wait(timeout=10)
