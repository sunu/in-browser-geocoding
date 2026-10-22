"""Input format for the local cross-encoder (plan-006). No dependencies, so that the training code on the
GPU machine uses the same format as the runtime.

One example = (decision, instructions, state, option). The model scores each option; a softmax over the
options of one question gives the probabilities.
"""
from __future__ import annotations

import json
from typing import Any

# Option keys that carry no meaning; the model sees only their descriptions.
_OPAQUE_PREFIXES = ("s", "c")


def state_text(state: Any) -> str:
    if isinstance(state, str):
        return f"text: {state}"
    parts = []
    for k in sorted(state):
        v = state[k]
        if not isinstance(v, str):
            v = json.dumps(v, ensure_ascii=False)
        parts.append(f"{k}: {v}")
    return " | ".join(parts)


def option_text(key: str, desc: str) -> str:
    if key[:1] in _OPAQUE_PREFIXES and key[1:].isdigit():
        return desc
    if key in ("true", "false"):
        return f"{key}: {desc}"
    return f"{key.replace('_', ' ')}: {desc}"


# Decisions whose options are ordered by the T5 beam score. The position is part of the input.
RANKED = ("pick_family", "pick_template", "pick_split")


def pair(decision: str, instructions: str, state: Any, key: str, desc: str, position: int = 0) -> tuple[str, str]:
    """(text_a, text_b) for the cross-encoder. `position` is the 0-based index of the option in the question."""
    b = option_text(key, desc)
    if decision.split(".")[0] in RANKED:
        b = f"[rank {position + 1}] {b}"
    return f"{decision} | {instructions} | {state_text(state)}", b
