"""Reference parses from Python for the JS parity check (plan-007 section 3.4, check 2).

Settings as in the browser: T5 frames only (no split patterns), no NER spans, providers from the config
(local model and rules). Output: web/test/ref_parse.jsonl
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from geoparse.config import REPO_ROOT
from geoparse.decisions.functions import Decider
from geoparse.decisions.log import NullLogger
from geoparse.parse.pipeline import Parser
from gold.run_gold import canon


def main() -> None:
    queries = []
    for p in [REPO_ROOT / "gold" / "gold.jsonl", REPO_ROOT / "gold" / "heldout.jsonl",
              REPO_ROOT / "training" / "data" / "llm_dev.jsonl", REPO_ROOT / "training" / "data" / "llm_test.jsonl"]:
        queries += [json.loads(l)["query"] for l in open(p) if l.strip()]
    queries = list(dict.fromkeys(queries))
    parser = Parser(Decider(logger=NullLogger(), use_ner=False), use_t5=True, use_patterns="never")

    def one(q):
        r = parser.parse(q)
        return {"query": q, "ok": r.ok, "template": r.template, "dag": canon(r.dag) if r.ok else None,
                "reason": r.unsupported.reason if r.unsupported else None}

    with ThreadPoolExecutor(4) as pool:
        rows = list(pool.map(one, queries))
    out = REPO_ROOT / "web" / "test" / "ref_parse.jsonl"
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(len(rows), "references;", sum(r["ok"] for r in rows), "parsed")


if __name__ == "__main__":
    main()
