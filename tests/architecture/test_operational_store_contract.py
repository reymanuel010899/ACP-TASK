"""Characterization contract for production SQLite retirement.

This test is intentionally strict while U3 is active: adding a new SQLite
module or local-database production default requires an explicit migration
mapping in the same change. U7 will invert the assertions and require the
production sets to be empty.
"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
MAPPING = ROOT / "docs/architecture/operational-state-mapping.md"
INVENTORY = ROOT / "docs/architecture/current-state-inventory.md"

EXPECTED_SQLITE_MODULES = {
    "agents/orchestrator/action_repository.py",
    "agents/orchestrator/campaign_repository.py",
    "agents/orchestrator/conversation_state.py",
    "agents/orchestrator/dispatch_ledger.py",
    "agents/orchestrator/workflow_repository.py",
    "libs/spend_ledger.py",
    "libs/twilio_events.py",
    "libs/whatsapp_state.py",
    "services/action_broker/rate_limits.py",
    "services/oauth/repository.py",
    "services/session/repository.py",
    "services/voice_bridge/app.py",
}

EXPECTED_PRODUCTION_DEFAULTS = {
    "ACTION_DATABASE",
    "CAMPAIGN_DATABASE",
    "OAUTH_DATABASE",
    "SESSION_DATABASE",
    "TWILIO_EVENT_DATABASE",
    "VOICE_TRANSCRIPT_DATABASE",
    "WORKFLOW_DATABASE",
}

SEARCH_ROOTS = ("agents", "libs", "services", "web", "scripts")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _python_files():
    for root_name in SEARCH_ROOTS:
        root = ROOT / root_name
        if root.exists():
            yield from root.rglob("*.py")


def _sqlite_modules() -> set[str]:
    modules = set()
    for path in _python_files():
        source = _text(path)
        if re.search(r"(?:^|\n)(?:import sqlite3|from sqlite3\b)", source):
            modules.add(path.relative_to(ROOT).as_posix())
    return modules


def _local_database_defaults() -> set[str]:
    defaults = set()
    pattern = re.compile(
        r'(?:get\(|\[)["\']([A-Z][A-Z0-9_]*DATABASE(?:_PATH)?)["\']'
        r"[^\n]{0,100}?[\"'](?:tessera-[^\"']+\.db|[^\"']+\.db)[\"']"
    )
    for path in _python_files():
        for match in pattern.finditer(_text(path)):
            defaults.add(match.group(1))
    return defaults


def test_current_sqlite_production_surface_is_frozen_and_mapped():
    mapping = _text(MAPPING)
    inventory = _text(INVENTORY)
    discovered = _sqlite_modules()

    assert discovered == EXPECTED_SQLITE_MODULES
    for module in sorted(discovered):
        assert f"`{module}`" in mapping
        assert f"`{module}`" in inventory


def test_current_local_database_defaults_are_frozen_and_have_cutover_targets():
    mapping = _text(MAPPING)
    discovered = _local_database_defaults()

    assert discovered == EXPECTED_PRODUCTION_DEFAULTS
    for variable in sorted(discovered):
        assert variable in mapping


def test_mapping_declares_fail_closed_ownership_and_one_way_authority():
    mapping = _text(MAPPING)

    assert "never inferred" in mapping
    assert "quarantined" in mapping
    assert "postgres_authoritative" in mapping
    assert "stale SQLite is never" in mapping
    assert "app.current_org_id" not in mapping or "tenant-bound" in mapping

