"""Regression test for the directory-plugin install path.

Hermes Agent's ``hermes_cli/plugins.py::_load_directory_module`` imports
``<plugin-dir>/__init__.py`` directly via
``importlib.util.spec_from_file_location``. Without the root shim,
``git clone … ~/.hermes/plugins/sekurvia`` would fail with
``No __init__.py in <plugindir>`` because Sekurvia's real package lives
under ``src/sekurvia/``.

This test simulates that loader path exactly and asserts the loaded
module exposes a callable ``register`` symbol — same contract as the
wheel-installed entry-point.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIM_PATH = REPO_ROOT / "__init__.py"
_FAKE_MODULE_NAME = "hermes_plugins_test.sekurvia_dir_load"


def test_root_shim_exists() -> None:
    assert SHIM_PATH.is_file(), (
        f"directory-plugin shim missing at {SHIM_PATH}; "
        "without it, `git clone … ~/.hermes/plugins/sekurvia` fails."
    )


def test_directory_loader_finds_register() -> None:
    """Mirror :func:`hermes_cli.plugins.PluginManager._load_directory_module`."""
    # Make sure stale state from prior runs can't satisfy the import.
    sys.modules.pop(_FAKE_MODULE_NAME, None)

    spec = importlib.util.spec_from_file_location(
        _FAKE_MODULE_NAME,
        SHIM_PATH,
        submodule_search_locations=[str(REPO_ROOT)],
    )
    assert spec is not None, "spec_from_file_location returned None"
    assert spec.loader is not None, "spec has no loader"

    module = importlib.util.module_from_spec(spec)
    sys.modules[_FAKE_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
        assert hasattr(module, "register"), "shim does not expose `register`"
        assert callable(module.register), "`register` must be callable"
    finally:
        sys.modules.pop(_FAKE_MODULE_NAME, None)


def test_shim_register_is_real_register() -> None:
    """The shim must hand back the same function the wheel install would."""
    sys.modules.pop(_FAKE_MODULE_NAME, None)

    spec = importlib.util.spec_from_file_location(
        _FAKE_MODULE_NAME,
        SHIM_PATH,
        submodule_search_locations=[str(REPO_ROOT)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_FAKE_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
        from sekurvia import register as wheel_register

        assert module.register is wheel_register
    finally:
        sys.modules.pop(_FAKE_MODULE_NAME, None)


def test_shim_register_wires_a_tool() -> None:
    """Smoke-test register(ctx) through the shim with a fake PluginContext."""
    sys.modules.pop(_FAKE_MODULE_NAME, None)

    spec = importlib.util.spec_from_file_location(
        _FAKE_MODULE_NAME,
        SHIM_PATH,
        submodule_search_locations=[str(REPO_ROOT)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_FAKE_MODULE_NAME] = module

    class _FakeCtx:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def register_tool(self, **kwargs) -> None:
            self.calls.append(kwargs)

    try:
        spec.loader.exec_module(module)
        ctx = _FakeCtx()
        module.register(ctx)
    finally:
        sys.modules.pop(_FAKE_MODULE_NAME, None)

    assert len(ctx.calls) == 1
    call = ctx.calls[0]
    assert call["name"] == "web_search"
    assert call["toolset"] == "sekurvia"
    assert call["is_async"] is True
    assert call["requires_env"] == ["SEARXNG_URL"]
    assert callable(call["handler"])


@pytest.mark.parametrize(
    "name",
    ["LICENSE", "plugin.yaml", "pyproject.toml", "README.md"],
)
def test_repo_root_files_present(name: str) -> None:
    """The shim has to live next to these files for Hermes' loader."""
    assert (REPO_ROOT / name).exists()
