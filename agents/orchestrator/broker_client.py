"""Authenticated internal client for the Tessera action broker."""

import requests


class ActionBrokerClient(object):
    def __init__(self, base_url, service_token, timeout=10.0, http=None):
        if not base_url or not service_token:
            raise ValueError("action broker URL and service token are required")
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token
        self.timeout = float(timeout)
        self.http = http or requests

    def execute(self, lease, binding, payload):
        response = self.http.post(
            self.base_url + "/internal/execute",
            json={
                "lease": lease,
                "binding": binding,
                "payload": payload,
            },
            headers={
                "Authorization": "Bearer %s" % self.service_token,
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
        )
        try:
            body = response.json()
        except ValueError:
            body = {"error": "action broker returned invalid JSON"}
        return response.status_code, body
