import threading

import requests

from agents.orchestrator.broker_client import ActionBrokerClient
from services.action_broker.app import make_server


class Broker(object):
    def __init__(self):
        self.calls = []

    def execute(self, lease, binding, payload):
        self.calls.append((lease, binding, payload))
        return 202, {"status": "execution_unknown"}


def test_internal_execution_requires_service_auth_and_preserves_status():
    broker = Broker()
    server = make_server(
        broker,
        host="127.0.0.1",
        port=0,
        internal_token="internal-secret",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = "http://127.0.0.1:%d" % server.server_address[1]
    request = {
        "lease": "lease-1",
        "binding": {"capability_id": "calendar.create"},
        "payload": {"event": {"summary": "Interview"}},
    }
    try:
        unauthorized = requests.post(
            base_url + "/internal/execute",
            json=request,
            timeout=5,
        )
        assert unauthorized.status_code == 401
        assert broker.calls == []

        client = ActionBrokerClient(
            base_url, "internal-secret", timeout=5
        )
        status, response = client.execute(
            request["lease"], request["binding"], request["payload"]
        )
        assert status == 202
        assert response == {"status": "execution_unknown"}
        assert broker.calls == [
            (
                request["lease"],
                request["binding"],
                request["payload"],
            )
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
