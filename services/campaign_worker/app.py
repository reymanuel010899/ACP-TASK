"""Generate one short authorized effect per campaign contact-cycle."""

import argparse
import importlib
import os
import time

from agents.orchestrator.dispatch_ledger import AmbiguousDispatch
from libs.connectors.base import ProviderHTTPError, ProviderNetworkError
from libs.spend_ledger import SpendCeilingExceeded
from services.action_broker.rate_limits import ThroughputExceeded


class CampaignWorker:
    def __init__(self, repository, worker_id, eligibility, dispatch, clock=None,
                 connection_available=None, emergency_stopped=None,
                 throughput=None, lease_seconds=60, authority_check=None):
        self.repository = repository
        self.worker_id = worker_id
        self.eligibility = eligibility
        self.dispatch = dispatch
        self.clock = clock or time.time
        self.connection_available = connection_available or (lambda *_: True)
        self.emergency_stopped = emergency_stopped or (lambda *_: False)
        self.throughput = throughput
        self.authority_check = authority_check
        self.lease_seconds = int(lease_seconds)

    def tick(self):
        now = int(self.clock())
        self.repository.recover_expired_claims(now)
        selected = self.repository.next_campaign(now)
        if selected is None:
            return False
        tenant_id, campaign_id = selected["tenant_id"], selected["campaign_id"]
        campaign = self.repository.get(tenant_id, campaign_id)
        self.repository.assert_envelope(
            tenant_id, campaign_id, campaign["definition"]
        )
        if self.authority_check is not None and self.repository.check_authority(
            tenant_id, campaign_id, self.authority_check
        ) != "valid":
            return "reaffirmation_required"
        if self.repository.expire(tenant_id, campaign_id, now):
            return "expired"
        if self.emergency_stopped(tenant_id):
            self.repository.stop(tenant_id, campaign_id, "emergency_stopped")
            return "stopped"
        if not self.connection_available(tenant_id, campaign):
            self.repository.set_status(tenant_id, campaign_id, "blocked_connection",
                                       "connection_unavailable")
            return "blocked_connection"
        if campaign["status"] == "blocked_connection":
            self.repository.set_status(tenant_id, campaign_id, "running")
        effect = self.repository.claim_next(
            self.worker_id, now, self.lease_seconds, tenant_id, campaign_id,
        )
        if effect is None:
            return self.repository.finalize(tenant_id, campaign_id) or False
        decision = self.eligibility(effect, campaign) or {}
        if not decision.get("allowed"):
            defer_until = decision.get("defer_until")
            if defer_until is not None:
                if int(defer_until) > int(campaign["envelope_expires_at"]):
                    self.repository.complete_effect(
                        effect, "never_eligible", decision.get("reason")
                    )
                    self.repository.finalize(tenant_id, campaign_id)
                    return "never_eligible"
                self.repository.complete_effect(
                    effect, "deferred", decision.get("reason"),
                    defer_until=defer_until,
                )
                self.repository.set_status(
                    tenant_id, campaign_id, "deferred_quiet_hours",
                    decision.get("reason"),
                )
                return "deferred"
            self.repository.complete_effect(
                effect, "prevented", decision.get("reason") or "ineligible"
            )
            self.repository.finalize(tenant_id, campaign_id)
            return "prevented"
        try:
            if self.throughput is not None:
                self.throughput.acquire(
                    tenant_id, "twilio.%s.send" % effect["channel"]
                )
            result = self.dispatch(effect, campaign)
        except ThroughputExceeded as exc:
            self.repository.complete_effect(
                effect, "deferred", "throughput_limited", defer_until=exc.retry_at
            )
            self.repository.set_status(tenant_id, campaign_id, "throttled")
            return "throttled"
        except SpendCeilingExceeded as exc:
            self.repository.complete_effect(effect, "prevented", exc.reason)
            self.repository.drain_remaining(tenant_id, campaign_id, exc.reason)
            self.repository.finalize(tenant_id, campaign_id)
            return "prevented"
        except (AmbiguousDispatch, TimeoutError):
            self.repository.complete_effect(
                effect, "uncertain", "provider_outcome_unknown", count_attempt=True
            )
            self.repository.finalize(tenant_id, campaign_id)
            return "uncertain"
        except ProviderNetworkError:
            # A network error after crossing the provider boundary cannot
            # prove absence. It must reconcile before any retry.
            self.repository.complete_effect(
                effect, "uncertain", "provider_outcome_unknown", count_attempt=True
            )
            self.repository.finalize(tenant_id, campaign_id)
            return "uncertain"
        except ProviderHTTPError:
            # A definite provider rejection created no effect. It is safe to
            # prevent this recipient and continue the fixed cohort; retrying
            # the same invalid request would only consume throughput.
            self.repository.complete_effect(
                effect, "prevented", "provider_rejected", count_attempt=True
            )
            self.repository.finalize(tenant_id, campaign_id)
            return "prevented"
        self.repository.complete_effect(
            effect, "completed", provider_id=result.get("provider_id"),
            count_attempt=True,
        )
        self.repository.finalize(tenant_id, campaign_id)
        return "completed"


def load_worker(factory_path):
    """Load deployment composition without putting vendor types in the worker."""
    if not factory_path or ":" not in factory_path:
        raise RuntimeError("CAMPAIGN_WORKER_FACTORY must be module:function")
    module_name, function_name = factory_path.split(":", 1)
    factory = getattr(importlib.import_module(module_name), function_name)
    worker = factory()
    if not isinstance(worker, CampaignWorker):
        raise TypeError("campaign worker factory returned the wrong type")
    return worker


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--factory", default=os.environ.get("CAMPAIGN_WORKER_FACTORY"))
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args(argv)
    worker = load_worker(args.factory)
    while True:
        worker.tick()
        time.sleep(max(0.1, args.poll_seconds))


if __name__ == "__main__":
    main()
