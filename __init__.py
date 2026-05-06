"""Directory-plugin entry shim.

Hermes Agent's directory-plugin loader imports
``<plugin-dir>/__init__.py`` directly (see ``hermes_cli/plugins.py``'s
``_load_directory_module``). Sekurvia uses a ``src/`` package layout, so
this shim makes the repo root importable as the plugin while keeping the
wheel/entry-point install path (`hermes_agent.plugins` in
``pyproject.toml``) unchanged.

This file is excluded from the built wheel by ``pyproject.toml``'s
``[tool.setuptools.packages.find]`` configuration (``where = ["src"]``);
it ships only in the source tree / git checkout.

Do not delete: removing this breaks ``git clone … ~/.hermes/plugins/sekurvia``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sekurvia import register  # noqa: E402  (sys.path setup before import)

__all__ = ["register"]
