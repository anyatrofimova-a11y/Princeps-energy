"""Princeps Magritte connector source modules.

Each module under this package defines one or more :class:`Connector`
subclasses decorated with ``@register_class``. They self-register at
import time; :func:`app.connectors.startup.register_all_connectors`
walks this package on app launch and hydrates ``princeps_datasets``.
"""
