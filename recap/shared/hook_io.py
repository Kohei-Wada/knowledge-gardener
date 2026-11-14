"""Hook stdout protocol and the auto-recap debug log.

Split out of the former recap/recap_common.py grab-bag: this module owns the
two ways the recap code talks to the outside world from inside a hook —
emitting the continue payload on stdout, and appending to the auto-recap log.
"""
from __future__ import annotations

import datetime as _dt
import pathlib
import sys

DEFAULT_TIMEOUT = 180
LOG_FILE = pathlib.Path.home() / ".local" / "state" / "knowledge-gardener" / "auto-recap.log"


def emit_continue() -> None:
    sys.stdout.write('{"continue": true, "suppressOutput": true}\n')
    sys.stdout.flush()


def log(line: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            ts = _dt.datetime.now().isoformat(timespec="seconds")
            f.write(f"{ts} {line}\n")
    except OSError:
        pass
