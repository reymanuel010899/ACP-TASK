"""Configuration for the AgentTrust demo Requester Agent (unit U5).

The requester reads its registry URL from configuration, never a hardcoded
constant (KTD5 / R5): the same requester binary can be pointed at any registry
— or several — that speaks the U4 API contract. Nothing here couples the
requester to a specific registry instance.
"""

DEFAULT_CAPABILITY = "terraform.generate"

# Demo task: two containers behind an AWS Application Load Balancer (R7).
DEFAULT_TASK_INPUT = {"containers": 2, "load_balancer": "alb"}

DEFAULT_HTTP_TIMEOUT = 15.0


class RequesterConfig(object):
    """Everything the requester needs to run one discovery-and-task cycle.

    ``registry_url`` is REQUIRED and has no default: a requester with no
    configured directory is a configuration error, not a silent fallback to
    some well-known instance (KTD5).
    """

    def __init__(
        self,
        registry_url,
        capability=DEFAULT_CAPABILITY,
        task_input=None,
        min_reputation=None,
        fan_out=3,
        top_counter=2,
        counter_fraction=0.9,
        require_portfolio_for_unproven=True,
        verification_url=None,
        provider_tokens=None,
        http_timeout=DEFAULT_HTTP_TIMEOUT,
    ):
        # type: (str, str, dict, float, int, int, float, bool, Optional[str], dict, float) -> None
        if not registry_url:
            raise ValueError(
                "registry_url is required (KTD5: the registry URL is "
                "configurable and never hardcoded)"
            )
        if fan_out < 1:
            raise ValueError("fan_out must be >= 1")
        if not 0 < counter_fraction <= 1:
            raise ValueError("counter_fraction must be in (0, 1]")
        self.registry_url = registry_url.rstrip("/")
        self.capability = capability
        self.task_input = (
            dict(task_input) if task_input is not None else dict(DEFAULT_TASK_INPUT)
        )
        self.min_reputation = min_reputation
        # Competitive-negotiation knobs (U4):
        self.fan_out = fan_out  # how many candidates to request offers from
        self.top_counter = top_counter  # how many cheapest offers to counter
        self.counter_fraction = counter_fraction  # counter at this * their price
        # An unproven (no-history) candidate must show verified portfolio work
        # to win over a proven one; assurance by verified facts (R4 / KTD-N3).
        self.require_portfolio_for_unproven = require_portfolio_for_unproven
        # A TRUSTED verification service URL the requester itself configures.
        # Portfolio assurance is only honored when checked here — never against
        # a URL a candidate declares on its own Agent Card (which an attacker
        # controls, and could stuff with fake 'verified' entries).
        self.verification_url = (
            verification_url.rstrip("/") if verification_url else None
        )
        # Bearer tokens to present to providers that require auth, keyed by
        # principal_id. A provider that requires auth but has no token here is
        # simply not eligible (RFC-0002 §7.4 / R3) — never a hard failure.
        self.provider_tokens = dict(provider_tokens or {})
        self.http_timeout = http_timeout
