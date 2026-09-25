"""Launch the action broker without executing its module as ``__main__``.

``python -m services.action_broker.app`` imports that module twice under two
names (``__main__`` and ``services.action_broker.app``, the latter pulled in by
``services.action_broker.composition``), so the broker the factory builds is an
instance of a *different* ``ActionBroker`` class than the one ``main()``
isinstance-checks. Importing it here keeps a single class object.
"""

from services.action_broker.app import main

if __name__ == "__main__":
    main()
