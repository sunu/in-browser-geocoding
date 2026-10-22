"""JSONL decision log. Each record is one decision with its inputs, options, output, and confidence.

The logs are the training data for later local classifiers.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path
from typing import Any

from geoparse.config import REPO_ROOT, load_config

_lock = threading.Lock()


class DecisionLogger:
    def __init__(self, log_dir: str | Path | None = None, enabled: bool = True):
        d = Path(log_dir or load_config()["decisions"]["log_dir"])
        self.dir = d if d.is_absolute() else REPO_ROOT / d
        self.enabled = enabled

    def _write(self, name: str, rec: dict[str, Any]) -> None:
        if not self.enabled:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        day = dt.date.today().isoformat()
        line = json.dumps(rec, default=str, ensure_ascii=False)
        with _lock, (self.dir / f"{name}-{day}.jsonl").open("a") as f:
            f.write(line + "\n")

    def decision(self, *, decision: str, run_id: str, inputs: dict[str, Any], options: Any, output: Any,
                 confidence: float, impl: str, trace: dict[str, Any]) -> None:
        self._write("decisions", {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "run_id": run_id,
            "decision": decision,
            "inputs": inputs,
            "options": options,
            "output": output,
            "confidence": confidence,
            "impl": impl,
            "trace": trace,
        })

    def unsupported(self, *, run_id: str, query: str, reason: str, trace: list[dict[str, Any]]) -> None:
        self._write("unsupported", {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "run_id": run_id,
            "query": query,
            "reason": reason,
            "trace": trace,
        })


class NullLogger(DecisionLogger):
    def __init__(self):
        super().__init__(enabled=False)
