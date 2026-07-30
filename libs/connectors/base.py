"""Provider-agnostic boundaries for credential lifecycle and provider calls."""

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass, field
from typing import Any, FrozenSet, Mapping, Optional


class ProviderError(Exception):
    """Base class for connector failures safe to handle by callers."""


class ProviderNetworkError(ProviderError):
    """The provider could not be reached."""


class ProviderHTTPError(ProviderError):
    """The provider returned a non-success response."""

    def __init__(self, provider, status_code, operation):
        ProviderError.__init__(
            self,
            "%s %s failed with HTTP %s"
            % (provider, operation, status_code),
        )
        self.provider = provider
        self.status_code = status_code
        self.operation = operation


class UnsupportedCapabilityError(ProviderError):
    """The executor has no closed, typed implementation for a capability."""


@dataclass(frozen=True)
class ProviderAuthority:
    """Actual authority returned by a provider token endpoint.

    This object is internal to the credential broker.  It deliberately records
    the provider's real ``expires_in`` and granted scopes rather than accepting
    a caller-selected TTL or pretending refresh can downscope the token.
    """

    access_token: str
    expires_in: int
    granted_scopes: FrozenSet[str]
    token_type: str = "Bearer"
    refresh_token: Optional[str] = None
    provider_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderReceipt:
    provider: str
    capability_id: str
    provider_id: str


class CredentialConnector(metaclass=ABCMeta):
    @abstractmethod
    def authorization_url(self, state, code_challenge, scopes):
        raise NotImplementedError

    @abstractmethod
    def exchange_code(self, code, code_verifier):
        raise NotImplementedError

    @abstractmethod
    def refresh(self, refresh_token):
        raise NotImplementedError

    @abstractmethod
    def revoke(self, token):
        raise NotImplementedError

    @abstractmethod
    def scope_catalog(self):
        raise NotImplementedError


class ActionExecutor(metaclass=ABCMeta):
    @abstractmethod
    def execute(self, capability_id, payload, provider_context):
        raise NotImplementedError

    @abstractmethod
    def read(self, capability_id, payload, provider_context):
        raise NotImplementedError
