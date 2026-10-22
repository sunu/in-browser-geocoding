"""LLM paraphrases and the LLM test set (plan-005 section 3.2), through OpenRouter.

Paraphrases (training):
  uv run python -m training.paraphrase para --n-seeds 3000 --per-seed 3
Test set (separate prompt and model, never used for training):
  uv run python -m training.paraphrase testset --per-template 15

Code accepts an LLM example only if its frame passes check_frame (template known, spans in the query,
quantities in the canonical form). For paraphrases, the quantities must also equal the seed quantities.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from geoparse.config import REPO_ROOT  # loads .env
from geoparse.t5.frames import Frame, check_frame, distance_m, value_num
from geoparse.templates.model import all_templates

DATA = REPO_ROOT / "training" / "data"
URL = "https://openrouter.ai/api/v1/chat/completions"
PARA_MODEL = "anthropic/claude-haiku-5.5"
TEST_MODEL = "anthropic/claude-sonnet-5.5"


def frame_spec() -> str:
    lines = []
    for t in all_templates().values():
        slots = ", ".join(f"{k} ({v.type}{', optional' if v.optional or v.default is not None else ''})" for k, v in t.slots.items())
        lines.append(f"- {t.id}: {t.description}. Slots: {slots}. Example: {t.examples[0] if t.examples else ''}")
    lines.append("- unsupported: the query asks for something else (weather, routes, facts, chat). No slots.")
    return "\n".join(lines)


RULES = """Frame format: <template> ; <slot> = <value> ; <slot> = <value>
Rules for slot values:
- Every slot value except distance and value is an EXACT substring of the query (same spelling, same case).
- A region slot can hold a whole description, for example "coastal districts of Odisha", if the query nests one.
- distance = <number in digits> <unit>, unit is one of: m, km, mi. Examples: "half a kilometre" -> 0.5 km; "2000 metres" -> 2000 m.
- value = <number in digits> [<scale>], scale is one of: thousand, lakh, million, crore, billion. Examples: "ten lakh" -> 10 lakh; "1,000,000" -> 1000000; "a million" -> 1 million.
- Leave out an optional slot that the query does not state.
- Closed slots (level, pred, dir, category, attr, op) hold the words of the query that express them, for example pred = "near the sea"."""


def call(model: str, system: str, user: str, temperature: float = 0.9, retries: int = 3,
         reasoning: bool = False) -> tuple[str, dict]:
    headers = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"}
    body = {"model": model, "temperature": temperature, "max_tokens": 12000,
            "reasoning": {"enabled": reasoning},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    for i in range(retries):
        try:
            r = httpx.post(URL, headers=headers, json=body, timeout=180)
            if r.status_code == 200:
                data = r.json()
                return data["choices"][0]["message"]["content"], data.get("usage", {})
        except httpx.HTTPError:
            pass
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"OpenRouter failed: {r.status_code} {r.text[:200]}")


def extract_json(text: str):
    m = re.search(r"\[.*\]", text, re.S)
    return json.loads(m.group()) if m else []


HINDI_WORDS = {"ka", "ke", "ki", "kya", "hai", "hain", "me", "mein", "se", "kaun", "kahan", "jinki", "jiski", "batao",
               "wala", "wale", "abadi", "kam", "zyada", "aur", "ko", "par", "pe", "sab", "saare", "kitne", "dikhao"}


def is_english(q: str) -> bool:
    return not (set(re.findall(r"[a-z]+", q.lower())) & HINDI_WORDS)


def exact_spans(frame: Frame, query: str) -> Frame:
    """Replace each span with the exact text of the query (same case)."""
    from geoparse.t5.frames import find_span

    slots = {}
    for k, v in frame.slots.items():
        r = None if k in ("distance", "value") else find_span(query, v)
        slots[k] = query[r[0]:r[1]] if r else v
    return Frame(template=frame.template, slots=slots)


def quantities(frame: Frame) -> tuple:
    d = frame.slots.get("distance")
    v = frame.slots.get("value")
    return (round(distance_m(d), 3) if d else None, round(value_num(v), 3) if v else None)


# ---------------------------------------------------------------- paraphrases

PARA_SYSTEM = f"""You write training data for a parser of location queries for maps of India.
Templates:
{frame_spec()}

{RULES}

Answer with a JSON array only. Each item: {{"seed": <seed number>, "query": "...", "frame": "..."}}."""


def para_prompt(seeds: list[dict], per_seed: int) -> str:
    lines = [f"Rewrite each seed query in {per_seed} different ways that real users in India type into a map search box.",
             "Write in English only (Indian English is fine; no Hindi or other languages). "
             "Vary the words and the word order a lot: informal words, questions, short forms, "
             "synonyms (for example 'near the sea' for coastal, 'metres' for m), a spelling mistake sometimes.",
             "Keep the same meaning: the same template, the same places (you may change their case or spelling a little), "
             "the same distances and numbers (you may write them differently). Give the frame for each rewrite.", ""]
    for i, s in enumerate(seeds):
        lines.append(f"Seed {i}: {s['query']}\nFrame: {s['frame']}")
    return "\n".join(lines)


def run_para(n_seeds: int, per_seed: int, batch: int, workers: int, seed: int) -> None:
    rng = random.Random(seed)
    syn = [json.loads(l) for l in (DATA / "synthetic.jsonl").read_text().splitlines()]
    rng.shuffle(syn)
    seeds = syn[:n_seeds]
    templates = all_templates()
    out_path = DATA / "paraphrase.jsonl"
    done = set()
    if out_path.exists():
        done = {json.loads(l)["seed_query"] for l in out_path.read_text().splitlines() if l.strip()}
    seeds = [s for s in seeds if s["query"] not in done]
    batches = [seeds[i:i + batch] for i in range(0, len(seeds), batch)]
    stats = {"ok": 0, "bad": 0, "in_tok": 0, "out_tok": 0}

    def work(b):
        try:
            text, usage = call(PARA_MODEL, PARA_SYSTEM, para_prompt(b, per_seed))
        except RuntimeError as e:
            return [], {"error": str(e)}
        items = extract_json(text)
        good = []
        bad = 0
        for it in items:
            try:
                sd = b[int(it["seed"])]
                f = Frame.from_text(it["frame"])
                sf = Frame.from_text(sd["frame"])
            except (KeyError, ValueError, IndexError, TypeError):
                bad += 1
                continue
            q = re.sub(r"\s+", " ", str(it.get("query", ""))).strip()
            if (f is None or f.template != sf.template or check_frame(f, q, templates) or quantities(f) != quantities(sf)
                    or set(f.slots) != set(sf.slots) or not is_english(q)):
                bad += 1
                continue
            f = exact_spans(f, q)
            good.append({"query": q, "frame": f.to_text(), "template": f.template, "source": "paraphrase",
                         "seed_query": sd["query"]})
        return good, {"bad": bad, **usage}

    with ThreadPoolExecutor(workers) as pool, out_path.open("a") as out:
        for i, (good, info) in enumerate(pool.map(work, batches)):
            for g in good:
                out.write(json.dumps(g, ensure_ascii=False) + "\n")
            out.flush()
            stats["ok"] += len(good)
            stats["bad"] += info.get("bad", 0)
            stats["cost"] = round(stats.get("cost", 0) + (info.get("cost") or 0), 4)
            stats["in_tok"] += info.get("prompt_tokens", 0)
            stats["out_tok"] += info.get("completion_tokens", 0)
            if i % 10 == 0 or i == len(batches) - 1:
                print(f"batch {i + 1}/{len(batches)} {stats}", flush=True)


# ---------------------------------------------------------------- test set

TEST_SYSTEM = f"""You write a test set for a parser of location queries for maps of India.
Templates:
{frame_spec()}

{RULES}

Answer with a JSON array only. Each item: {{"query": "...", "frame": "..."}}."""


def run_testset(per_template: int, workers: int, name: str = "llm_test") -> None:
    templates = all_templates()
    jobs = list(templates) + ["unsupported"]

    def work(tid):
        desc = "queries that are out of scope (no template fits)" if tid == "unsupported" else \
            f"queries for the template {tid} ({templates[tid].description})"
        prompt = (f"Write {per_template} different {desc}. Write them as different real people in India would type them "
                  "into a map search: some short, some long, some as questions, some informal, a few with spelling "
                  "mistakes. English only. Use real places in India (states, districts, cities, neighbourhoods, streets, landmarks). "
                  "Do not copy the examples. Give the frame for each query.")
        text, usage = call(TEST_MODEL, TEST_SYSTEM, prompt, temperature=1.0, reasoning=True)
        out = []
        for it in extract_json(text):
            f = Frame.from_text(str(it.get("frame", "")))
            q = re.sub(r"\s+", " ", str(it.get("query", ""))).strip()
            if f is None or check_frame(f, q, templates) or not is_english(q):
                continue
            f = exact_spans(f, q)
            out.append({"query": q, "frame": f.to_text(), "template": f.template, "source": "llm_test",
                        "asked_template": tid})
        return out

    recs = []
    with ThreadPoolExecutor(workers) as pool:
        for out in pool.map(work, jobs):
            recs += out
    # Remove queries that are in the training data.
    train = set()
    for name in ("synthetic.jsonl", "paraphrase.jsonl"):
        p = DATA / name
        if p.exists():
            train |= {json.loads(l)["query"].lower() for l in p.read_text().splitlines() if l.strip()}
    for other in ("llm_test.jsonl", "llm_dev.jsonl"):
        p = DATA / other
        if p.exists() and other != f"{name}.jsonl":
            train |= {json.loads(l)["query"].lower() for l in p.read_text().splitlines() if l.strip()}
    recs = [r for r in recs if r["query"].lower() not in train]
    for r in recs:
        r["source"] = name
    (DATA / f"{name}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
    from collections import Counter

    print(len(recs), Counter(r["template"] for r in recs).most_common())


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("para")
    p.add_argument("--n-seeds", type=int, default=3000)
    p.add_argument("--per-seed", type=int, default=3)
    p.add_argument("--batch", type=int, default=10)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--seed", type=int, default=11)
    t = sub.add_parser("testset")
    t.add_argument("--per-template", type=int, default=15)
    t.add_argument("--workers", type=int, default=8)
    t.add_argument("--name", default="llm_test", help="llm_test (final) or llm_dev (error analysis)")
    args = ap.parse_args()
    if args.cmd == "para":
        run_para(args.n_seeds, args.per_seed, args.batch, args.workers, args.seed)
    else:
        run_testset(args.per_template, args.workers, args.name)


if __name__ == "__main__":
    main()
