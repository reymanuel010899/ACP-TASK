"""Serialized compare-and-swap rotation for single-use OAuth refresh tokens."""

import threading
import time

from libs.connectors.base import REFRESH_AUTHORITY_UNSUPPORTED


class ManagedOAuthRotator(object):
    def __init__(self, vault, connector, clock=None, refresh_skew_seconds=300):
        self.vault = vault
        self.connector = connector
        self.clock = clock or time.time
        self.refresh_skew_seconds = refresh_skew_seconds
        self._guard = threading.Lock()
        self._locks = {}

    def rotate(self, connection_id, credential_id, service_identity):
        lock = self._connection_lock(connection_id)
        with lock:
            version, status, document = self.vault.read_rotation_document(
                credential_id, service_identity
            )
            if status != "active":
                raise PermissionError("credential is not active")
            # A provider that issues no refresh tokens has not lost its
            # refresh authority; it never had any. Reporting that as a named
            # limitation keeps a static credential dispatchable, while a
            # provider that does refresh and arrives without a refresh token
            # still fails closed below.
            if not getattr(self.connector, "supports_refresh", True):
                return {
                    "credential_version": version,
                    "status": "active",
                    "limitation": REFRESH_AUTHORITY_UNSUPPORTED,
                }
            if document.get("expires_at", 0) > (
                self.clock() + self.refresh_skew_seconds
            ):
                return {
                    "credential_version": version,
                    "status": "active",
                    "limitation": None,
                }
            refresh_token = document.get("refresh_token")
            if not isinstance(refresh_token, str) or not refresh_token:
                raise PermissionError("refresh authority is unavailable")
            authority = self.connector.refresh(refresh_token)
            if not authority.refresh_token:
                raise PermissionError("provider did not rotate refresh authority")
            replacement = {
                "access_token": authority.access_token,
                "refresh_token": authority.refresh_token,
                "expires_at": int(self.clock()) + authority.expires_in,
                "token_type": authority.token_type,
                "provider_metadata": dict(
                    authority.provider_metadata or document.get("provider_metadata", {})
                ),
                "granted_scopes": sorted(authority.granted_scopes),
            }
            if not self.vault.compare_and_swap_rotation_document(
                credential_id,
                version,
                replacement,
                service_identity,
            ):
                raise PermissionError("credential rotation lost its version fence")
            return {
                "credential_version": version + 1,
                "status": "active",
                "limitation": None,
            }

    def _connection_lock(self, connection_id):
        with self._guard:
            return self._locks.setdefault(connection_id, threading.Lock())
