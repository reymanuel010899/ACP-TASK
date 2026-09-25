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


#: Named limitations of the credential contract. A provider that authenticates
#: with an account identifier and a long-lived auth token has no browser
#: redirect, no code exchange, and no refresh token — that is a shape, not a
#: fault, so callers branch on the name rather than on prose in a message.
INTERACTIVE_AUTHORIZATION_UNSUPPORTED = "interactive_authorization_unsupported"
REFRESH_AUTHORITY_UNSUPPORTED = "refresh_authority_unsupported"
PROVIDER_REVOCATION_UNSUPPORTED = "provider_revocation_unsupported"


class ConnectorLimitation(ProviderError):
    """The connector does not implement an optional part of the contract.

    Distinct from a failure: nothing went wrong, the provider simply has no
    such mechanism. The limitation is carried as a stable name so a caller can
    record it rather than guess from the message.
    """

    def __init__(self, provider, limitation):
        ProviderError.__init__(
            self, "%s does not support %s" % (provider, limitation)
        )
        self.provider = provider
        self.limitation = limitation


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
    """What every provider must answer, whatever shape its credential has.

    The redirect-and-refresh methods used to be abstract here, which asserted
    that every provider is an OAuth provider. Only the scope catalog is truly
    universal: a provider with no scope system still has to say what authority
    its capabilities are expressed in, because the policy evaluator and the
    runtime registry both decide by scope subset. The rest are declared
    optional and answer with a named limitation, so an unsupported mechanism is
    reported rather than mistaken for a broken one.
    """

    provider = "provider"
    #: Whether authority is obtained by sending a person through a browser.
    supports_interactive_authorization = False
    #: Whether the provider issues refresh tokens that can be exchanged.
    supports_refresh = False
    #: Whether the provider offers an endpoint that invalidates a live token.
    supports_provider_revocation = False

    @abstractmethod
    def scope_catalog(self):
        raise NotImplementedError

    def authorization_url(self, state, code_challenge, scopes):
        raise ConnectorLimitation(
            self.provider, INTERACTIVE_AUTHORIZATION_UNSUPPORTED
        )

    def exchange_code(self, code, code_verifier):
        raise ConnectorLimitation(
            self.provider, INTERACTIVE_AUTHORIZATION_UNSUPPORTED
        )

    def refresh(self, refresh_token):
        raise ConnectorLimitation(self.provider, REFRESH_AUTHORITY_UNSUPPORTED)

    def revoke(self, token):
        raise ConnectorLimitation(
            self.provider, PROVIDER_REVOCATION_UNSUPPORTED
        )


class OAuthCredentialConnector(CredentialConnector):
    """A provider whose authority comes from consent and can be refreshed.

    Keeping the four OAuth methods abstract here preserves the guarantee the
    old single base class gave: an OAuth connector that forgets to implement
    revoke still fails at construction, not at revocation time.
    """

    supports_interactive_authorization = True
    supports_refresh = True
    supports_provider_revocation = True

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


class StaticCredentialConnector(CredentialConnector):
    """A provider authenticated by an account identifier plus an auth token.

    There is no consent callback to read authority out of, so authority is
    read from the account instead: ``verify_account`` returns what the account
    verifiably has — which capability families are live, which sending
    identities exist and are enabled, which destinations they may reach, which
    templates are approved — and the caller derives scopes from that. It is
    called at connection time and again on re-verification, because account
    state changes without anyone visiting a browser.
    """

    supports_interactive_authorization = False
    supports_refresh = False
    supports_provider_revocation = False

    @abstractmethod
    def verify_account(self, account_id, auth_token):
        """Return the account's verified state as a mapping.

        The shape is the one :func:`libs.integrations.catalog.account_state`
        accepts. Raising means the account could not be verified at all, which
        the caller must treat as no authority rather than as unchanged
        authority.
        """
        raise NotImplementedError


class ActionExecutor(metaclass=ABCMeta):
    @abstractmethod
    def execute(self, capability_id, payload, provider_context):
        raise NotImplementedError

    @abstractmethod
    def read(self, capability_id, payload, provider_context):
        raise NotImplementedError
