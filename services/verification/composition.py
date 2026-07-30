"""Production receipt-verifier composition over a credential-isolated gateway."""

import importlib
import os

from services.verification.verifiers.google import GoogleReceiptVerifier
from services.verification.verifiers.slack import SlackReceiptVerifier


def build_receipt_verifiers():
    path = os.environ.get("TESSERA_PROVIDER_RECEIPT_GATEWAY_FACTORY")
    if not path or ":" not in path:
        raise RuntimeError(
            "TESSERA_PROVIDER_RECEIPT_GATEWAY_FACTORY=module:function is required"
        )
    module_name, factory_name = path.split(":", 1)
    factory = getattr(importlib.import_module(module_name), factory_name)
    gateway = factory()
    if not hasattr(gateway, "read_receipt"):
        raise TypeError("provider receipt gateway must implement read_receipt")
    return {
        "google": GoogleReceiptVerifier(gateway),
        "slack": SlackReceiptVerifier(gateway),
    }
