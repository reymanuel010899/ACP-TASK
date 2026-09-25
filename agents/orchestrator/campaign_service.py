"""Application service joining campaign envelopes to contacts and Twilio."""

import json
import os
import threading
import time

from agents.orchestrator.campaign_repository import (
    CampaignEnvelopeChanged,
    CampaignPermissionDenied,
    CampaignStateConflict,
)
from libs.connectors.twilio import TwilioActionExecutor
from libs.contacts_permissions import DIMENSION_CAMPAIGN_USE
from libs.ulid import generate_ulid
from services.campaign_worker.app import CampaignWorker


class CampaignService(object):
    """Create a fixed preview, authorize it, and drain it as small effects."""

    def __init__(
        self, repository, contacts, access, permissions, consent,
        connections, vault, broker_identity="service:credential-broker",
        executor=None, clock=None, unit_price_micros=10_000,
        callback_base=None,
    ):
        self.repository = repository
        self.contacts = contacts
        self.access = access
        self.permissions = permissions
        self.consent = consent
        self.connections = connections
        self.vault = vault
        self.broker_identity = broker_identity
        self.executor = executor or TwilioActionExecutor()
        self.clock = clock or time.time
        self.unit_price_micros = int(unit_price_micros)
        self.callback_base = (callback_base or "https://example.com").rstrip("/")
        self._launch_lock = threading.Lock()
        self._running = set()

    def create_preview(self, tenant_id, principal_id, payload):
        branch_id = payload.get("branchId")
        name = str(payload.get("name") or "").strip()
        body = str(payload.get("body") or "").strip()
        purpose = str(payload.get("purpose") or "service")
        if not branch_id or not name or not body:
            raise ValueError("name, audience branch, and message are required")
        if len(name) > 120:
            raise ValueError("campaign name is too long")
        if len(body) > 1600:
            raise ValueError("SMS message cannot exceed 1600 characters")
        if purpose not in ("marketing", "utility", "authentication", "transactional", "service"):
            raise ValueError("unsupported campaign purpose")
        sender = self._sms_connection(tenant_id)["sender"]
        projection = self.access.audience_preview(
            tenant_id, principal_id, "sms", purpose, branch_id=branch_id,
            now=self._utc_now(), limit=500,
        )
        audience, exclusions = [], []
        for entry in projection["entries"]:
            contact_id = entry["contact_id"]
            address = self._sms_address(tenant_id, contact_id)
            member = {
                "contact_id": contact_id,
                "channel": "sms",
                "address_id": address["address_id"] if address else "excluded:%s" % contact_id,
                "branch_id": self.contacts.get_contact(tenant_id, contact_id)["primary_branch_id"],
                "masked_destination": (entry.get("destination") or {}).get("text") or "Sin número SMS",
            }
            if entry.get("excluded_reason"):
                member["reason"] = entry["excluded_reason"]
                exclusions.append(member)
            else:
                audience.append(member)
        if not audience:
            raise ValueError("the selected audience has no eligible SMS contacts")
        now = int(self.clock())
        starts_at = max(now, int(payload.get("startsAt") or now))
        ends_at = starts_at + 86_400
        estimated = len(audience) * self.unit_price_micros
        ceiling = int(payload.get("budgetMicros") or estimated)
        if ceiling < estimated:
            raise ValueError("campaign budget is below the estimated spend")
        definition = {
            "audience_rule": {"branch_id": branch_id, "include_descendants": True},
            "content": {"kind": "sms", "name": name, "body": body, "purpose": purpose},
            "channels": ["sms"], "senders": {"sms": sender},
            "schedule": {"starts_at": starts_at, "ends_at": ends_at},
            "frequency": {"max_per_contact": 1, "period_seconds": 86_400},
            "budget_micros": ceiling,
            "concurrency": min(10, max(1, int(payload.get("concurrency") or 2))),
            "duration_seconds": 86_400,
            "stop_conditions": ["budget_exhausted", "emergency_stop"],
            "include_late_arrivals": False,
            "audience_ceiling": len(audience),
        }
        campaign_id = "campaign:%s" % generate_ulid()
        return self.repository.create_preview(
            tenant_id, campaign_id, principal_id, definition, audience,
            exclusions=exclusions, estimated_spend_micros=estimated,
        )

    def authorize(self, tenant_id, principal_id, campaign_id, envelope_hash):
        current = self.repository.get(tenant_id, campaign_id)
        if current.get("envelope_hash") != envelope_hash:
            raise CampaignEnvelopeChanged("campaign preview binding changed")
        campaign = self.repository.authorize(
            tenant_id, campaign_id, principal_id,
            lambda actor, branch: self.permissions.holds(
                tenant_id, actor, branch, DIMENSION_CAMPAIGN_USE
            ),
        )
        self._launch(tenant_id, campaign_id)
        return campaign

    def detail(self, tenant_id, campaign_id):
        campaign = self.repository.get(tenant_id, campaign_id)
        preview = self.repository.preview(tenant_id, campaign_id)
        report = self.repository.report(tenant_id, campaign_id)
        return self._serialize(campaign, preview, report)

    def list(self, tenant_id):
        return [self._serialize(row, report=self.repository.report(
            tenant_id, row["campaign_id"]
        )) for row in self.repository.list_campaigns(tenant_id)]

    def _launch(self, tenant_id, campaign_id):
        key = (tenant_id, campaign_id)
        with self._launch_lock:
            if key in self._running:
                return
            self._running.add(key)
        thread = threading.Thread(
            target=self._drain, args=(tenant_id, campaign_id),
            name="campaign-%s" % campaign_id.rsplit(":", 1)[-1], daemon=True,
        )
        thread.start()

    def _drain(self, tenant_id, campaign_id):
        key = (tenant_id, campaign_id)
        worker = CampaignWorker(
            self.repository, "worker:web:%s" % os.getpid(),
            eligibility=self._eligibility, dispatch=self._dispatch,
            clock=self.clock,
            connection_available=lambda tenant, _campaign: bool(
                self._connections(tenant)
            ),
            authority_check=lambda actor, branch: self.permissions.holds(
                tenant_id, actor, branch, DIMENSION_CAMPAIGN_USE
            ),
        )
        try:
            while True:
                campaign = self.repository.get(tenant_id, campaign_id)
                if campaign["status"] in (
                    "drained", "reconciling", "expired", "stopped", "invalidated"
                ):
                    break
                outcome = worker.tick()
                if outcome in (False, "blocked_connection", "reaffirmation_required"):
                    break
        finally:
            with self._launch_lock:
                self._running.discard(key)

    def _eligibility(self, effect, campaign):
        content = campaign["definition"]["content"]
        sender = campaign["definition"]["senders"]["sms"]
        decision = self.consent.evaluate_eligibility(
            effect["tenant_id"], effect["address_id"], "sms",
            content["purpose"], sender_id=sender, now=self._utc_now(),
        )
        return {"allowed": decision.eligible, "reason": decision.reason}

    def _dispatch(self, effect, campaign):
        connection = self._sms_connection(effect["tenant_id"])
        address = self.contacts.get_address(effect["tenant_id"], effect["address_id"])
        if address is None:
            raise ValueError("campaign destination no longer exists")
        definition = campaign["definition"]
        payload = {
            "to": address["address_normalized"],
            "from": definition["senders"]["sms"],
            "body": definition["content"]["body"],
            "status_callback": "%s/twilio/status" % self.callback_base,
        }
        def execute(raw):
            document = json.loads(raw.decode("utf-8"))
            return self.executor.execute(
                "twilio.sms.send", payload,
                {"account_id": document["account_id"], "access_token": document["auth_token"]},
            )
        receipt = self.vault.use_managed_oauth(
            connection["credential_id"], self.broker_identity, execute,
        )
        self.contacts.record_contacted(effect["tenant_id"], effect["address_id"], self._utc_now())
        return receipt

    def _connections(self, tenant_id):
        return [row for row in self.connections.list_tenant_installations(
            tenant_id, "twilio"
        ) if "twilio.sms.send" in set(row.get("enabled_capabilities") or ())]

    def _sms_connection(self, tenant_id):
        rows = self._connections(tenant_id)
        if not rows:
            raise CampaignStateConflict("a connected SMS-capable Twilio account is required")
        row = rows[0]
        sender = next((scope.split("twilio:sender:", 1)[1]
                       for scope in row.get("granted_scopes") or ()
                       if scope.startswith("twilio:sender:")), None)
        if not sender:
            raise CampaignStateConflict("the Twilio connection has no SMS sender")
        result = dict(row)
        result["sender"] = sender
        return result

    def _sms_address(self, tenant_id, contact_id):
        rows = [row for row in self.contacts.addresses(tenant_id, contact_id)
                if row["channel"] == "sms"]
        return next((row for row in rows if row.get("is_primary")), rows[0] if rows else None)

    def _utc_now(self):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(self.clock(), tz=timezone.utc)

    @staticmethod
    def _serialize(campaign, preview=None, report=None):
        definition = campaign["definition"]
        value = {
            "campaignId": campaign["campaign_id"],
            "name": definition["content"].get("name") or "Campaign",
            "body": definition["content"]["body"],
            "purpose": definition["content"]["purpose"],
            "channel": "sms", "sender": definition["senders"]["sms"],
            "status": campaign["status"],
            "startsAt": definition["schedule"]["starts_at"],
            "createdAt": campaign["created_at"],
            "estimatedSpendMicros": campaign["estimated_spend_micros"],
        }
        if preview is not None:
            value["preview"] = preview
        if report is not None:
            value["audienceTotal"] = report["audience_total"]
            value["outcomes"] = report["outcomes"]
        return value
