"""Characterization guards for the consolidation architecture baseline.

These tests intentionally inspect repository configuration and documentation.
They make new deployables, SQLite production stores, or accidental public
contract drift visible in the same change that introduces them.
"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs/architecture/current-state-inventory.md"
TARGET = ROOT / "docs/architecture/target-architecture.md"
COMPATIBILITY = ROOT / "docs/architecture/compatibility-contract.md"
STRATEGY = ROOT / "STRATEGY.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _dev_stack_services() -> set[str]:
    script = _text(ROOT / "scripts/dev-stack.sh")
    return set(re.findall(r'"([a-z_]+):\d+"', script))


def _production_sqlite_modules() -> set[str]:
    modules: set[str] = set()
    excluded_roots = {"tests"}
    for path in ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT)
        if relative.parts[0] in excluded_roots or any(
            part.startswith(".") for part in relative.parts
        ):
            continue
        source = _text(path)
        if re.search(r"(?:^|\n)(?:import sqlite3|from sqlite3\b)", source):
            modules.add(relative.as_posix())
    return modules


def test_authoritative_architecture_documents_exist_and_are_linked():
    for path in (STRATEGY, INVENTORY, TARGET, COMPATIBILITY):
        assert path.is_file(), f"missing architecture baseline: {path}"

    readme = _text(ROOT / "README.md")
    for relative in (
        "STRATEGY.md",
        "docs/architecture/current-state-inventory.md",
        "docs/architecture/target-architecture.md",
        "docs/architecture/compatibility-contract.md",
    ):
        assert relative in readme
        assert (ROOT / relative).exists()


def test_every_local_stack_process_is_documented():
    inventory = _text(INVENTORY)
    services = _dev_stack_services()

    assert services == {
        "registry",
        "vault",
        "verification",
        "runner",
        "session",
        "oauth",
        "action_broker",
        "concierge",
        "workflow_worker",
        "twilio_webhook",
        "frontend",
        "voice_bridge",
        "campaign_worker",
    }
    for service in services:
        assert f"`{service}`" in inventory, (
            f"scripts/dev-stack.sh starts {service!r}, but the current-state "
            "inventory does not classify it"
        )


def test_every_production_sqlite_module_is_declared_as_migration_work():
    inventory = _text(INVENTORY)
    modules = _production_sqlite_modules()

    assert modules, "characterization unexpectedly found no SQLite modules"
    for module in modules:
        assert f"`{module}`" in inventory, (
            f"{module} imports sqlite3 but is missing from the durable-store "
            "inventory; document or replace it in the same change"
        )


def test_strategy_and_target_preserve_the_open_agent_network_boundary():
    strategy = _text(STRATEGY)
    target = _text(TARGET)

    for framework in ("Eve", "n8n", "Python"):
        assert framework in strategy
    for boundary in ("Protocol", "Network", "Orchestrator", "Console", "Vertical applications"):
        assert boundary in strategy
        assert boundary in target

    assert "ProviderCompleted" in target
    assert "Only `Verified` is a trusted success" in target
    assert "PostgreSQL is the only production source of truth" in target


def test_public_a2a_and_trust_contracts_are_frozen_explicitly():
    contract = _text(COMPATIBILITY)

    assert "https://treessera.com/extensions/trust/v1" in contract
    assert "/.well-known/agent-card.json" in contract
    assert "task.request" in contract
    assert "task.offer" in contract
    assert "task.accept" in contract
    assert "plain A2A" in contract
    assert "schema `$id`" in contract


def test_previous_database_proposal_is_clearly_superseded():
    database_design = _text(ROOT / "docs/architecture/database-design.md")

    assert "status: superseded" in database_design
    assert "superseded_by: docs/architecture/target-architecture.md" in database_design
    assert "current-state-inventory.md" in database_design


def test_tenant_contract_separates_public_discovery_from_private_control():
    target = _text(TARGET)
    contract = _text(COMPATIBILITY)

    assert "`app.current_org_id`" in target
    assert "fail closed" in target
    assert "Public Agent Cards and capability discovery" in target
    assert "agent ownership" in target.lower()
    assert "administrative quarantine" in target

    assert "Public registry data" in contract
    assert "Tenant-private registry data" in contract
    assert "does not require tenant context" in contract
    assert "must require tenant context" in contract
