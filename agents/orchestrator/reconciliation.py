"""Narrow reconciliation for provider calls with an ambiguous outcome."""


def reconcile_unknown_action(repository, binding, provider_lookup, now_ts):
    proposal = repository.get_by_idempotency_key(binding["idempotency_key"])
    if proposal is None or proposal.get("status") != "execution_unknown":
        return {"status": "not_unknown"}
    receipt = provider_lookup(binding)
    if not isinstance(receipt, dict):
        return {"status": "execution_unknown", "requires_resolution": True}
    repository.complete_execution(
        proposal["proposal_id"], proposal["version"], receipt, now_ts
    )
    return {"status": "completed", "receipt": receipt}
