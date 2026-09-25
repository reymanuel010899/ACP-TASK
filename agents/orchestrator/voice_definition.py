"""Immutable, exactly approvable definition of one voice conversation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass


_PINNED_MODEL = re.compile(r"^grok-voice-[0-9]{4}-[0-9]{2}-[0-9]{2}$")


@dataclass(frozen=True)
class VoiceDefinition:
    persona_id: str
    persona_version: str
    model: str
    voice: str
    opening_script: str
    topic_policy_id: str
    topic_policy_version: str
    maximum_duration_seconds: int
    transfer_policy_id: str
    transfer_policy_version: str
    recording: bool

    @classmethod
    def from_mapping(cls, value):
        forbidden = {"to", "from", "destination", "contact_id", "address_id"}
        if forbidden.intersection(value):
            raise ValueError("a voice definition cannot contain a destination")
        required = tuple(cls.__dataclass_fields__)
        if set(value) != set(required):
            raise ValueError("voice definition fields must be exact")
        result = cls(**{name: value[name] for name in required})
        for name in required:
            item = getattr(result, name)
            if name == "recording":
                if type(item) is not bool:
                    raise ValueError("recording must be boolean")
            elif name == "maximum_duration_seconds":
                if type(item) is not int or not 15 <= item <= 7200:
                    raise ValueError("maximum duration must be between 15 and 7200 seconds")
            elif not isinstance(item, str) or not item.strip():
                raise ValueError("voice definition strings cannot be empty")
        if not _PINNED_MODEL.match(result.model):
            raise ValueError("voice model must be pinned to a dated version")
        return result

    def as_dict(self):
        return asdict(self)

    @property
    def digest(self):
        canonical = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def assert_approved(self, expected_hash):
        if not isinstance(expected_hash, str) or expected_hash != self.digest:
            raise PermissionError("voice definition no longer matches its approval")

