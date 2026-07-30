"""Connect existing (BYO) agents — the vision path.

An externally hosted agent (someone else's process, on their own domain/cloud)
joins the marketplace by URL: the runner fetches its published agent card
server-side (no browser CORS), validates it declares the AgentTrust trust
extension, registers it into the registry so requesters discover it, and then
just health-checks its endpoint. The runner never launches it.
"""

import hashlib
import json
import urllib.error
import urllib.request

from libs.config import TRUST_EXTENSION_URI as TRUST_URI
from runner.trust_challenge import prove_identity

_CARD_PATH = "/.well-known/agent-card.json"

# Some hosts/CDNs reject the default `Python-urllib/x.y` agent with 403, so
# identify ourselves like a normal client.
_HEADERS = {
    "User-Agent": "AgentTrust-Console/1.0 (agent-card-fetch)",
    "Accept": "application/json, */*",
}


class ConnectError(Exception):
    """A connect attempt failed for a user-actionable reason."""


def _normalize(endpoint_url):
    # type: (str) -> str
    return (endpoint_url or "").strip().rstrip("/")


def card_url_for(endpoint_url):
    # type: (str) -> str
    """Where the card lives. Accepts EITHER the agent's base URL or the full
    card URL — pasting the card URL must not append the well-known path twice."""
    base = _normalize(endpoint_url)
    if base.endswith(_CARD_PATH) or base.endswith(".json"):
        return base
    return base + _CARD_PATH


def base_url_for(endpoint_url):
    # type: (str) -> str
    """The agent's base URL, given either form."""
    base = _normalize(endpoint_url)
    if base.endswith(_CARD_PATH):
        return base[: -len(_CARD_PATH)]
    if base.endswith(".json"):
        return base.rsplit("/", 1)[0]
    return base


def fetch_card(endpoint_url, timeout=5.0):
    # type: (str, float) -> dict
    base = _normalize(endpoint_url)
    if not (base.startswith("http://") or base.startswith("https://")):
        raise ConnectError("endpoint_url must start with http:// or https://")
    target = card_url_for(base)
    request = urllib.request.Request(target, headers=_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            if resp.status != 200:
                raise ConnectError("agent returned HTTP %s for its card" % resp.status)
            raw = resp.read().decode("utf-8")
    except ConnectError:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise ConnectError(
                "the host refused the request (403 Forbidden) at %s — it may block "
                "automated clients or require authentication" % target)
        if exc.code == 404:
            raise ConnectError("no agent card found at %s (404)" % target)
        raise ConnectError("the agent card request failed (HTTP %s) at %s"
                           % (exc.code, target))
    except Exception as exc:
        raise ConnectError("could not reach the agent card at %s: %s" % (target, exc))
    try:
        card = json.loads(raw)
    except ValueError:
        raise ConnectError("the response at %s is not valid JSON" % target)
    if not isinstance(card, dict):
        raise ConnectError("the agent card is not a JSON object")
    return card


def card_declares_trust(card):
    # type: (dict) -> bool
    caps = card.get("capabilities") or {}
    for ext in (caps.get("extensions") or []):
        if isinstance(ext, dict) and ext.get("uri") == TRUST_URI:
            return True
    return False


def extract_principal(card):
    # type: (dict) -> str
    caps = card.get("capabilities") or {}
    for ext in (caps.get("extensions") or []):
        params = (ext or {}).get("params") or {}
        pid = params.get("principal_id")
        if isinstance(pid, str) and pid:
            return pid
    return None


def extract_capabilities(card):
    # type: (dict) -> list
    skills = card.get("skills")
    if isinstance(skills, list):
        ids = [s.get("id") for s in skills if isinstance(s, dict) and s.get("id")]
        if ids:
            return ids
    caps = card.get("capabilities")
    if isinstance(caps, list):
        return [c for c in caps if isinstance(c, str) and c]
    return []


def inspect(endpoint_url, timeout=5.0):
    # type: (str, float) -> dict
    """Fetch + validate an external agent card; return the detected fields.
    Raises ConnectError with an actionable message on any problem."""
    card = fetch_card(endpoint_url, timeout=timeout)

    # Trust tier. The distinction is not just about identity — it is about what
    # you can actually DO with the agent:
    #   verified -> TRANSACTABLE. Declares this extension, so it speaks the
    #               negotiation vocabulary (task.request/offer/accept), can
    #               deliver evidence, and accrues provable reputation.
    #   basic    -> DISCOVERY ONLY. A plain A2A agent, OR one that claims an
    #               identity it cannot PROVE (see below). Reachable and listed,
    #               but no negotiation and no verifiable result. The marketplace
    #               assigns it a stable identifier it holds no keys for.
    #
    # `verified` is a PROOF, not a claim: a card that declares the extension is
    # only trusted after it signs a fresh nonce with the private key for the
    # principal_id it declares (proof of possession). A copied principal_id
    # can't pass — the attacker can't sign for a key it doesn't hold. Anything
    # that fails the challenge is downgraded to `basic` (proof = "unproven"),
    # and its stolen/unproven claim is discarded in favour of an assigned id.
    claimed = extract_principal(card)
    callable_url = card.get("url") or base_url_for(endpoint_url)
    claims_trust = card_declares_trust(card) and bool(claimed)
    if claims_trust and prove_identity(callable_url, claimed):
        trust_tier = "verified"
        principal_id = claimed
        proof = "proven"
    else:
        trust_tier = "basic"
        principal_id = derive_unverified_principal(endpoint_url)
        proof = "unproven" if claims_trust else "none"

    # Capabilities may legitimately be empty here: many external agents don't
    # publish skills in this marketplace's vocabulary, so the operator declares
    # them at connect time (merged into the published card by merge_skills).
    capabilities = extract_capabilities(card)
    return {
        "card": card,
        "name": card.get("name") or "Connected agent",
        "description": card.get("description") or "",
        "version": card.get("version") or "0.1.0",
        "url": card.get("url") or base_url_for(endpoint_url),
        # Where the card actually lives. The card's own `url` is the callable
        # (often JSON-RPC) endpoint and is NOT where the well-known card sits,
        # so health checks must use this instead.
        "card_url": card_url_for(endpoint_url),
        "principal_id": principal_id,
        "trust_tier": trust_tier,
        # proven = signed the challenge; unproven = claimed the extension but
        # failed to; none = never claimed it.
        "proof": proof,
        "capabilities": capabilities,
    }


UNVERIFIED_PREFIX = "atp:principal:unverified:"


def derive_unverified_principal(endpoint_url):
    # type: (str) -> str
    """A stable identifier for an agent that does NOT hold an AgentTrust
    identity (tier "basic").

    Deliberately NOT a keypair: the marketplace must never hold a private key
    that could sign as someone else's agent. This is a deterministic label
    derived from the endpoint, so reconnecting the same agent reuses the same
    id, and the ``unverified:`` namespace makes the weaker guarantee legible.
    """
    base = base_url_for(endpoint_url)
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
    return UNVERIFIED_PREFIX + digest


def ensure_trust_extension(card, principal_id, attested):
    # type: (dict, str, bool) -> dict
    """Return a copy of ``card`` that declares the trust extension.

    The registry requires it. When ``attested`` is true the identity was
    assigned by the marketplace rather than self-asserted by the agent, and the
    published card says so explicitly — a reader of the registry can tell the
    two apart.
    """
    merged = dict(card)
    caps = dict(merged.get("capabilities") or {})
    exts = [e for e in (caps.get("extensions") or []) if isinstance(e, dict)]
    if not any(e.get("uri") == TRUST_URI for e in exts):
        params = {"principal_id": principal_id}
        if attested:
            params["self_asserted"] = False
            params["attested_by"] = "marketplace"
            # An agent that never declared this extension does not speak the
            # negotiation vocabulary (task.request/offer/accept), so it is
            # listed for DISCOVERY but cannot be transacted with. Machine
            # readable so requesters can filter, not just UI copy.
            params["transactable"] = False
        exts = exts + [{"uri": TRUST_URI, "required": False, "params": params}]
    caps["extensions"] = exts
    merged["capabilities"] = caps
    return merged


def merge_skills(card, capability_ids):
    # type: (dict, list) -> dict
    """Return a copy of ``card`` whose ``skills`` cover ``capability_ids``.

    The registry indexes a card's declared capabilities off ``skills[].id``, so
    operator-declared capabilities must land IN the published card — otherwise
    the agent would not be discoverable by them. Existing skill entries are
    preserved; missing ids are appended.
    """
    merged = dict(card)
    skills = [s for s in (card.get("skills") or []) if isinstance(s, dict)]
    present = {s.get("id") for s in skills}
    for cap_id in capability_ids:
        if cap_id and cap_id not in present:
            skills.append({"id": cap_id, "name": cap_id})
            present.add(cap_id)
    merged["skills"] = skills
    return merged


def register_external(registry_url, card, principal_id, api_key, timeout=5.0):
    # type: (str, dict, str, str, float) -> None
    """Publish the external agent's card to the registry so requesters can
    discover it. Raises ConnectError on a registry rejection."""
    body = json.dumps({
        "agent_card": card,
        "principal_id": principal_id,
        "api_key": api_key,
    }).encode("utf-8")
    req = urllib.request.Request(
        registry_url.rstrip("/") + "/register", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                raise ConnectError("registry rejected the agent (HTTP %s)" % resp.status)
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            return  # already registered -> treat as success
        raise ConnectError("registry rejected the agent (HTTP %s)" % exc.code)
    except ConnectError:
        raise
    except Exception as exc:
        raise ConnectError("could not reach the registry: %s" % exc)


def health_check(endpoint_url, timeout=3.0):
    # type: (str, float) -> bool
    try:
        fetch_card(endpoint_url, timeout=timeout)
        return True
    except Exception:
        return False
