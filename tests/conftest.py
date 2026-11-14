"""Shared pytest fixtures.

`recap.shared.hook_io.log()` appends to `$XDG_STATE_HOME/knowledge-gardener/auto-recap.log`.
Any in-process test that triggers it (e.g. an error path in `daily_note`) would
otherwise append to the developer's REAL auto-recap log. Point the state home
at a per-test temp dir so the suite never pollutes machine-local state.
Subprocess tests pass their own `XDG_STATE_HOME` in the child env.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
