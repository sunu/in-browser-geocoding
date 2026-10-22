"""T5 candidate generator: query -> k best parse frames (plan-005).

The model directory comes from the config (`t5.model_dir`) or the GEOPARSE_T5_DIR environment variable.
Runtime: transformers and torch (optional extra "t5"). CPU is fast enough for t5-small.
"""
from __future__ import annotations

import os
import threading
import time
from functools import lru_cache
from pathlib import Path

from geoparse.config import REPO_ROOT, load_config
from geoparse.t5.frames import Frame

PREFIX = "parse: "


class T5Parser:
    def __init__(self, model_dir: str | Path, device: str | None = None):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self.torch = torch
        self.dir = Path(model_dir)
        self.tok = AutoTokenizer.from_pretrained(str(self.dir))
        self.model = AutoModelForSeq2SeqLM.from_pretrained(str(self.dir)).eval()
        self.device = device or "cpu"
        self.model.to(self.device)
        self._lock = threading.Lock()

    def frames(self, query: str, k: int = 4, max_new_tokens: int = 96) -> tuple[list[Frame], float]:
        """The k best frames with their sequence log probabilities, and the latency in seconds."""
        t0 = time.time()
        x = self.tok([PREFIX + query], return_tensors="pt", truncation=True, max_length=64).to(self.device)
        with self._lock, self.torch.no_grad():
            out = self.model.generate(**x, max_new_tokens=max_new_tokens, num_beams=max(k, 1),
                                      num_return_sequences=k, output_scores=True, return_dict_in_generate=True)
        texts = self.tok.batch_decode(out.sequences, skip_special_tokens=True)
        scores = out.sequences_scores.tolist() if getattr(out, "sequences_scores", None) is not None else [0.0] * len(texts)
        frames = []
        for t, s in zip(texts, scores):
            f = Frame.from_text(t, score=float(s))
            if f is not None and all(f.to_text() != g.to_text() for g in frames):
                frames.append(f)
        return frames, time.time() - t0


def model_dir() -> Path | None:
    d = os.environ.get("GEOPARSE_T5_DIR") or load_config().get("t5", {}).get("model_dir")
    if not d:
        return None
    p = Path(d)
    return p if p.is_absolute() else REPO_ROOT / p


@lru_cache(maxsize=2)
def get_t5(path: str | None = None) -> T5Parser:
    d = Path(path) if path else model_dir()
    if d is None or not d.exists():
        raise FileNotFoundError(f"T5 model not found: {d}")
    return T5Parser(d)
