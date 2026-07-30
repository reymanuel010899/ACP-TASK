"""U2: template registry + launch-command builder."""

import sys

import pytest

from runner.templates import build_command, get_template


def _defn(**over):
    base = {
        "id": "agt_x",
        "template": "terraform-provider",
        "keys_dir": "/tmp/agt_x/keys",
        "list_price": 9,
        "min_price": 8,
    }
    base.update(over)
    return base


def test_terraform_template_declares_real_capability():
    tpl = get_template("terraform-provider")
    assert tpl is not None
    assert tpl.capability == "terraform.generate"


def test_build_command_emits_expected_argv():
    argv = build_command(_defn(), 8100, "KEY",
                         "http://reg", "http://ver")
    assert argv[0] == sys.executable
    assert argv[1:3] == ["-m", "agents.provider.agent"]
    assert "--port" in argv and "8100" in argv
    assert "--api-key" in argv and "KEY" in argv
    assert "--keys-dir" in argv and "/tmp/agt_x/keys" in argv
    assert "--list-price" in argv and "--min-price" in argv
    # argv is a list of strings -> no shell interpolation (R9)
    assert all(isinstance(a, str) for a in argv)


def test_unknown_template_raises():
    with pytest.raises(ValueError):
        build_command(_defn(template="nope"), 8100, "K", "r", "v")


def test_min_above_list_raises():
    with pytest.raises(ValueError):
        build_command(_defn(list_price=3, min_price=9), 8100, "K", "r", "v")


def test_non_numeric_price_raises():
    with pytest.raises(ValueError):
        build_command(_defn(list_price="cheap"), 8100, "K", "r", "v")


def test_prices_optional():
    argv = build_command(_defn(list_price=None, min_price=None), 8100, "K", "r", "v")
    assert "--list-price" not in argv and "--min-price" not in argv
