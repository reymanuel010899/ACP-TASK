"""Tests for the AgentTrust A2A extension binding (RFC-0002).

Test-first: these tests define the contract for
``schemas/a2a-extension-descriptor.schema.json`` and the two example
documents in ``examples/``. The descriptor schema is JSON Schema draft-07
and references the core schemas (evidence, verification-result) via
relative ``$ref``s resolved with a filesystem-backed RefResolver.
"""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, RefResolver
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "schemas"
EXAMPLES_DIR = ROOT / "examples"

TRUST_EXTENSION_URI = "https://agenttrust.example/extensions/trust/v1"
DESCRIPTOR_PATH = SCHEMA_DIR / "a2a-extension-descriptor.schema.json"
AGENT_CARD_PATH = EXAMPLES_DIR / "agent-card-with-extension.json"
TASK_MESSAGE_PATH = EXAMPLES_DIR / "task-message-with-evidence.json"


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def load_json(path):
    with open(path) as f:
        return json.load(f)


def build_store():
    """Map every schema's $id to its document so $refs resolve offline."""
    store = {}
    for path in SCHEMA_DIR.glob("*.schema.json"):
        schema = load_json(path)
        store[schema["$id"]] = schema
    return store


@pytest.fixture(scope="module")
def descriptor():
    return load_json(DESCRIPTOR_PATH)


# NOTE: the resolver and validators are function-scoped on purpose.
# jsonschema's Draft7Validator.validate() stops iterating errors early
# (best_match), which can leave $id scopes pushed on a shared RefResolver
# and corrupt later resolutions; a fresh resolver per test avoids that.
@pytest.fixture
def resolver(descriptor):
    return RefResolver(
        base_uri=descriptor["$id"], referrer=descriptor, store=build_store()
    )


@pytest.fixture
def descriptor_validator(descriptor, resolver):
    """Validator for the whole descriptor schema (root oneOf)."""
    return Draft7Validator(descriptor, resolver=resolver)


def definition_validator(descriptor, resolver, name):
    """Validator targeting one named definition inside the descriptor."""
    ref = {"$ref": descriptor["$id"] + "#/definitions/" + name}
    return Draft7Validator(ref, resolver=resolver)


@pytest.fixture
def agent_extension_validator(descriptor, resolver):
    return definition_validator(descriptor, resolver, "agentExtension")


@pytest.fixture
def trust_metadata_validator(descriptor, resolver):
    return definition_validator(descriptor, resolver, "trustMetadata")


@pytest.fixture(scope="module")
def agent_card():
    return load_json(AGENT_CARD_PATH)


@pytest.fixture(scope="module")
def task_message():
    return load_json(TASK_MESSAGE_PATH)


def find_trust_extension(card):
    """Return the AgentExtension entry declaring the trust extension."""
    for ext in card.get("capabilities", {}).get("extensions", []):
        if ext.get("uri") == TRUST_EXTENSION_URI:
            return ext
    return None


def extract_trust_metadata(message):
    """RFC-0002 extraction rule: the namespaced key in Message.metadata.

    Returns the trust metadata object, or None when the message carries no
    AgentTrust extension data (graceful-degradation path).
    """
    metadata = message.get("metadata")
    if not isinstance(metadata, dict):
        return None
    return metadata.get(TRUST_EXTENSION_URI)


def extract_evidence_status(message):
    payload = extract_trust_metadata(message)
    if payload is None:
        return None
    return payload.get("evidence_status")


def assert_plain_message_shape(message):
    """Structural sanity for the baseline A2A message fields we rely on."""
    assert message["kind"] == "message"
    assert isinstance(message["messageId"], str) and message["messageId"]
    assert message["role"] in ("user", "agent")
    assert isinstance(message["parts"], list) and message["parts"]
    for part in message["parts"]:
        assert isinstance(part, dict) and "kind" in part


# ---------------------------------------------------------------------------
# Descriptor schema is itself well-formed
# ---------------------------------------------------------------------------


class TestDescriptorSchema:
    def test_descriptor_file_exists(self):
        assert DESCRIPTOR_PATH.is_file()

    def test_descriptor_is_valid_draft7(self, descriptor):
        Draft7Validator.check_schema(descriptor)

    def test_descriptor_id_and_definitions(self, descriptor):
        assert descriptor["$id"] == (
            "https://agenttrust.example/schemas/a2a-extension-descriptor.schema.json"
        )
        assert "agentExtension" in descriptor["definitions"]
        assert "trustMetadata" in descriptor["definitions"]


# ---------------------------------------------------------------------------
# Happy path: Agent Card declares the extension
# ---------------------------------------------------------------------------


class TestAgentCardDeclaration:
    def test_card_has_a2a_required_fields(self, agent_card):
        # Structural sanity for the A2A Agent Card fields the binding relies on.
        assert isinstance(agent_card["name"], str) and agent_card["name"]
        assert agent_card["url"].startswith("https://")
        assert isinstance(agent_card["version"], str)
        assert isinstance(agent_card["protocolVersion"], str)
        capabilities = agent_card["capabilities"]
        assert isinstance(capabilities["extensions"], list)
        assert isinstance(agent_card["skills"], list) and agent_card["skills"]
        for skill in agent_card["skills"]:
            for field in ("id", "name", "description", "tags"):
                assert field in skill

    def test_card_declares_trust_extension(self, agent_card):
        entry = find_trust_extension(agent_card)
        assert entry is not None
        assert entry["uri"] == TRUST_EXTENSION_URI

    def test_extension_entry_validates_against_definition(
        self, agent_card, agent_extension_validator
    ):
        entry = find_trust_extension(agent_card)
        agent_extension_validator.validate(entry)

    def test_extension_entry_validates_against_root_schema(
        self, agent_card, descriptor_validator
    ):
        descriptor_validator.validate(find_trust_extension(agent_card))

    def test_extension_params_carry_binding_fields(self, agent_card):
        params = find_trust_extension(agent_card)["params"]
        assert isinstance(params["principal_id"], str) and params["principal_id"]
        assert params["verification_service_url"].startswith("https://")

    def test_entry_with_wrong_uri_rejected(
        self, agent_card, agent_extension_validator
    ):
        entry = copy.deepcopy(find_trust_extension(agent_card))
        entry["uri"] = "https://other.example/extensions/unrelated/v1"
        with pytest.raises(ValidationError):
            agent_extension_validator.validate(entry)

    def test_entry_missing_uri_rejected(self, agent_card, agent_extension_validator):
        entry = copy.deepcopy(find_trust_extension(agent_card))
        del entry["uri"]
        with pytest.raises(ValidationError):
            agent_extension_validator.validate(entry)


# ---------------------------------------------------------------------------
# Trust metadata payload on messages
# ---------------------------------------------------------------------------


class TestTrustMetadataPayload:
    def test_example_message_is_plain_valid_a2a_message(self, task_message):
        assert_plain_message_shape(task_message)

    def test_message_lists_extension_uri(self, task_message):
        # RFC-0002: a message carrying trust metadata MUST list the URI
        # in Message.extensions.
        assert TRUST_EXTENSION_URI in task_message["extensions"]

    def test_payload_validates_against_definition(
        self, task_message, trust_metadata_validator
    ):
        payload = extract_trust_metadata(task_message)
        assert payload is not None
        trust_metadata_validator.validate(payload)

    def test_payload_validates_against_root_schema(
        self, task_message, descriptor_validator
    ):
        descriptor_validator.validate(extract_trust_metadata(task_message))

    def test_payload_without_verification_result_is_valid(
        self, task_message, trust_metadata_validator
    ):
        payload = copy.deepcopy(extract_trust_metadata(task_message))
        payload.pop("verification_result", None)
        payload["evidence_status"] = "pending"
        trust_metadata_validator.validate(payload)

    def test_bad_evidence_status_rejected(self, task_message, trust_metadata_validator):
        payload = copy.deepcopy(extract_trust_metadata(task_message))
        payload["evidence_status"] = "maybe"
        with pytest.raises(ValidationError):
            trust_metadata_validator.validate(payload)

    def test_missing_evidence_rejected(self, task_message, trust_metadata_validator):
        payload = copy.deepcopy(extract_trust_metadata(task_message))
        del payload["evidence"]
        with pytest.raises(ValidationError):
            trust_metadata_validator.validate(payload)

    def test_ref_to_core_evidence_schema_is_enforced(
        self, task_message, trust_metadata_validator
    ):
        # Corrupt a core Evidence constraint (sha256 must be lowercase hex):
        # proves the $ref wiring into evidence.schema.json actually validates.
        payload = copy.deepcopy(extract_trust_metadata(task_message))
        hashes = payload["evidence"]["artifact_hashes"]
        assert hashes, "example evidence should carry at least one artifact hash"
        hashes[next(iter(hashes))] = "not-a-sha256"
        with pytest.raises(ValidationError):
            trust_metadata_validator.validate(payload)

    def test_ref_to_core_verification_result_schema_is_enforced(
        self, task_message, trust_metadata_validator
    ):
        payload = copy.deepcopy(extract_trust_metadata(task_message))
        assert "verification_result" in payload
        payload["verification_result"]["verdict"] = "unsure"
        with pytest.raises(ValidationError):
            trust_metadata_validator.validate(payload)

    def test_unknown_top_level_key_rejected(
        self, task_message, trust_metadata_validator
    ):
        payload = copy.deepcopy(extract_trust_metadata(task_message))
        payload["surprise"] = True
        with pytest.raises(ValidationError):
            trust_metadata_validator.validate(payload)


# ---------------------------------------------------------------------------
# Graceful degradation + integration: with vs. without extension data
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    def make_plain_message(self, task_message):
        """The same task result as the server sends it when the client did
        NOT opt in via the A2A-Extensions header: no trust metadata key,
        no trust URI in Message.extensions."""
        plain = copy.deepcopy(task_message)
        plain.get("metadata", {}).pop(TRUST_EXTENSION_URI, None)
        if not plain.get("metadata"):
            plain.pop("metadata", None)
        if "extensions" in plain:
            plain["extensions"] = [
                uri for uri in plain["extensions"] if uri != TRUST_EXTENSION_URI
            ]
            if not plain["extensions"]:
                del plain["extensions"]
        return plain

    def test_plain_message_still_valid_a2a_shape(self, task_message):
        # Edge: a client that never sent A2A-Extensions gets a response with
        # no extension data, and that response is still a valid A2A message.
        plain = self.make_plain_message(task_message)
        assert_plain_message_shape(plain)
        assert extract_trust_metadata(plain) is None

    def test_status_extraction_distinguishes_messages(self, task_message):
        # Integration: evidence_status is extractable from the enriched
        # message and absent (None) from the degraded one.
        plain = self.make_plain_message(task_message)
        assert extract_evidence_status(task_message) == "verified"
        assert extract_evidence_status(plain) is None
        assert extract_evidence_status(task_message) != extract_evidence_status(plain)

    def test_message_without_metadata_field_at_all(self):
        message = {
            "kind": "message",
            "messageId": "msg-000",
            "role": "agent",
            "parts": [{"kind": "text", "text": "done"}],
        }
        assert_plain_message_shape(message)
        assert extract_evidence_status(message) is None

    def test_verified_status_comes_from_example_payload(
        self, task_message, trust_metadata_validator
    ):
        payload = extract_trust_metadata(task_message)
        trust_metadata_validator.validate(payload)
        assert payload["evidence_status"] == "verified"
        assert payload["verification_result"]["verdict"] == "verified"
        # The evidence and the verdict chain by evidence_id.
        assert (
            payload["verification_result"]["evidence_id"]
            == payload["evidence"]["evidence_id"]
        )
