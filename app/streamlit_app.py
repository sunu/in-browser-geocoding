"""geoparse test UI.

Run: uv run streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import pydeck as pdk
import shapely
import streamlit as st
from shapely.geometry import shape

from geoparse.decisions.functions import Decider
from geoparse.execute.executor import Executor
from geoparse.parse.pipeline import Parser

ROOT = Path(__file__).resolve().parents[1]
PALETTE = [(31, 119, 180), (255, 127, 14), (44, 160, 44), (214, 39, 40), (148, 103, 189), (140, 86, 75),
           (227, 119, 194), (127, 127, 127), (188, 189, 34), (23, 190, 207)]

st.set_page_config(page_title="geoparse", layout="wide")


@st.cache_resource
def get_parser(provider: str) -> Parser:
    return Parser(Decider(default=None if provider == "config" else provider))


@st.cache_resource
def get_executor() -> Executor:
    return Executor()


@st.cache_data
def load_gold() -> dict[str, dict]:
    out = {}
    for name in ("gold", "heldout"):
        p = ROOT / "gold" / f"{name}.jsonl"
        if p.exists():
            for line in p.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    out[r["query"]] = r
    return out


def canon(dag):
    from gold.run_gold import canon as c

    return c(dag)


# ---------------------------------------------------------------- sidebar

gold = load_gold()
with st.sidebar:
    st.header("Settings")
    provider = st.radio("Decision provider", ["config", "local", "jev", "rules"], horizontal=True,
                        help="config: the provider of each decision from config.yaml (now local + rules). "
                             "local: the local cross-encoder for every decision. jev: TypeSafe Jev through "
                             "OpenRouter for every decision. rules: code only.")
    with_geometry = st.checkbox("Load geometry", value=True)
    st.divider()
    st.header("Examples")
    families = sorted({r["family"] for r in gold.values()})
    fam = st.selectbox("Family", ["(all)"] + families)
    examples = [q for q, r in gold.items() if fam == "(all)" or r["family"] == fam]
    example = st.selectbox("Gold query", [""] + examples)
    if st.button("Use example", disabled=not example):
        st.session_state["query"] = example

st.title("geoparse")
st.caption("Natural-language location query to geometry. India, English.")

tab_query, tab_dag = st.tabs(["Query", "DAG editor"])

# ---------------------------------------------------------------- helpers


def render_map(features, key: str):
    feats = [f for f in features if f.geometry]
    if not feats:
        st.info("No geometry to show.")
        return
    gj = {"type": "FeatureCollection", "features": []}
    for i, f in enumerate(feats):
        r, g, b = PALETTE[i % len(PALETTE)]
        gj["features"].append({"type": "Feature", "geometry": f.geometry,
                               "properties": {"name": f.name or "", "subtype": f.subtype or "", "source": f.source or "",
                                              "id": f.id or "", "fill": [r, g, b, 70], "line": [r, g, b, 230]}})
    geoms = [shape(f.geometry) for f in feats]
    x0, y0, x1, y1 = shapely.union_all(geoms).bounds
    span = max(x1 - x0, y1 - y0, 0.005)
    zoom = max(1.0, min(16.0, 8.5 - (span and __import__("math").log2(span))))
    layer = pdk.Layer(
        "GeoJsonLayer", gj, pickable=True, stroked=True, filled=True, get_fill_color="properties.fill",
        get_line_color="properties.line", line_width_min_pixels=1.5, point_radius_min_pixels=5,
        get_point_radius=30,
    )
    deck = pdk.Deck(layers=[layer], map_provider="carto", map_style="light",
                    initial_view_state=pdk.ViewState(longitude=(x0 + x1) / 2, latitude=(y0 + y1) / 2, zoom=zoom),
                    tooltip={"text": "{name}\n{subtype} ({source})\n{id}"})
    st.pydeck_chart(deck, height=560, key=key)


def render_result(res, key: str):
    if res is None:
        return
    if not res.ok:
        st.error(f"Execution error: {res.error}")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Result", res.kind)
    c2.metric("Features", len(res.features))
    c3.metric("Execute time", f"{res.timings.get('total_s', 0):.2f} s")
    for n in res.notes:
        st.warning(n)
    render_map(res.features, key)
    if res.features:
        st.dataframe(pd.DataFrame([{"name": f.name, "subtype": f.subtype, "source": f.source, "id": f.id}
                                   for f in res.features]), width="stretch", hide_index=True)
        st.download_button("Download GeoJSON", json.dumps(res.geojson()), file_name="geoparse.geojson",
                           mime="application/geo+json", key=f"dl-{key}")
    with st.expander(f"SQL ({len(res.sql)} statements)"):
        st.code("\n\n".join(s + ";" for s in res.sql), language="sql")


def trace_table(trace):
    rows = []
    for t in trace:
        v = t["value"]
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        opts = t.get("options")
        rows.append({
            "depth": t["depth"], "decision": t["decision"], "value": str(v)[:120],
            "confidence": t["confidence"], "threshold": t.get("threshold"),
            "below": t["confidence"] < (t.get("threshold") or 0) if t["decision"] != "extract_spans" else False,
            "impl": t["impl"], "latency_s": t["latency_s"],
            "options": ", ".join(opts) if isinstance(opts, list) else (", ".join(opts.keys()) if isinstance(opts, dict) else ""),
            "inputs": json.dumps(t.get("inputs"), ensure_ascii=False)[:160],
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- query tab

with tab_query:
    query = st.text_input("Query", key="query", placeholder="hospitals within 2 km of coastal districts of Odisha")
    run_clicked = st.button("Run", type="primary", disabled=not query)
    if run_clicked and query:
        parser = get_parser(provider)
        with st.spinner("Parsing"):
            p = parser.parse(query)
        res = None
        if p.ok and p.dag:
            with st.spinner("Executing"):
                res = get_executor().execute(p.dag, with_geometry=with_geometry)
        st.session_state["last"] = {"parse": p, "result": res, "provider": provider}

    last = st.session_state.get("last")
    if last:
        p, res = last["parse"], last["result"]
        jev = [t for t in p.trace if t["impl"] == "jev"]
        impls = sorted({t["impl"] for t in p.trace if t["decision"] not in ("extract_spans",)})
        cost = sum((t["trace"].get("cost") or 0) for t in jev)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Status", "OK" if p.ok else "Unsupported")
        c2.metric("Template", p.template or "-")
        c3.metric("Path", p.path or "-")
        c4.metric("Model calls", p.n_model_calls)
        c5.metric("Parse time", f"{p.timings.get('parse_s', 0):.2f} s", help=f"Jev cost ${cost:.6f}")
        st.caption("Decision implementations used: " + ", ".join(impls))
        if not p.ok:
            u = p.unsupported
            st.error(f"Unsupported: {u.reason}" + (f" (decision: {u.decision}, depth {u.depth}, text: '{u.text}')" if u.decision or u.text else ""))

        g = gold.get(p.query)
        if g:
            ok_dag = p.ok and canon(p.dag) == canon(g["dag"])
            (st.success if ok_dag else st.warning)(
                f"Gold record {g['id']}: template `{g['template']}`. DAG {'matches' if ok_dag else 'does not match'} the gold DAG.")

        t_map, t_parse, t_trace, t_dag = st.tabs(["Map", "Slots", "Decisions", "DAG"])
        with t_map:
            render_result(res, "q")
        with t_parse:
            st.json({"family": p.family, "template": p.template, "slots": p.slots})
            if g:
                st.caption("Gold")
                st.json({"family": g["family"], "template": g["template"], "slots": g["slots"]})
        with t_trace:
            df = trace_table(p.trace)
            if not df.empty:
                st.dataframe(df.style.apply(lambda r: ["background-color: #fde2e1" if r["below"] else "" for _ in r], axis=1),
                             width="stretch", hide_index=True)
                pick = st.selectbox("Details for decision", list(range(len(p.trace))),
                                    format_func=lambda i: f"{i}: {p.trace[i]['decision']} (depth {p.trace[i]['depth']})")
                st.json(p.trace[pick])
        with t_dag:
            if p.dag:
                st.json(p.dag)
                if st.button("Open in DAG editor"):
                    st.session_state["dag_text"] = json.dumps(p.dag, indent=2)

# ---------------------------------------------------------------- DAG editor tab

with tab_dag:
    st.caption("Edit a DAG (JSON) and execute it without the parser.")
    default = json.dumps({"op": "Filter", "args": {
        "set": {"op": "Children", "args": {"of": {"op": "Resolve", "args": {"name": "Odisha"}}, "level": "district"}},
        "pred": {"op": "Touches", "args": {"target": {"op": "Layer", "args": {"name": "coastline"}}}}}}, indent=2)
    text = st.text_area("DAG", value=st.session_state.get("dag_text", default), height=320)
    if st.button("Execute DAG"):
        try:
            dag = json.loads(text)
        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {e}")
        else:
            t0 = time.time()
            st.session_state["dag_result"] = get_executor().execute(dag, with_geometry=with_geometry)
    if st.session_state.get("dag_result") is not None:
        render_result(st.session_state["dag_result"], "dag")
