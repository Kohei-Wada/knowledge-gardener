"""Hook stdout protocol and the auto-recap debug log.

Split out of the former recap/recap_common.py grab-bag: this module owns the
two ways the recap code talks to the outside world from inside a hook —
emitting the continue payload on stdout, and appending to the auto-recap log.
"""
from __future__ import annotations

import datetime as _dt
import pathlib
import sys

from .paths import kg_state_dir

DEFAULT_TIMEOUT = 180


def log_path() -> pathlib.Path:
    return kg_state_dir() / "auto-recap.log"


def emit_continue() -> None:
    sys.stdout.write('{"continue": true, "suppressOutput": true}\n')
    sys.stdout.flush()


def log(line: str) -> None:
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open("a", encoding="utf-8") as f:
            ts = _dt.datetime.now().isoformat(timespec="seconds")
            f.write(f"{ts} {line}\n")
    except OSError:
        pass
