"""Check the ONNX models against PyTorch (plan-007 section 3.4, check 1).

T5: a simple beam search over encoder.onnx and decoder.onnx (the same algorithm as web/src/models/t5.ts)
against transformers generate(). Cross-encoder: the decisions on the validation questions.

Usage: uv run python scripts/onnx_parity.py [--int8]
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer

from geoparse.config import REPO_ROOT
from geoparse.t5.frames import Frame
from geoparse.t5.model import get_t5
from training.eval_t5 import core_of_frame

M = REPO_ROOT / "web" / "public" / "models"


def log_softmax(x):
    x = x - x.max(-1, keepdims=True)
    return x - np.log(np.exp(x).sum(-1, keepdims=True))


class OnnxT5:
    def __init__(self, int8: bool):
        sfx = "_int8" if int8 else ""
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.enc = ort.InferenceSession(str(M / "t5" / f"encoder{sfx}.onnx"), opts)
        self.dec = ort.InferenceSession(str(M / "t5" / f"decoder{sfx}.onnx"), opts)
        self.tok = AutoTokenizer.from_pretrained(str(M / "t5"))
        self.gen = json.loads((M / "t5" / "generation.json").read_text())

    def beams(self, query: str, k: int = 4, max_new: int = 96):
        x = self.tok([self.gen["prefix"] + query], return_tensors="np", truncation=True, max_length=64)
        ids, mask = x["input_ids"].astype(np.int64), x["attention_mask"].astype(np.int64)
        kv = self.enc.run(None, {"input_ids": ids, "attention_mask": mask})[0]
        L, _, _, H, _, D = kv.shape
        past = np.zeros((L, 2, 1, H, 0, D), np.float32)
        eos = self.gen["eos_token_id"]
        alive = [([self.gen["decoder_start_token_id"]], 0.0)]
        done = []
        for step in range(max_new):
            dec_ids = np.array([[s[-1]] for s, _ in alive], dtype=np.int64)
            logits, present = self.dec.run(None, {"input_ids": dec_ids, "past": past, "cross_kv": kv,
                                                  "encoder_attention_mask": mask})
            lp = log_softmax(logits.astype(np.float64))
            cands = []
            for i, (seq, sc) in enumerate(alive):
                top = np.argpartition(-lp[i], 2 * k)[: 2 * k]
                for t in top:
                    cands.append((seq + [int(t)], sc + float(lp[i, t]), i))
            cands.sort(key=lambda c: -c[1])
            alive, parents = [], []
            for seq, sc, i in cands:
                if seq[-1] == eos:
                    # Length-normalised score (length penalty 1.0), as in transformers.
                    done.append((seq, sc / (len(seq) - 1)))
                else:
                    alive.append((seq, sc))
                    parents.append(i)
                if len(alive) == k:
                    break
            past = present[:, :, parents]
            if len(done) >= k:
                best_alive = max((sc / (len(s) - 1) for s, sc in alive), default=-1e9)
                if sorted(d[1] for d in done)[-k] >= best_alive:
                    break
            if not alive:
                break
        done.sort(key=lambda d: -d[1])
        out = []
        for seq, sc in done[:k]:
            f = Frame.from_text(self.tok.decode(seq, skip_special_tokens=True), score=sc)
            if f and all(f.to_text() != g.to_text() for g in out):
                out.append(f)
        return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--int8", action="store_true")
    args = ap.parse_args()
    queries = []
    for name in ("llm_dev", "llm_test"):
        queries += [json.loads(l)["query"] for l in open(REPO_ROOT / "training" / "data" / f"{name}.jsonl")]
    pt = get_t5()
    ox = OnnxT5(args.int8)
    same_top, same_core, t_pt, t_ox = 0, 0, 0.0, 0.0
    diffs = []
    for q in queries:
        t0 = time.time(); a, _ = pt.frames(q, k=4); t_pt += time.time() - t0
        t0 = time.time(); b = ox.beams(q, k=4); t_ox += time.time() - t0
        if a and b and a[0].to_text() == b[0].to_text():
            same_top += 1
        if a and b and core_of_frame(a[0]) == core_of_frame(b[0]):
            same_core += 1
        elif len(diffs) < 8:
            diffs.append((q, a[0].to_text() if a else None, b[0].to_text() if b else None))
    n = len(queries)
    print(f"T5 {'int8' if args.int8 else 'fp32'}: same top frame {same_top}/{n}, same core {same_core}/{n}, "
          f"time torch {1000 * t_pt / n:.0f} ms, onnx {1000 * t_ox / n:.0f} ms per query")
    for d in diffs:
        print("   ", d)


if __name__ == "__main__":
    main()


def accuracy() -> None:
    """T5 top-1 core accuracy against the labels, for torch, ONNX fp32, and ONNX int8."""
    from training.eval_t5 import load_sets

    sets = load_sets()
    pt, f32, i8 = get_t5(), OnnxT5(False), OnnxT5(True)
    for name in ("llm_dev", "llm_test"):
        recs = [r for r in sets[name] if not r.get("refusal")]
        acc = {"torch": 0, "fp32": 0, "int8": 0}
        for r in recs:
            a, _ = pt.frames(r["query"], k=4)
            for k, fr in (("torch", a), ("fp32", f32.beams(r["query"])), ("int8", i8.beams(r["query"]))):
                acc[k] += bool(fr) and core_of_frame(fr[0]) == r["core"]
        print(name, len(recs), {k: f"{v / len(recs):.3f}" for k, v in acc.items()})


def xenc_parity() -> None:
    import torch

    from geoparse.decisions.providers import LocalClassifierProvider
    from geoparse.decisions.xenc_format import pair

    lp = LocalClassifierProvider(REPO_ROOT / "models" / "local" / "current")
    tok = AutoTokenizer.from_pretrained(str(M / "xenc"))
    names = json.loads((M / "xenc" / "inputs.json").read_text())["input_names"]
    sess = {k: ort.InferenceSession(str(M / "xenc" / f"model{s}.onnx")) for k, s in (("fp32", ""), ("int8", "_int8"))}
    rows = [json.loads(l) for l in open(REPO_ROOT / "training" / "data" / "decisions.jsonl")]
    rows = [r for r in rows if r["split"] == "val"][:2000]
    agree = {"fp32": 0, "int8": 0}
    correct = {"torch": 0, "fp32": 0, "int8": 0}
    for r in rows:
        opts = r["options"]
        pairs = [pair(r["decision"], r["instructions"], r["state"], k, v, i) for i, (k, v) in enumerate(opts.items())]
        enc = tok([a for a, _ in pairs], [b for _, b in pairs], return_tensors="np", padding=True, truncation=True, max_length=128)
        ref = lp.probs(r["decision"], r["instructions"], r["state"], opts)
        ref_best = max(ref, key=ref.get)
        correct["torch"] += ref_best == r["label"]
        for k, s in sess.items():
            lg = s.run(None, {n: enc[n].astype(np.int64) for n in names})[0].reshape(-1)
            best = list(opts)[int(np.argmax(lg))]
            agree[k] += best == ref_best
            correct[k] += best == r["label"]
    n = len(rows)
    print("xenc agreement with torch:", {k: f"{v / n:.4f}" for k, v in agree.items()},
          "accuracy:", {k: f"{v / n:.4f}" for k, v in correct.items()})


if __name__ == "__main__" and False:
    pass
