import json
import threading

from libs.connectors.base import ProviderAuthority
from services.action_broker.token_rotation import ManagedOAuthRotator


class FakeConnector:
    def __init__(self):
        self.calls = []

    def refresh(self, token):
        self.calls.append(token)
        return ProviderAuthority(
            access_token="xoxb-next",
            refresh_token="xoxe-next",
            expires_in=43200,
            granted_scopes=frozenset({"chat:write"}),
            token_type="bot",
        )


class FakeVault:
    def __init__(self):
        self.version = 1
        self.status = "active"
        self.document = {
            "access_token": "xoxb-current",
            "refresh_token": "xoxe-current",
            "expires_at": 100,
            "token_type": "bot",
            "provider_metadata": {"team_id": "T1"},
        }
        self.lock = threading.Lock()

    def read_rotation_document(self, credential_id, service_identity):
        with self.lock:
            return self.version, self.status, dict(self.document)

    def compare_and_swap_rotation_document(
        self, credential_id, expected_version, document, service_identity
    ):
        with self.lock:
            if self.status != "active" or self.version != expected_version:
                return False
            self.document = dict(document)
            self.version += 1
            return True


def test_concurrent_rotation_consumes_single_use_refresh_token_once():
    vault = FakeVault()
    connector = FakeConnector()
    rotator = ManagedOAuthRotator(vault, connector, clock=lambda: 200)
    results = []

    def run():
        results.append(rotator.rotate("conn:1", "cred:1", "service:broker"))

    threads = [threading.Thread(target=run), threading.Thread(target=run)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert connector.calls == ["xoxe-current"]
    assert sorted(result["credential_version"] for result in results) == [2, 2]
    assert vault.document["refresh_token"] == "xoxe-next"
    assert json.dumps(results).find("xoxe-") == -1
