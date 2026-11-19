"""The evaluation queries: never in the training data (all gold sets, the LLM dev and test sets)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def eval_queries() -> set[str]:
    """Lower-case, stripped queries of gold/*.jsonl and training/data/llm_{dev,test}.jsonl."""
    paths = sorted((ROOT / "gold").glob("*.jsonl")) + [ROOT / "training" / "data" / f"llm_{n}.jsonl" for n in ("dev", "test")]
    out = set()
    for p in paths:
        if p.exists():
            out |= {json.loads(l)["query"].lower().strip() for l in p.read_text().splitlines() if l.strip()}
    return out
