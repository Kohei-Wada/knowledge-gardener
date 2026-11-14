from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import pathlib
from ..shared.hook_io import log


@dataclasses.dataclass(frozen=True)
class RecapContext:
    sid8: str
    vault: pathlib.Path
    today_str: str
    transcript_path: str | None

    @classmethod
    def from_hook(cls, raw_stdin: str, dict_env: dict[str, str]) -> "RecapContext | None":
        if dict_env.get("KG_AUTO_RECAP") != "1":
            return None
        try:
            payload = json.loads(raw_stdin) if raw_stdin else {}
        except Exception:
            log("invalid hook payload")
            return None
        if not isinstance(payload, dict):
            return None
        v = dict_env.get("KG_VAULT")
        if not v:
            log("KG_VAULT unset or invalid")
            return None
        vault = pathlib.Path(v)
        if not vault.is_dir():
            log("KG_VAULT unset or invalid")
            return None
        sid8 = (payload.get("session_id") or "")[:8] or "unknown"
        transcript_path = payload.get("transcript_path") or None
        return cls(
            sid8=sid8,
            vault=vault,
            today_str=_dt.date.today().isoformat(),
            transcript_path=transcript_path,
        )
