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
        http_timeout=DEFAULT_HTTP_TIMEOUT,
    ):
        # type: (str, str, dict, float, float) -> None
        if not registry_url:
            raise ValueError(
                "registry_url is required (KTD5: the registry URL is "
                "configurable and never hardcoded)"
            )
        self.registry_url = registry_url.rstrip("/")
        self.capability = capability
        self.task_input = (
            dict(task_input) if task_input is not None else dict(DEFAULT_TASK_INPUT)
        )
        self.min_reputation = min_reputation
        self.http_timeout = http_timeout
