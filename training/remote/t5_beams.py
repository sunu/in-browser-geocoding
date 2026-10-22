"""Batched T5 beam search over many queries (GPU). Output: one JSON line per query with the k best frames.

Usage: uv run python t5_beams.py --model runs/t5-small-v3/best --inputs data/*.jsonl --out beams.jsonl
"""
from __future__ import annotations

import argparse
import json

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

PREFIX = "parse: "


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--inputs", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--bs", type=int, default=128)
    args = ap.parse_args()
    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSeq2SeqLM.from_pretrained(args.model).eval().cuda()
    queries = []
    for p in args.inputs:
        for line in open(p):
            if line.strip():
                queries.append(json.loads(line)["query"])
    queries = list(dict.fromkeys(queries))
    with open(args.out, "w") as out:
        for i in range(0, len(queries), args.bs):
            batch = queries[i:i + args.bs]
            x = tok([PREFIX + q for q in batch], return_tensors="pt", padding=True, truncation=True, max_length=64).to("cuda")
            with torch.no_grad():
                o = model.generate(**x, max_new_tokens=96, num_beams=args.k, num_return_sequences=args.k,
                                   output_scores=True, return_dict_in_generate=True)
            texts = tok.batch_decode(o.sequences, skip_special_tokens=True)
            scores = o.sequences_scores.tolist()
            for j, q in enumerate(batch):
                beams = [(texts[j * args.k + b], round(scores[j * args.k + b], 5)) for b in range(args.k)]
                out.write(json.dumps({"query": q, "beams": beams}, ensure_ascii=False) + "\n")
            print(f"{i + len(batch)}/{len(queries)}", flush=True)


if __name__ == "__main__":
    main()
