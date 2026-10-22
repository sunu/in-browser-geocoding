"""GLiNER span extraction with onnxruntime and tokenizers only (no torch).

The input encoding follows the GLiNER "markerV0" span mode, as in the gliner Python and JS packages:
  [CLS] <<ENT>> label1 <<ENT>> label2 ... <<SEP>> word1 word2 ... [SEP]
words_mask gives the 1-based word index on the first sub-token of each text word, else 0.
span_idx lists every (start, end) word pair with width < max_width.
The model returns logits with shape [batch, num_words, max_width, num_labels].
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

REPO = "onnx-community/gliner_small-v2.1"
MODEL_FILE = "onnx/model_int8.onnx"
WORD_RE = re.compile(r"\w+(?:[-_]\w+)*|\S")


@dataclass
class RawSpan:
    start: int  # character offset
    end: int  # character offset, exclusive
    text: str
    label: str
    score: float


def split_words(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(), m.start(), m.end()) for m in WORD_RE.finditer(text)]


class GlinerOnnx:
    def __init__(self, repo: str = REPO, model_file: str = MODEL_FILE):
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        cfg = json.loads(open(hf_hub_download(repo, "gliner_config.json")).read())
        self.max_width = cfg["max_width"]
        self.ent_token = cfg["ent_token"]
        self.sep_token = cfg["sep_token"]
        self.tok = Tokenizer.from_file(hf_hub_download(repo, "tokenizer.json"))
        self.cls_id = self.tok.token_to_id("[CLS]")
        self.sep_id = self.tok.token_to_id("[SEP]")
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(hf_hub_download(repo, model_file), opts)

    def _ids(self, word: str) -> list[int]:
        return self.tok.encode(word, add_special_tokens=False).ids

    def encode(self, words: list[str], labels: list[str]) -> dict[str, np.ndarray]:
        input_ids = [self.cls_id]
        words_mask = [0]
        prompt: list[str] = []
        for label in labels:
            prompt += [self.ent_token, label]
        prompt.append(self.sep_token)
        for w in prompt:
            ids = self._ids(w)
            input_ids += ids
            words_mask += [0] * len(ids)
        for i, w in enumerate(words, start=1):
            ids = self._ids(w) or [self.tok.token_to_id("[UNK]")]
            input_ids += ids
            words_mask += [i] + [0] * (len(ids) - 1)
        input_ids.append(self.sep_id)
        words_mask.append(0)

        n = len(words)
        span_idx, span_mask = [], []
        for i in range(n):
            for j in range(self.max_width):
                span_idx.append([i, min(i + j, n - 1)])
                span_mask.append(i + j < n)
        return {
            "input_ids": np.array([input_ids], dtype=np.int64),
            "attention_mask": np.ones((1, len(input_ids)), dtype=np.int64),
            "words_mask": np.array([words_mask], dtype=np.int64),
            "text_lengths": np.array([[n]], dtype=np.int64),
            "span_idx": np.array([span_idx], dtype=np.int64),
            "span_mask": np.array([span_mask], dtype=bool),
        }

    def predict(self, text: str, labels: list[str], threshold: float = 0.4) -> list[RawSpan]:
        words = split_words(text)
        if not words:
            return []
        inputs = self.encode([w for w, _, _ in words], labels)
        logits = self.session.run(["logits"], inputs)[0][0]  # [num_words, max_width, num_labels]
        probs = 1.0 / (1.0 + np.exp(-logits))
        n = len(words)
        cands = []
        for i, j, k in zip(*np.where(probs > threshold)):
            if i + j >= n:
                continue
            cands.append((float(probs[i, j, k]), int(i), int(i + j), labels[k]))
        # Flat NER: greedy, highest score first, no overlap.
        cands.sort(reverse=True)
        taken: list[tuple[int, int]] = []
        out = []
        for score, s, e, label in cands:
            if any(not (e < ts or s > te) for ts, te in taken):
                continue
            taken.append((s, e))
            cs, ce = words[s][1], words[e][2]
            out.append(RawSpan(cs, ce, text[cs:ce], label, round(score, 4)))
        return sorted(out, key=lambda r: r.start)


@lru_cache(maxsize=1)
def get_model() -> GlinerOnnx:
    return GlinerOnnx()
