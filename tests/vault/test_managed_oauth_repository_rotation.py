import inspect

from vault.repository import VaultRepository


def test_rotation_compare_and_swap_is_bound_to_the_repository_instance():
    repository = object.__new__(VaultRepository)

    assert list(inspect.signature(
        repository.compare_and_swap_managed_oauth_envelope
    ).parameters) == [
        "credential_id", "expected_version", "envelope", "granted_scopes",
    ]
