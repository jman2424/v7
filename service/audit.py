"""
Append-only audit trail.

Records:
- who (username/role), ip
- action (string), target (path/id)
- before / after (optional snapshots)
- timestamp

Writes JSON Lines to logs/selfrepair.log by default, or a custom file.
"""

from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


def _default_audit_path() -> str:
    data_root = (os.getenv("V7_DATA_DIR") or "").strip()
    return os.path.join(data_root, "logs", "selfrepair.log") if data_root else "logs/selfrepair.log"


@dataclass
class AuditService:
    log_path: str = field(default_factory=_default_audit_path)

    def _ensure_dir(self) -> None:
        d = os.path.dirname(self.log_path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

    def record(
        self,
        *,
        user: str,
        role: str,
        ip: str,
        action: str,
        target: str,
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._ensure_dir()
        evt = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "user": user,
            "role": role,
            "ip": ip,
            "action": action,
            "target": target,
            "before": before,
            "after": after,
            "extra": extra or {},
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")
