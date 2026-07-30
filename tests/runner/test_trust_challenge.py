"""Signature challenge: proof-of-possession primitives + provider responder."""

import base64
import hashlib

import nacl.signing

from runner.trust_challenge import (
    principal_matches_pubkey,
    prove_identity,
    verify_signature,
)


def _keypair():
    sk = nacl.signing.SigningKey.generate()
    pub = base64.b64encode(bytes(sk.verify_key)).decode("ascii")
    principal = "atp:principal:x:" + hashlib.sha256(pub.encode("ascii")).hexdigest()[:16]
    return sk, pub, principal


def test_principal_binding_accepts_the_matching_key():
    _, pub, principal = _keypair()
    assert principal_matches_pubkey(principal, pub) is True


def test_principal_binding_rejects_a_different_key():
    _, pub, principal = _keypair()
    _, other_pub, _ = _keypair()
    assert principal_matches_pubkey(principal, other_pub) is False


def test_principal_binding_supports_the_raw_pubkey_form():
    _, pub, _ = _keypair()
    assert principal_matches_pubkey(pub, pub) is True  # user-register convention


def test_verify_signature_accepts_a_genuine_signature():
    sk, pub, _ = _keypair()
    nonce = "abc123"
    sig = base64.b64encode(sk.sign(nonce.encode("utf-8")).signature).decode("ascii")
    assert verify_signature(pub, nonce, sig) is True


def test_verify_signature_rejects_a_tampered_nonce():
    sk, pub, _ = _keypair()
    sig = base64.b64encode(sk.sign(b"abc123").signature).decode("ascii")
    assert verify_signature(pub, "DIFFERENT", sig) is False


def test_verify_signature_rejects_garbage():
    _, pub, _ = _keypair()
    assert verify_signature(pub, "n", "not-base64!!") is False


def test_prove_identity_is_false_for_an_unreachable_agent():
    assert prove_identity("http://127.0.0.1:1", "atp:principal:x:deadbeefdeadbeef") is False


# -- the provider actually answers the challenge correctly -------------------


def test_provider_signs_the_challenge_and_the_proof_verifies():
    from agents.provider.agent import ProviderAgent

    agent = ProviderAgent(base_url="http://127.0.0.1:9999",
                          verification_url="http://127.0.0.1:8080")
    nonce = "nonce-under-test"
    proof = agent.handle_payload({"type": "trust.challenge", "nonce": nonce})

    assert proof["type"] == "trust.proof"
    # the proof is self-consistent: key hashes to the declared principal_id,
    # and the signature over the nonce validates against that key
    assert principal_matches_pubkey(proof["principal_id"], proof["public_key"])
    assert verify_signature(proof["public_key"], nonce, proof["signature"])
    assert proof["principal_id"] == agent.principal_id
