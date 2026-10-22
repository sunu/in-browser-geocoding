"""Train the local cross-encoder ("local Jev", plan-006) on decision questions.

Each question has several options. The model scores (question, option) pairs; a softmax over the options
of one question gives probabilities. Loss: cross-entropy to the label, or to the Jev probabilities when
the example has them. After training, one temperature per decision is fit on the validation split.

Usage: uv run python train_xenc.py --data data/decisions.jsonl --out runs/xenc-minilm
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from collections import defaultdict
from pathlib import Path

import torch
import torch.nn.functional as F
from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

from xenc_format import pair


def base(decision: str) -> str:
    return decision if decision.startswith("fill_closed_slot") else decision.split(".")[0]


def load(path: str, max_per_decision: int, seed: int):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    rng = random.Random(seed)
    rng.shuffle(rows)
    train, val = [], []
    count = defaultdict(int)
    for r in rows:
        if r["split"] == "val":
            val.append(r)
            continue
        b = base(r["decision"])
        if count[b] >= max_per_decision:
            continue
        count[b] += 1
        train.append(r)
    print("train per decision:", dict(count))
    return train, val


def encode_groups(tok, groups, max_len, device):
    a, b, sizes = [], [], []
    for g in groups:
        for i, (k, v) in enumerate(g["options"].items()):
            x, y = pair(g["decision"], g["instructions"], g["state"], k, v, i)
            a.append(x)
            b.append(y)
        sizes.append(len(g["options"]))
    enc = tok(a, b, return_tensors="pt", padding=True, truncation=True, max_length=max_len).to(device)
    return enc, sizes


def group_logits(model, enc, sizes):
    logits = model(**enc).logits.squeeze(-1).float()
    out, i = [], 0
    for n in sizes:
        out.append(logits[i:i + n])
        i += n
    return out


def target(g):
    keys = list(g["options"])
    if g.get("soft"):
        t = torch.tensor([float(g["soft"].get(k, 0.0)) for k in keys])
        if t.sum() > 0:
            return t / t.sum()
    t = torch.zeros(len(keys))
    t[keys.index(g["label"])] = 1.0
    return t


def evaluate(model, tok, rows, max_len, device, bs=64):
    model.eval()
    res = []  # (decision, logits list, label index)
    with torch.no_grad():
        for i in range(0, len(rows), bs):
            chunk = rows[i:i + bs]
            enc, sizes = encode_groups(tok, chunk, max_len, device)
            for g, lg in zip(chunk, group_logits(model, enc, sizes)):
                res.append((g["decision"], lg.cpu(), list(g["options"]).index(g["label"])))
    model.train()
    return res


def fit_temperature(items) -> float:
    best_t, best_nll = 1.0, float("inf")
    for t in [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]:
        nll = sum(-F.log_softmax(lg / t, dim=0)[y].item() for _, lg, y in items) / max(len(items), 1)
        if nll < best_nll:
            best_t, best_nll = t, nll
    return best_t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="cross-encoder/ms-marco-MiniLM-L12-v2")
    ap.add_argument("--data", default="data/decisions.jsonl")
    ap.add_argument("--out", default="runs/xenc-minilm")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--groups", type=int, default=32, help="questions per batch")
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--max-len", type=int, default=128)
    ap.add_argument("--max-per-decision", type=int, default=12000)
    ap.add_argument("--seed", type=int, default=21)
    args = ap.parse_args()
    torch.manual_seed(args.seed)
    device = "cuda"
    train, val = load(args.data, args.max_per_decision, args.seed)
    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(args.model, num_labels=1, ignore_mismatched_sizes=True).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    steps = args.epochs * math.ceil(len(train) / args.groups)
    sched = get_linear_schedule_with_warmup(opt, int(0.05 * steps), steps)
    rng = random.Random(args.seed)
    t0 = time.time()
    step = 0
    for ep in range(args.epochs):
        rng.shuffle(train)
        for i in range(0, len(train), args.groups):
            chunk = train[i:i + args.groups]
            enc, sizes = encode_groups(tok, chunk, args.max_len, device)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                lgs = group_logits(model, enc, sizes)
            loss = sum(-(target(g).to(device) * F.log_softmax(lg, dim=0)).sum() for g, lg in zip(chunk, lgs)) / len(chunk)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad()
            step += 1
            if step % 200 == 0:
                print(f"epoch {ep} step {step}/{steps} loss {loss.item():.4f} {time.time() - t0:.0f}s", flush=True)
        res = evaluate(model, tok, val, args.max_len, device)
        acc = sum(int(lg.argmax().item() == y) for _, lg, y in res) / len(res)
        print(f"epoch {ep} val acc {acc:.4f}", flush=True)

    out = Path(args.out) / "best"
    model.save_pretrained(out)
    tok.save_pretrained(out)
    res = evaluate(model, tok, val, args.max_len, device)
    by = defaultdict(list)
    for d, lg, y in res:
        by[base(d)].append((d, lg, y))
    temps, report = {}, {}
    for b, items in sorted(by.items()):
        temps[b] = fit_temperature(items)
        acc = sum(int(lg.argmax().item() == y) for _, lg, y in items) / len(items)
        report[b] = {"n": len(items), "acc": round(acc, 4), "temperature": temps[b]}
        print(f"{b:40s} n={len(items):5d} acc={acc:.4f} T={temps[b]}")
    temps["default"] = fit_temperature(res)
    (out / "calibration.json").write_text(json.dumps(temps, indent=1))
    (Path(args.out) / "val_report.json").write_text(json.dumps(report, indent=1))
    print(f"train time {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
