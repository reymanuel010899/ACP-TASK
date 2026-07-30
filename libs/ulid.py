"""Minimal, dependency-free ULID generator (KTD4, unit U2).

Every *new* surrogate key this database architecture introduces (identity's
``key_id``/``team_id``, and later units' credential/task/grant/audit-entry
ids) uses a ULID rather than a random UUID4: a ULID's leading 48 bits are a
millisecond timestamp, so lexicographic/string sort order matches insertion
order and inserts land at the append-heavy right edge of a B-tree primary-key
index instead of a random point (the page-split problem UUID4 causes at
volume -- see ``docs/architecture/database-design.md`` Section 1).

Not used for ``principal_id`` (ed25519-derived) or ``capability_id``
(dot-namespaced string) -- both keep their existing natural string identity,
per KTD4.

This is a small hand-rolled encoder, not a new pip dependency (matching this
codebase's 100%-stdlib convention, KTD1) -- a full ULID library would pull in
a package for ~15 lines of Crockford-base32 encoding.
"""

import os
import time

from typing import Optional

#: Crockford's base32 alphabet: excludes I, L, O, U to avoid visual
#: ambiguity/accidental profanity -- the standard ULID encoding alphabet.
_CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

#: A ULID is 128 bits (48-bit timestamp + 80-bit randomness) rendered as 26
#: base32 characters (26 * 5 = 130 bits -- the top 2 bits of the first
#: character are always 0 since 128 < 130).
_ULID_LENGTH = 26
_TIMESTAMP_BITS = 48
_RANDOMNESS_BITS = 80


def generate_ulid(now_ms=None, random_bytes=None):
    # type: (Optional[int], Optional[bytes]) -> str
    """Return a new 26-character Crockford-base32-encoded ULID.

    ``now_ms`` and ``random_bytes`` are injectable for deterministic tests;
    real callers omit both and get the current wall clock (milliseconds
    since the Unix epoch) plus ``os.urandom``.
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    if random_bytes is None:
        random_bytes = os.urandom(_RANDOMNESS_BITS // 8)

    timestamp_part = now_ms & ((1 << _TIMESTAMP_BITS) - 1)
    randomness_part = int.from_bytes(random_bytes, "big") & ((1 << _RANDOMNESS_BITS) - 1)
    value = (timestamp_part << _RANDOMNESS_BITS) | randomness_part

    chars = ["0"] * _ULID_LENGTH
    for i in range(_ULID_LENGTH - 1, -1, -1):
        chars[i] = _CROCKFORD_ALPHABET[value & 0x1F]
        value >>= 5
    return "".join(chars)
