"""Logger estructurat JSON — ADR-0008."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone


class StructuredLogger:
    """Logger que emet JSON per línia. Secrets mai als logs."""

    def __init__(self, name: str = "migration_agent") -> None:
        level_name = os.getenv("LOG_LEVEL", "info").upper()
        self._level = getattr(logging, level_name, logging.INFO)
        self._name = name

    def _emit(self, level: str, event: str, **kwargs: object) -> None:
        if getattr(logging, level.upper(), 0) < self._level:
            return
        record: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "event": event,
        }
        record.update({k: v for k, v in kwargs.items() if v is not None})
        print(json.dumps(record, ensure_ascii=False), flush=True)  # noqa: T201

    def info(self, event: str, **kwargs: object) -> None:
        self._emit("info", event, **kwargs)

    def warn(self, event: str, **kwargs: object) -> None:
        self._emit("warn", event, **kwargs)

    def error(self, event: str, **kwargs: object) -> None:
        self._emit("error", event, **kwargs)

    def debug(self, event: str, **kwargs: object) -> None:
        self._emit("debug", event, **kwargs)


log = StructuredLogger()
