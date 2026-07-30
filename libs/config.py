"""Shared protocol constants — the ONE place the Tessera identity lives.

The trust-extension URI is a namespace identifier compared as an exact string:
an agent declares it on its card, and the registry/verification services match
against it, so it MUST be identical on every side (including the treessera SDK).
Change it here and every service follows; override per-process via the
``TREESSERA_URI`` env var — the same variable the SDK honors — without editing
code.
"""

import os
from dataclasses import dataclass

#: The A2A extension URI that marks an agent as a Tessera participant.
TRUST_EXTENSION_URI = os.environ.get(
    "TREESSERA_URI", "https://treessera.com/extensions/trust/v1"
)


class ConfigurationError(Exception):
    """Required deployment configuration is absent or malformed."""


@dataclass(frozen=True)
class GoogleOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str


@dataclass(frozen=True)
class SlackOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    app_id: str


def get_google_oauth_config(environ=None):
    """Read Google OAuth secrets lazily from the process environment.

    Nothing is defaulted to a development credential: deployments must source
    these values from their environment/secret manager.
    """
    source = environ if environ is not None else os.environ
    values = {
        "client_id": source.get("GOOGLE_OAUTH_CLIENT_ID"),
        "client_secret": source.get("GOOGLE_OAUTH_CLIENT_SECRET"),
        "redirect_uri": source.get("GOOGLE_OAUTH_REDIRECT_URI"),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ConfigurationError(
            "missing Google OAuth configuration: %s" % ", ".join(missing)
        )
    return GoogleOAuthConfig(**values)


def get_slack_oauth_config(environ=None):
    """Read the confidential Slack app configuration without defaults."""
    source = environ if environ is not None else os.environ
    values = {
        "client_id": source.get("SLACK_OAUTH_CLIENT_ID"),
        "client_secret": source.get("SLACK_OAUTH_CLIENT_SECRET"),
        "redirect_uri": source.get("SLACK_OAUTH_REDIRECT_URI"),
        "app_id": source.get("SLACK_OAUTH_APP_ID"),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ConfigurationError(
            "missing Slack OAuth configuration: %s" % ", ".join(missing)
        )
    return SlackOAuthConfig(**values)
