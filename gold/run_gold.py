"""Gold suite runner.

Scores each decision function alone (with gold inputs), and the full pipeline.
Reports accuracy per decision, per family, and per depth, plus latency and model calls.

Usage:
  uv run python -m gold.run_gold --provider rules
  uv run python -m gold.run_gold --provider jev --jev-mode cached
  options: --execute (compare executed results with expected_ids), --limit N, --only g001,g002
  GEOPARSE_SCOPE=world uv run python -m gold.run_gold --provider config --setup web --set world --execute
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from geoparse.config import REPO_ROOT
from geoparse.decisions.functions import Decider
from geoparse.decisions.log import DecisionLogger
from geoparse.options import norm
from geoparse.parse.pipeline import Parser, normalize_query
from geoparse.templates.model import CLOSED_TYPES, OPEN_TYPES, all_templates

GOLD = Path(__file__).resolve().parent / "gold.jsonl"
REPORTS = REPO_ROOT / "reports"


def ntext(s: str) -> str:
    return re.sub(r"^(the|a|an) ", "", norm(s))


def open_text(v: Any) -> str:
    if isinstance(v, dict):
        return v.get("text") or v.get("q") or ""
    if isinstance(v, list):
        return " and ".join(open_text(x) for x in v)
    return v


LIST_LEAD = re.compile(r"^(both|either|all of the|all of|each of|any one of|any of) ")


def list_text_ok(seg: str, names: list[str]) -> bool:
    """A slot text that holds the gold list: the names in order, from the first to the last (plan-036)."""
    n = LIST_LEAD.sub("", ntext(seg))
    parts = [ntext(open_text(x)) for x in names]
    pos = 0
    for p in parts:
        i = n.find(p, pos)
        if i < 0:
            return False
        pos = i + len(p)
    return n.startswith(parts[0]) and n.endswith(parts[-1])


# ---------------------------------------------------------------- comparisons


def slots_equal(t: str, got: dict[str, Any], gold: dict[str, Any]) -> tuple[bool, list[str]]:
    tpl = all_templates()[t]
    diffs = []
    for name, sd in tpl.slots.items():
        g = gold.get(name, sd.default)
        r = got.get(name, sd.default)
        if sd.type in OPEN_TYPES:
            if g is None and r is None:
                continue
            if isinstance(g, dict) and "q" in g:
                if not (isinstance(r, dict) and "t" in r and r["t"] == g["t"]):
                    diffs.append(f"{name}: expected sub-query {g['t']}, got {r!r}")
                    continue
                ok, d = slots_equal(g["t"], r["s"], g["s"])
                if not ok:
                    diffs += [f"{name}.{x}" for x in d]
            elif isinstance(g, dict) and "lex" in g:
                if not (isinstance(r, dict) and r.get("lex") == g["lex"]):
                    diffs.append(f"{name}: expected lexicon {g['lex']}, got {r!r}")
            elif isinstance(g, list):
                got = r["list"] if isinstance(r, dict) and "list" in r else None
                if got is None or len(got) != len(g):
                    diffs.append(f"{name}: expected list {g!r}, got {r!r}")
                    continue
                for i, (gx, rx) in enumerate(zip(g, got)):
                    # A part of a list is a name or a sub-query (plan-038: "Kerala and coastal districts of Karnataka").
                    if isinstance(gx, dict) and "q" in gx:
                        if not (isinstance(rx, dict) and rx.get("t") == gx["t"]):
                            diffs.append(f"{name}[{i}]: expected sub-query {gx['t']}, got {rx!r}")
                        else:
                            diffs += [f"{name}[{i}].{x}" for x in slots_equal(gx["t"], rx["s"], gx["s"])[1]]
                    elif ntext(open_text(rx)) != ntext(open_text(gx)):
                        diffs.append(f"{name}[{i}]: expected {gx!r}, got {rx!r}")
            else:
                if not isinstance(r, str) or ntext(r) != ntext(g):
                    diffs.append(f"{name}: expected {g!r}, got {r!r}")
        elif sd.type in ("distance", "value"):
            g, r = (None if isinstance(x, str) and x.startswith("policy.") else x for x in (g, r))
            if (g is None) != (r is None) or (g is not None and abs(float(g) - float(r)) > 1e-6):
                diffs.append(f"{name}: expected {g!r}, got {r!r}")
        elif g != r:
            diffs.append(f"{name}: expected {g!r}, got {r!r}")
    return not diffs, diffs


def canon(dag: Any, unordered: bool = False) -> Any:
    """unordered: the order of the parts of a union does not count (the gold comparison; the reference keeps it)."""
    if isinstance(dag, dict) and "op" in dag:
        a = dag.get("args", {})
        if dag["op"] == "Resolve":
            if a.get("source") == "photon":
                return ["Resolve", "photon", ntext(a["name"])]
            return ["Resolve", a.get("id") or ntext(a["name"])]
        if unordered and dag["op"] == "Union":
            parts, todo = [], [dag]
            while todo:
                x = todo.pop()
                if isinstance(x, dict) and x.get("op") == "Union":
                    todo += [x["args"]["a"], x["args"]["b"]]
                else:
                    parts.append(canon(x, True))
            return ["Union", sorted(parts, key=json.dumps)]
        return [dag["op"], {k: canon(v, unordered) for k, v in sorted(a.items()) if k not in ("type_hint", "context")}]
    return dag


# ---------------------------------------------------------------- isolated decisions


def gold_match(parser: Parser, text: str, t: str, slots: dict[str, Any]) -> dict[str, Any] | None:
    tpl = all_templates()[t]
    cands = parser.candidates(text).get(t, [])
    for m in cands:
        seg_of = {s: seg for seg, fed in m["feeds"].items() for s in fed}
        ok = True
        for name, sd in tpl.slots.items():
            if sd.type in OPEN_TYPES:
                if name not in seg_of or slots.get(name) is None:
                    if (name in seg_of) != (slots.get(name) is not None):
                        ok = False
                        break
                    continue
                gold_v = slots[name]
                if isinstance(gold_v, list):
                    if not list_text_ok(m["segments"][seg_of[name]], gold_v):
                        ok = False
                        break
                elif ntext(m["segments"][seg_of[name]]) != ntext(open_text(gold_v)):
                    ok = False
                    break
        if ok:
            return m
    return None


def eval_isolated(parser: Parser, dec: Decider, rec: dict[str, Any], text: str, t: str, slots: dict[str, Any],
                  src: dict[str, str], depth: int, family: str, out: list[dict[str, Any]], flat: bool) -> None:
    templates = all_templates()
    tpl = templates[t]

    def add(decision, correct, **kw):
        out.append({"id": rec["id"], "decision": decision, "depth": depth, "family": family, "correct": bool(correct), **kw})

    cands = parser.candidates(text)
    spans = []
    tfam = {tid: templates[tid].family for tid in cands}
    tscores = {tid: max(m["score"] for m in ms) for tid, ms in cands.items() if ms}
    ctx = {"template_scores": tscores, "template_family": tfam}
    if not parser.prune:
        # No pattern pruning: the model sees every family and every template.
        cands = {tid: cands.get(tid, []) for tid in templates}
        tfam = {tid: templates[tid].family for tid in cands}
    fams = {f: parser.families[f].description for f in parser.families if any(tfam[x] == f for x in cands)}
    if family not in fams:
        add("pick_family", False, coverage_miss=True, got=None, gold=family)
    else:
        d = dec.pick_family(text, spans, fams, depth=depth, context=ctx)
        add("pick_family", d.value == family, got=d.value, gold=family, conf=d.confidence, n_options=len(fams))
    topts = {tid: parser._template_option(tid) for tid in cands if tfam[tid] == family}
    if t not in topts:
        add("pick_template", False, coverage_miss=True, got=None, gold=t)
    else:
        d = dec.pick_template(text, spans, family, topts, depth=depth, context=ctx)
        add("pick_template", d.value == t, got=d.value, gold=t, conf=d.confidence, n_options=len(topts))
    if flat:
        allopts = {tid: parser._template_option(tid) for tid in cands}
        if t not in allopts:
            add("pick_template_flat", False, coverage_miss=True, got=None, gold=t)
        else:
            d = dec.pick_template_flat(text, spans, allopts, depth=depth, context=ctx)
            add("pick_template_flat", d.value == t, got=d.value, gold=t, conf=d.confidence, n_options=len(allopts))

    gm = gold_match(parser, text, t, slots)
    matches = cands.get(t, [])
    if gm is None:
        add("pick_split", False, coverage_miss=True, gold={k: open_text(v) for k, v in slots.items()})
    else:
        from geoparse.decisions.types import Split

        splits = [Split(parts=m["segments"]) for m in matches]
        d = dec.pick_split(text, tpl.description, splits, depth=depth, labels=parser._labels(tpl, matches[0]),
                           context={"split_scores": {f"s{i}": m["score"] for i, m in enumerate(matches)}})
        add("pick_split", split_key(tpl, d.value.parts, matches) == split_key(tpl, gm["segments"], matches),
            got=d.value.parts, gold=gm["segments"],
            conf=d.confidence, n_options=len(splits))
        seg_of = {s: seg for seg, fed in gm["feeds"].items() for s in fed}
        for name, sd in tpl.slots.items():
            if sd.type in CLOSED_TYPES and name in seg_of:
                seg = gm["segments"][seg_of[name]]
                d = dec.fill_closed_slot(seg, sd.type, sd.options_ref, depth=depth, query=text, allow_none=sd.optional)
                add(f"fill_closed_slot.{sd.type}", d.value == slots.get(name, sd.default), got=d.value,
                    gold=slots.get(name, sd.default), text=seg, conf=d.confidence)

    for name, sd in tpl.slots.items():
        if sd.type == "region" and tpl.family != "lookup":
            v = slots.get(name)
            if v is None or (isinstance(v, dict) and "lex" in v) or isinstance(v, list):
                # A list is found by a rule before the model (plan-036): no is_subquery question.
                continue
            gold_sub = isinstance(v, dict) and "q" in v
            txt = re.sub(r"^(the|a|an)\s+", "", open_text(v), flags=re.I)
            exact = parser.store.search(txt, fuzzy=False, limit=1, view=rec.get("view"))
            d = dec.is_subquery(txt, depth=depth, context={"gazetteer_exact": bool(exact),
                                                           "has_distance": bool(re.search(r"\d", txt))})
            add("is_subquery", d.value == gold_sub, got=d.value, gold=gold_sub, text=txt, conf=d.confidence)
            if gold_sub:
                eval_isolated(parser, dec, rec, v["q"], v["t"], v["s"], {}, depth + 1, templates[v["t"]].family, out, flat)
        if name in src:
            txt = open_text(slots[name])
            cands_g = parser.store.search(txt, limit=1, view=rec.get("view"))
            top = cands_g[0] if cands_g else None
            d = dec.select_source(txt, {"gazetteer_match": top.description if top else None,
                                        "gazetteer_top_score": top.score if top else 0.0}, depth=depth)
            add("select_source", d.value == src[name], got=d.value, gold=src[name], text=txt, conf=d.confidence)


def split_key(tpl, parts: dict[str, str], matches: list[dict[str, Any]]) -> tuple:
    """The texts of the open and parsed slots of a split. Closed-slot grouping is not compared."""
    m = next(m for m in matches if m["segments"] == parts)
    seg_of = {s: seg for seg, fed in m["feeds"].items() for s in fed}
    return tuple(sorted((name, ntext(parts[seg_of[name]])) for name, sd in tpl.slots.items()
                        if name in seg_of and sd.type not in CLOSED_TYPES))


# ---------------------------------------------------------------- execution


def exec_compare(rec: dict[str, Any], dag: dict[str, Any], ex) -> tuple[bool | None, str]:
    if rec["expected_ids"] is None:
        return None, "needs network"
    res = ex.execute(dag, with_geometry="expected_geometry" in rec, view=rec.get("view"))
    if not res.ok:
        return False, res.error or ""
    if rec.get("expected_geometry"):
        from gold.build_gold import geometry_summary

        g = geometry_summary(res)
        e = rec["expected_geometry"]
        if g is None:
            return False, "empty geometry"
        ok = abs(g["area_km2"] - e["area_km2"]) <= 0.05 * max(e["area_km2"], 1e-6) and \
            abs(g["centroid"][0] - e["centroid"][0]) < 0.02 and abs(g["centroid"][1] - e["centroid"][1]) < 0.02
        return ok, f"area {g['area_km2']} vs {e['area_km2']}"
    return sorted(res.ids) == sorted(rec["expected_ids"]), f"{len(res.ids)} ids vs {len(rec['expected_ids'])}"


# ---------------------------------------------------------------- main


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f}% ({a}/{b})" if b else "-"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="rules")
    ap.add_argument("--jev-mode", default="cached")
    ap.add_argument("--jev-cache", default=str(REPO_ROOT / "tests" / "fixtures" / "jev_cache.jsonl"))
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only")
    ap.add_argument("--no-isolated", action="store_true")
    ap.add_argument("--no-flat", action="store_true")
    ap.add_argument("--no-ner", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tag", default="")
    ap.add_argument("--set", default="gold", help="gold, heldout, india_ref, world or world_heldoutN (world sets: GEOPARSE_SCOPE=world)")
    ap.add_argument("--setup", choices=["default", "web"], default="default",
                    help="web: as the browser version (T5 frames only, no split patterns, no NER)")
    ap.add_argument("--no-prune", action="store_true", help="the model sees every family and template")
    args = ap.parse_args()

    path = GOLD.parent / f"{args.set}.jsonl"
    recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    if args.only:
        keep = set(args.only.split(","))
        recs = [r for r in recs if r["id"] in keep]
    if args.limit:
        recs = recs[: args.limit]

    logger = DecisionLogger()
    # "config" uses the provider of each decision from the config file.
    base = Decider(default=None if args.provider == "config" else args.provider, logger=logger,
                   use_ner=not args.no_ner and args.setup != "web", jev_mode=args.jev_mode,
                   jev_cache=args.jev_cache)
    web = {"use_t5": True, "use_patterns": "never"} if args.setup == "web" else {}
    parser = Parser(base, prune_by_pattern=not args.no_prune, **web)
    # Warm up GLiNER and the store so that the first query does not carry the load time.
    parser.parse("Kerala")

    iso: list[dict[str, Any]] = []
    if not args.no_isolated:
        def one_iso(rec):
            out: list[dict[str, Any]] = []
            if rec["dag"] is None:
                return out
            dec = base.fork()
            dec.view_country = parser.store.view(rec.get("view"), parser.cfg)[1]
            dec.data_level_words = parser.store.level_words(dec.view_country)
            eval_isolated(parser, dec, rec, normalize_query(rec["query"]), rec["template"], rec["slots"],
                          rec.get("src", {}), 0, rec["family"], out, not args.no_flat)
            return out

        with ThreadPoolExecutor(args.workers) as pool:
            for out in pool.map(one_iso, recs):
                iso += out

    ex = None
    if args.execute:
        from geoparse.execute.executor import Executor

        ex = Executor()

    pipe: list[dict[str, Any]] = []

    def one_pipe(rec):
        t0 = time.time()
        p = parser.parse(rec["query"], view=rec.get("view"))
        dt = time.time() - t0
        row = {"id": rec["id"], "query": rec["query"], "family": rec["family"], "depth": rec["depth"],
               "template_ok": p.template == rec["template"], "ok": p.ok, "latency_s": dt,
               "model_calls": p.n_model_calls,
               "requests_in_sequence": sequential_requests(p.trace),
               "unsupported": p.unsupported.model_dump() if p.unsupported else None,
               "got_template": p.template, "path": p.path}
        if rec["dag"] is None:
            # A query that the parser must refuse: correct if the parse is not ok.
            row["template_ok"] = row["slots_ok"] = row["dag_ok"] = not p.ok
            if ex is not None:
                row["exec_ok"] = not p.ok
        elif p.ok:
            sok, diffs = slots_equal(rec["template"], p.slots, rec["slots"]) if p.template == rec["template"] else (False, ["template"])
            row["slots_ok"] = sok
            row["diffs"] = diffs
            row["dag_ok"] = canon(p.dag, True) == canon(rec["dag"], True)
            if ex is not None:
                row["exec_ok"], row["exec_note"] = exec_compare(rec, p.dag, ex)
        else:
            row["slots_ok"] = row["dag_ok"] = False
            if ex is not None and rec["expected_ids"] is not None:
                row["exec_ok"] = False
        return row

    with ThreadPoolExecutor(args.workers) as pool:
        pipe = list(pool.map(one_pipe, recs))

    report = summarize(iso, pipe, recs, args)
    tag = (f"{args.set}-" if args.set != "gold" else "") + args.provider + ("-web" if args.setup == "web" else "") + (
        f"-{args.tag}" if args.tag else "")
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"gold-{tag}.json").write_text(json.dumps({"isolated": iso, "pipeline": pipe, "summary": report["summary"]},
                                                         indent=1, default=str))
    (REPORTS / f"gold-{tag}.md").write_text(report["markdown"])
    print(report["markdown"])


def sequential_requests(trace: list[dict[str, Any]]) -> int:
    """Approximate number of model requests in sequence: calls at the same depth and stage run in parallel."""
    stages = []
    for t in trace:
        if t["impl"] in ("deterministic",) or t["decision"] == "extract_spans":
            continue
        stage = (t["depth"], {"pick_family": 0, "pick_template": 1, "pick_template_flat": 1, "pick_split": 2}.get(
            t["decision"], 3))
        stages.append(stage)
    return len(set(stages))


def summarize(iso, pipe, recs, args) -> dict[str, Any]:
    lines = [f"# Gold suite `{args.set}`: provider `{args.provider}`", ""]
    lines.append(f"Records: {len(recs)}. Depth 0: {sum(r['depth'] == 0 for r in recs)}. Depth 1 (two levels): "
                 f"{sum(r['depth'] == 1 for r in recs)}.")
    lines.append("")
    summary: dict[str, Any] = {}

    if iso:
        lines += ["## Decisions alone (gold inputs)", "", "| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |",
                  "|---|---|---|---|---|---|"]
        by = defaultdict(list)
        for r in iso:
            key = r["decision"] if not r["decision"].startswith("fill_closed_slot") else r["decision"]
            by[key].append(r)
        order = ["pick_family", "pick_template", "pick_template_flat", "pick_split", "is_subquery", "select_source"]
        keys = [k for k in order if k in by] + sorted(k for k in by if k not in order)
        for k in keys:
            rs = by[k]
            c = sum(r["correct"] for r in rs)
            d0 = [r for r in rs if r["depth"] == 0]
            d1 = [r for r in rs if r["depth"] >= 1]
            cm = sum(1 for r in rs if r.get("coverage_miss"))
            confs = [r["conf"] for r in rs if "conf" in r]
            lines.append(f"| {k} | {pct(c, len(rs))} | {pct(sum(r['correct'] for r in d0), len(d0))} | "
                         f"{pct(sum(r['correct'] for r in d1), len(d1))} | {cm} | "
                         f"{statistics.mean(confs):.2f} |" if confs else f"| {k} | {pct(c, len(rs))} | | | {cm} | - |")
            summary[k] = {"n": len(rs), "correct": c}
        lines.append("")
        errs = [r for r in iso if not r["correct"]]
        if errs:
            lines += ["### Errors in decisions alone", "", "| Gold id | Decision | Depth | Gold | Got | Confidence |", "|---|---|---|---|---|---|"]
            for r in errs:
                lines.append(f"| {r['id']} | {r['decision']} | {r['depth']} | {_short(r.get('gold'))} | {_short(r.get('got'))} | "
                             f"{r.get('conf', '-') if not r.get('coverage_miss') else 'coverage miss'} |")
            lines.append("")

    lines += ["## Full pipeline", "", "| Family | Template | Slots | DAG | Unsupported |" + (" Executed result |" if args.execute else ""),
              "|---|---|---|---|---|" + ("---|" if args.execute else "")]
    fams = sorted({r["family"] for r in pipe})
    for f in fams + ["ALL"]:
        rs = [r for r in pipe if f == "ALL" or r["family"] == f]
        row = (f"| {f} | {pct(sum(r['template_ok'] for r in rs), len(rs))} | {pct(sum(r['slots_ok'] for r in rs), len(rs))} | "
               f"{pct(sum(r['dag_ok'] for r in rs), len(rs))} | {sum(not r['ok'] for r in rs)} |")
        if args.execute:
            ers = [r for r in rs if r.get("exec_ok") is not None]
            row += f" {pct(sum(bool(r['exec_ok']) for r in ers), len(ers))} |"
        lines.append(row)
        summary.setdefault("pipeline", {})[f] = {"n": len(rs), "dag_ok": sum(r["dag_ok"] for r in rs)}
    lines.append("")
    lines += ["### By depth", "", "| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |", "|---|---|---|---|---|"]
    for d in sorted({r["depth"] for r in pipe}):
        rs = [r for r in pipe if r["depth"] == d]
        lines.append(f"| {d} | {pct(sum(r['dag_ok'] for r in rs), len(rs))} | {statistics.median(r['latency_s'] for r in rs):.2f} s | "
                     f"{statistics.mean(r['model_calls'] for r in rs):.1f} | {statistics.mean(r['requests_in_sequence'] for r in rs):.1f} |")
    lines.append("")
    bad = [r for r in pipe if not r["dag_ok"]]
    if bad:
        lines += ["### Pipeline errors", "", "| Gold id | Query | Got template | Problem |", "|---|---|---|---|"]
        for r in bad:
            prob = r["unsupported"]["reason"] if r["unsupported"] else "; ".join(r.get("diffs") or []) or "DAG differs"
            lines.append(f"| {r['id']} | {r['query']} | {r['got_template']} | {_short(prob, 120)} |")
        lines.append("")
    if args.execute:
        ebad = [r for r in pipe if r.get("exec_ok") is False and r["dag_ok"]]
        if ebad:
            lines += ["### Execution differences with a correct DAG", ""]
            lines += [f"- {r['id']} {r['query']}: {r.get('exec_note')}" for r in ebad]
            lines.append("")

    pairs = Counter()
    for r in recs:
        for v in r["slots"].values():
            if isinstance(v, dict) and "q" in v:
                pairs[(r["template"], v["t"])] += 1
    if pairs:
        lines += ["### Nested template pairs in the gold suite", "", "| Outer | Inner | Count |", "|---|---|---|"]
        lines += [f"| {a} | {b} | {n} |" for (a, b), n in pairs.most_common()]
        lines.append("")
    return {"summary": summary, "markdown": "\n".join(lines)}


def _short(v: Any, n: int = 70) -> str:
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    s = s.replace("|", "/")
    return s if len(s) <= n else s[: n - 3] + "..."


if __name__ == "__main__":
    main()
