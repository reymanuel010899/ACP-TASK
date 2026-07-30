# SDK

The Tessera SDK no longer lives in this monorepo. It has its own repository and
is published on PyPI.

- **Repository:** https://github.com/reymanuel010899/treessera-python
- **PyPI:** https://pypi.org/project/treessera/
- **Install:** `pip install treessera`

The SDK is fully self-contained (only depends on `pynacl`) and imports nothing
from this monorepo, which is why it lives on its own. The one value it shares
with the backend is the trust-extension URI — kept in sync via
`libs/config.py` here (env var `TREESSERA_URI`) and `treessera/config.py` in the
SDK repo. Both must resolve to the same URI for agents to interoperate.

Its history before the split is preserved in this repo's git log (search for
commits touching `sdk/python`).
