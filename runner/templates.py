"""Runtime templates for the runner (U2).

A template maps a managed agent definition to a REAL runnable process. It
declares the capability the process actually executes and builds the launch
argv (a list, never a shell string -- KTD5/R9: the template controls the
executable, and only validated numeric config from the definition reaches the
command). MVP ships one template, ``terraform-provider``, wrapping
``agents.provider.agent`` (which really implements ``terraform.generate``).
"""

import sys


class Template(object):
    def __init__(self, key, label, capability, module):
        # type: (str, str, str, str) -> None
        self.key = key
        self.label = label
        self.capability = capability
        self.module = module


TEMPLATES = {
    "terraform-provider": Template(
        key="terraform-provider",
        label="Terraform Provider",
        capability="terraform.generate",
        module="agents.provider.agent",
    ),
}


def get_template(key):
    # type: (str) -> Template
    return TEMPLATES.get(key)


def _validate_price(value, field):
    # type: (object, str) -> float
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s must be a number" % field)
    if value < 0:
        raise ValueError("%s must be non-negative" % field)
    return float(value)


def build_command(definition, port, api_key, registry_url, verification_url):
    # type: (dict, int, str, str, str) -> list
    """Build the argv to launch ``definition``'s template process.

    Raises ``ValueError`` on an unknown template or invalid pricing. Prices are
    validated numerics; the executable/module comes from the template, so no
    raw user string is ever interpolated into a shell (R9).
    """
    template = get_template(definition.get("template"))
    if template is None:
        raise ValueError("unknown template: %r" % definition.get("template"))
    if not isinstance(port, int) or port <= 0:
        raise ValueError("port must be a positive int")

    list_price = _validate_price(definition.get("list_price"), "list_price")
    min_price = _validate_price(definition.get("min_price"), "min_price")
    if list_price is not None and min_price is not None and min_price > list_price:
        raise ValueError("min_price must not exceed list_price")

    argv = [
        sys.executable,
        "-m",
        template.module,
        "--port",
        str(port),
        "--registry-url",
        registry_url,
        "--verification-url",
        verification_url,
        "--api-key",
        api_key,
        "--keys-dir",
        definition["keys_dir"],
    ]
    if list_price is not None:
        argv += ["--list-price", str(list_price)]
    if min_price is not None:
        argv += ["--min-price", str(min_price)]
    return argv
