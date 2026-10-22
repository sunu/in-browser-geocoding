"""Connection to the local extract (geoparse.duckdb) and the gazetteer."""
from __future__ import annotations

import math
import re
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

import duckdb

from geoparse.config import build_dir, load_config
from geoparse.decisions.types import Candidate

# Ranking prior for each subtype (and locality class). A higher value ranks first.
SUBTYPE_PRIOR = {
    "country": 0.40, "region": 0.38, "county": 0.30, ("locality", "city"): 0.32, ("locality", "town"): 0.20,
    ("locality", None): 0.12, "macrohood": 0.16, "neighborhood": 0.10, "microhood": 0.06,
    ("locality", "village"): 0.02, ("locality", "hamlet"): 0.0,
}


def norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s.lower())).strip()


class Store:
    """Read-only access to geoparse.duckdb. One connection; cursors per thread."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else build_dir() / "geoparse.duckdb"
        if not self.path.exists():
            raise FileNotFoundError(f"{self.path} not found. Run: uv run python -m geoparse.data.build_extract")
        self._con = duckdb.connect(str(self.path), read_only=True)
        self._con.execute("LOAD spatial; SET geometry_always_xy = true;")
        self._local = threading.local()

    def cursor(self) -> duckdb.DuckDBPyConnection:
        c = getattr(self._local, "cur", None)
        if c is None:
            c = self._con.cursor()
            c.execute("LOAD spatial; SET geometry_always_xy = true;")
            self._local.cur = c
        return c

    def new_session(self) -> duckdb.DuckDBPyConnection:
        """A cursor for one execution. Temp tables live in it."""
        c = self._con.cursor()
        c.execute("LOAD spatial; SET geometry_always_xy = true;")
        return c

    # ------------------------------------------------------------ gazetteer

    def describe(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        if not ids:
            return {}
        rows = self.cursor().execute("""
            SELECT d.id, d.name, d.subtype, d.class, d.region, d.country, d.population,
                   [h.name FOR h IN list_filter(
                        (SELECT list(struct_pack(id := x.id, name := x.name, subtype := x.subtype))
                         FROM divisions x WHERE list_contains(d.ancestors, x.id) AND x.id <> d.id),
                        lambda h: h.subtype IN ('region', 'county', 'locality', 'macrohood'))] AS anc,
                   EXISTS (SELECT 1 FROM areas a WHERE a.id = d.id) AS has_area, d.ancestors
            FROM divisions d WHERE d.id IN (SELECT unnest(?))
        """, [ids]).fetchall()
        out = {}
        for id_, name, subtype, cls, region, country, pop, anc, has_area, anc_ids in rows:
            out[id_] = {"name": name, "subtype": subtype, "class": cls, "region": region, "country": country,
                        "population": pop, "ancestors": anc or [], "has_area": has_area,
                        "ancestor_ids": [a for a in (anc_ids or []) if a != id_]}
        return out

    def search(self, name: str, *, type_hint: str | None = None, context: str | None = None,
               limit: int = 8, fuzzy: bool = True) -> list[Candidate]:
        """Find Overture divisions by name. Exact (primary, English, alternate, no-space) first, then fuzzy."""
        n = norm_name(re.sub(r"^(the)\s+", "", name.strip(), flags=re.I))
        if not n:
            return []
        level_words = {"district", "state", "city", "town", "taluk", "village"}
        words = n.split()
        hint_from_name = None
        if len(words) > 1 and words[-1] in level_words:
            # "Pune district" -> name "pune", hint "district"
            hint_from_name = words[-1]
        cur = self.cursor()
        q_list = [n]
        if hint_from_name:
            q_list.append(" ".join(words[:-1]))
        rows = cur.execute("""
            SELECT id, max(CASE WHEN kind = 'primary' THEN 1.0 WHEN kind = 'en' THEN 0.98 ELSE 0.95 END) AS s
            FROM names WHERE name_norm IN (SELECT unnest(?)) OR name_nospace IN (SELECT replace(unnest(?), ' ', ''))
            GROUP BY id
        """, [q_list, q_list]).fetchall()
        scores = {r[0]: float(r[1]) for r in rows}
        if fuzzy and not scores and len(n) >= 4:
            rows = cur.execute("""
                SELECT n.id, max(jaro_winkler_similarity(n.name_norm, ?)) AS s
                FROM names n JOIN divisions d ON d.id = n.id
                WHERE d.subtype IN ('country', 'region', 'county', 'locality', 'macrohood', 'neighborhood')
                  AND coalesce(d.class, '') NOT IN ('hamlet')
                  AND n.name_norm[1] = ?[1]
                  AND jaro_winkler_similarity(n.name_norm, ?) >= 0.9
                  AND damerau_levenshtein(n.name_norm, ?) <= CASE WHEN length(?) >= 10 THEN 2 ELSE 1 END
                GROUP BY n.id ORDER BY s DESC LIMIT 50
            """, [n, n, n, n, n]).fetchall()
            scores = {r[0]: float(r[1]) * 0.9 for r in rows}
        if not scores:
            return []
        info = self.describe(list(scores))
        policy = load_config()["policy"]
        hint = type_hint or hint_from_name
        hint_subtypes = set()
        if hint:
            h = {"district": "district", "state": "state", "city": "city", "town": "city", "country": "country"}.get(hint, hint)
            hint_subtypes = set(policy["admin_levels"].get(h, []))
        ctx = norm_name(context) if context else ""
        cands = []
        for id_, s in scores.items():
            d = info.get(id_)
            if not d:
                continue
            if d["subtype"] == "region" and policy["require_region_code"] and not d["region"]:
                continue
            prior = SUBTYPE_PRIOR.get((d["subtype"], d["class"]), SUBTYPE_PRIOR.get(d["subtype"], 0.0))
            score = s + prior
            if d["has_area"]:
                score += 0.1
            if d["population"]:
                score += min(0.1, math.log10(max(d["population"], 1)) / 100)
            if hint_subtypes and d["subtype"] in hint_subtypes:
                score += 0.5
            if ctx and any(ctx in norm_name(a) or norm_name(a) in ctx for a in d["ancestors"]):
                score += 0.3
            if d["country"] != load_config()["data"]["country"]:
                score -= 0.2
            where = ", ".join(a for a in reversed(d["ancestors"][-2:])) if d["ancestors"] else ""
            kind = d["subtype"] if not d["class"] else f"{d['subtype']} ({d['class']})"
            desc = f"{d['name']}: {kind}" + (f" in {where}" if where else "") + ("" if d["country"] == "IN" else f", country {d['country']}")
            cands.append(Candidate(id=id_, name=d["name"], source="overture", subtype=d["subtype"],
                                   description=desc, score=round(score, 4), ancestors=d["ancestor_ids"]))
        cands.sort(key=lambda c: (-c.score, c.id))
        return cands[:limit]


@lru_cache(maxsize=4)
def get_store(path: str | None = None) -> Store:
    return Store(path)
