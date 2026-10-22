"""Fine-tune T5 to map a query to a parse frame (plan-005).

Usage (on the GPU machine):
  uv run python train_t5.py --model t5-small --out runs/t5-small
  uv run python train_t5.py --model google/flan-t5-base --out runs/flan-t5-base --bs 32
Input:  "parse: <query>"    Target: "<frame text>"
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import torch
from datasets import Dataset
from transformers import (AutoModelForSeq2SeqLM, AutoTokenizer, DataCollatorForSeq2Seq, Seq2SeqTrainer,
                          Seq2SeqTrainingArguments)

PREFIX = "parse: "


def load(paths: list[str]) -> list[dict]:
    out = []
    for p in paths:
        for line in Path(p).read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                out.append({"query": r["query"], "frame": r["frame"], "source": r.get("source", "")})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="t5-small")
    ap.add_argument("--data", nargs="+", default=["data/synthetic.jsonl", "data/paraphrase.jsonl"])
    ap.add_argument("--out", default="runs/t5-small")
    ap.add_argument("--epochs", type=float, default=6)
    ap.add_argument("--bs", type=int, default=64)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--max-src", type=int, default=64)
    ap.add_argument("--max-tgt", type=int, default=96)
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args()

    rows = load(args.data)
    rng = random.Random(args.seed)
    rng.shuffle(rows)
    n_val = max(200, len(rows) // 33)
    val, train = rows[:n_val], rows[n_val:]
    print(f"train {len(train)} val {len(val)}")

    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSeq2SeqLM.from_pretrained(args.model)

    def enc(batch):
        x = tok([PREFIX + q for q in batch["query"]], max_length=args.max_src, truncation=True)
        y = tok(text_target=batch["frame"], max_length=args.max_tgt, truncation=True)
        x["labels"] = y["input_ids"]
        return x

    dtr = Dataset.from_list(train).map(enc, batched=True, remove_columns=["query", "frame", "source"])
    dva = Dataset.from_list(val).map(enc, batched=True, remove_columns=["query", "frame", "source"])
    bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    targs = Seq2SeqTrainingArguments(
        output_dir=args.out, per_device_train_batch_size=args.bs, per_device_eval_batch_size=args.bs,
        learning_rate=args.lr, num_train_epochs=args.epochs, lr_scheduler_type="linear", warmup_steps=200,
        weight_decay=0.01, eval_strategy="epoch", save_strategy="epoch", save_total_limit=2,
        load_best_model_at_end=True, metric_for_best_model="eval_loss", greater_is_better=False,
        bf16=bf16, logging_steps=50, report_to=[], seed=args.seed, dataloader_num_workers=2,
    )
    trainer = Seq2SeqTrainer(model=model, args=targs, train_dataset=dtr, eval_dataset=dva,
                             data_collator=DataCollatorForSeq2Seq(tok, model=model), processing_class=tok)
    t0 = time.time()
    trainer.train()
    print(f"train time {time.time() - t0:.0f}s")
    best = Path(args.out) / "best"
    trainer.save_model(str(best))
    tok.save_pretrained(str(best))

    # Exact-match accuracy on the validation split (greedy).
    model = trainer.model.eval()
    dev = model.device
    hits = 0
    for i in range(0, len(val), 64):
        chunk = val[i:i + 64]
        x = tok([PREFIX + r["query"] for r in chunk], return_tensors="pt", padding=True, truncation=True,
                max_length=args.max_src).to(dev)
        with torch.no_grad():
            out = model.generate(**x, max_new_tokens=args.max_tgt, num_beams=1)
        preds = tok.batch_decode(out, skip_special_tokens=True)
        hits += sum(p.strip() == r["frame"] for p, r in zip(preds, chunk))
    print(f"val exact match {hits}/{len(val)} = {hits / len(val):.3f}")
    (Path(args.out) / "val_metrics.json").write_text(json.dumps({"exact": hits / len(val), "n": len(val)}))


if __name__ == "__main__":
    main()
