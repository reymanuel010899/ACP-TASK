"""Production composition for the provider-neutral action broker."""

import json
import os

import requests

from agents.orchestrator.action_repository import ActionRepository
from agents.orchestrator.attestation import ExecutionAttestor
from agents.orchestrator.policy import PolicyEvaluator
from libs.aws_kms import AWSKMSClient
from libs.config import ConfigurationError, get_google_oauth_config, get_slack_oauth_config
from libs.connectors.google import (
    GoogleActionExecutor,
    GoogleCredentialConnector,
)
from libs.connectors.slack import SlackActionExecutor, SlackCredentialConnector
from libs.integrations.catalog import (
    ProviderRuntime,
    ProviderRuntimeRegistry,
    google_definitions,
    slack_definitions,
)
from libs.db import Database
from libs.signing import load_signing_key
from services.action_broker.app import (
    ActionBroker,
    oauth_connection_authorizer,
)
from services.action_broker.rate_limits import SlackRatePolicy
from services.action_broker.token_rotation import ManagedOAuthRotator
from services.oauth.repository import OAuthRepository
from services.session.repository import SessionRepository
from vault.app import VaultService
from vault.managed_oauth_crypto import ManagedOAuthCrypto


def _required(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError("%s is required" % name)
    return value


def _trusted_agent_resolver():
    try:
        endpoints = json.loads(_required("TESSERA_AGENT_ENDPOINTS_JSON"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "TESSERA_AGENT_ENDPOINTS_JSON must be a JSON object"
        ) from exc
    if not isinstance(endpoints, dict) or not endpoints:
        raise RuntimeError(
            "TESSERA_AGENT_ENDPOINTS_JSON must be a non-empty object"
        )

    def resolve(principal_id):
        endpoint = endpoints.get(principal_id)
        return endpoint if isinstance(endpoint, str) else None

    return resolve


def _evidence_submitter():
    endpoint = _required("TESSERA_VERIFICATION_EVIDENCE_URL")
    timeout = float(os.environ.get("TESSERA_SERVICE_TIMEOUT_SECONDS", "10"))

    def submit(evidence):
        response = requests.post(
            endpoint,
            json={"evidence": evidence},
            timeout=timeout,
        )
        try:
            body = response.json()
        except ValueError:
            body = {}
        return response.status_code, body

    return submit


def build_broker():
    """Build a fail-closed broker from deployment secrets and durable stores."""
    google = get_google_oauth_config()
    try:
        slack = get_slack_oauth_config()
    except ConfigurationError:
        if any(key.startswith("SLACK_OAUTH_") for key in os.environ):
            raise
        slack = None
    broker_identity = os.environ.get(
        "TESSERA_BROKER_IDENTITY", "service:credential-broker"
    )
    oauth_ingestion_identity = os.environ.get(
        "TESSERA_OAUTH_INGESTION_IDENTITY", "service:oauth-ingestion"
    )
    managed_crypto = ManagedOAuthCrypto(
        AWSKMSClient(),
        os.environ.get("MANAGED_OAUTH_KMS_KEY_ID")
        or _required("GOOGLE_OAUTH_KMS_KEY_ID"),
        ingestion_identities={oauth_ingestion_identity},
        broker_identity=broker_identity,
    )
    connector = GoogleCredentialConnector(
        google.client_id,
        google.client_secret,
        google.redirect_uri,
    )
    oauth_repository = OAuthRepository(
        _required("TESSERA_OAUTH_DATABASE_PATH")
    )
    keypair = load_signing_key(_required("TESSERA_BROKER_SIGNING_KEY"))

    executor = GoogleActionExecutor()
    runtimes = [ProviderRuntime(
        provider="google",
        connector=connector,
        executor=executor,
        definitions=google_definitions(),
    )]
    credential_rotators = {}
    vault_service = VaultService(
        db=Database(),
        managed_oauth_crypto=managed_crypto,
    )
    if slack is not None:
        slack_connector = SlackCredentialConnector(
            slack.client_id, slack.client_secret, slack.redirect_uri
        )
        slack_executor = SlackActionExecutor(rate_policy=SlackRatePolicy())
        runtimes.append(ProviderRuntime(
            provider="slack",
            connector=slack_connector,
            executor=slack_executor,
            definitions=slack_definitions(),
        ))
        credential_rotators["slack"] = ManagedOAuthRotator(
            vault_service, slack_connector
        )
    runtime_registry = ProviderRuntimeRegistry(runtimes)
    rollout_version = os.environ.get(
        "TESSERA_CAPABILITY_ROLLOUT_VERSION", "production-v1"
    )
    policy_evaluator = PolicyEvaluator(
        runtime_registry.definitions(), rollout_version
    )

    def dispatch_policy(binding):
        if binding.get("workflow_revision_id") not in (None, "legacy"):
            if os.environ.get(
                "TESSERA_DYNAMIC_EXECUTION_ENABLED", "false"
            ).lower() != "true":
                return False
        if str(binding.get("capability_id", "")).startswith("slack."):
            return os.environ.get(
                "TESSERA_SLACK_EXECUTION_ENABLED", "false"
            ).lower() == "true"
        return True

    return ActionBroker(
        ActionRepository(_required("TESSERA_ACTION_DATABASE_PATH")),
        SessionRepository(_required("TESSERA_SESSION_DATABASE_PATH")),
        vault_service,
        executor,
        broker_identity=broker_identity,
        agent_url_resolver=_trusted_agent_resolver(),
        credential_authorizer=oauth_connection_authorizer(
            oauth_repository
        ),
        credential_connector=connector,
        attestor=ExecutionAttestor(
            _required("TESSERA_BROKER_KEY_ID"), keypair.signing_key
        ),
        evidence_submitter=_evidence_submitter(),
        runtime_registry=runtime_registry,
        rollout_version=rollout_version,
        credential_rotators=credential_rotators,
        dispatch_policy=dispatch_policy,
        policy_evaluator=policy_evaluator,
        connection_resolver=oauth_repository.get_installation,
    )
