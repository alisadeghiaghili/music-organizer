#!/usr/bin/env python3
"""Smoke tests that the application entry points resolve to callables.

The ``music-organizer-gui`` script pointed at ``music_organizer_gui:main`` which
did not exist, so ``pip install`` produced a broken ``music-organizer-gui``
command. These tests import the target module and assert the named callable
exists, so a regression fails CI without needing a display or a network.
"""

import importlib
from pathlib import Path

import pytest


def _pyproject_scripts():
    """Return the [project.scripts] mapping, or None if unparsable on this Python.

    tomllib is stdlib from 3.11; on 3.10 we can't parse pyproject.toml here, so
    the pyproject-driven test is skipped but the direct smoke test still runs.
    """
    try:
        import tomllib
    except ModuleNotFoundError:
        return None
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data.get("project", {}).get("scripts", {})


def test_cli_main_is_callable():
    mod = importlib.import_module("music_organizer_cli")
    assert callable(getattr(mod, "main", None))


def test_gui_main_is_callable():
    mod = importlib.import_module("music_organizer_gui")
    assert callable(getattr(mod, "main", None))


@pytest.mark.skipif(
    _pyproject_scripts() is None,
    reason="tomllib unavailable (Python < 3.11)",
)
def test_all_pyproject_entry_points_resolve_to_callables():
    scripts = _pyproject_scripts()
    assert scripts, "expected [project.scripts] in pyproject.toml"
    for name, target in scripts.items():
        module_name, _, func = target.partition(":")
        assert func, f"entry point {name!r} has no ':callable' part: {target!r}"
        mod = importlib.import_module(module_name)
        assert callable(getattr(mod, func, None)), (
            f"entry point {name!r} -> {target!r} does not resolve to a callable"
        )
