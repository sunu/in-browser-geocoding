"""Connection to the local extract (geoparse.duckdb) and the gazetteer."""
from __future__ import annotations

import math
import re
import threading
import unicodedata
from functools import lru_cache
from pathlib import Path
from collections.abc import Sequence
from typing import Any

import duckdb

from geoparse.config import build_dir, country_policy, load_config
from geoparse.decisions.types import Candidate

# Score of a name match for each name kind.
KIND_SCORE = "CASE WHEN kind = 'primary' THEN 1.0 WHEN kind = 'en' THEN 0.98 WHEN kind = 'translit' THEN 0.9 ELSE 0.95 END"
# Fuzzy search compares only keys with the same first characters (no spaces).
FUZZY_PREFIX = 3

# Ranking prior for each subtype (and locality class). A higher value ranks first.
SUBTYPE_PRIOR = {
    "country": 0.40, "region": 0.38, "county": 0.30, ("locality", "city"): 0.32, ("locality", "town"): 0.20,
    ("locality", None): 0.12, "macrohood": 0.16, "neighborhood": 0.10, "microhood": 0.06,
    ("locality", "village"): 0.02, ("locality", "hamlet"): 0.0,
}


@lru_cache(maxsize=1)
def name_aliases() -> dict[str, str]:
    import yaml

    from geoparse.config import PACKAGE_DIR

    raw = yaml.safe_load((PACKAGE_DIR / "data" / "name_aliases.yaml").read_text()) or {}
    return {norm_name(k): norm_name(v) for k, v in raw.items()}


# Latin letters that NFKD does not split into a base letter and a mark.
NAME_FOLD = {"ł": "l", "ø": "o", "đ": "d", "ð": "d", "ħ": "h", "ı": "i", "ŀ": "l", "ß": "ss", "æ": "ae", "œ": "oe", "þ": "th"}
_GENERIC_MARKS = re.compile("[̀-ͯ]")


def norm_name(s: str) -> str:
    """Name key for the gazetteer. web/src/core/text.ts normName must give the same result.

    Removes the generic diacritics (U+0300 to U+036F) only. Script-specific marks (for example the
    vowel signs of Devanagari and Thai) stay. All characters other than letters, marks and digits
    become a space.
    """
    s = unicodedata.normalize("NFKD", s.lower())
    s = unicodedata.normalize("NFC", _GENERIC_MARKS.sub("", s))
    s = "".join(NAME_FOLD.get(c, c) if unicodedata.category(c)[0] in "LMN" else " " for c in s)
    return " ".join(s.split())


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
        """A cursor for one execution. Temp tables live in it. The world point datasets (poi/*.parquet next to
        the database) are views `poi_<name>`."""
        c = self._con.cursor()
        c.execute("LOAD spatial; SET geometry_always_xy = true;")
        for f in sorted((self.path.parent / "poi").glob("*.parquet")):
            c.execute(f"CREATE TEMP VIEW poi_{f.stem} AS SELECT * FROM read_parquet('{f}')")
        return c

    # ------------------------------------------------------------ gazetteer

    def describe(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        if not ids:
            return {}
        rows = self.cursor().execute("""
            SELECT d.id, d.name, d.subtype, d.class, d.region, d.country, d.population,
                   [h.name FOR h IN list_filter(
                        (SELECT list(struct_pack(id := x.id, name := x.name, subtype := x.subtype)
                                    ORDER BY list_position(d.ancestors, x.id) DESC)
                         FROM divisions x WHERE list_contains(d.ancestors, x.id) AND x.id <> d.id),
                        lambda h: h.subtype IN ('region', 'county', 'locality', 'macrohood'))] AS anc,
                   EXISTS (SELECT 1 FROM areas a WHERE a.id = d.id) AS has_area, d.ancestors,
                   ST_X(d.geometry) AS lon, ST_Y(d.geometry) AS lat
            FROM divisions d WHERE d.id IN (SELECT unnest(?))
        """, [ids]).fetchall()
        out = {}
        for id_, name, subtype, cls, region, country, pop, anc, has_area, anc_ids, lon, lat in rows:
            out[id_] = {"name": name, "subtype": subtype, "class": cls, "region": region, "country": country,
                        "population": pop, "ancestors": anc or [], "has_area": has_area, "lon": lon, "lat": lat,
                        "ancestor_ids": [a for a in (anc_ids or []) if a != id_]}
        return out

    def view(self, view: Sequence[float] | None, cfg: dict[str, Any]) -> tuple[Sequence[float], str | None]:
        """Map view (xmin, ymin, xmax, ymax) and the country of its center. No view: data.bbox and data.country."""
        if not view:
            return cfg["data"]["bbox"], cfg["data"]["country"]
        cx, cy = (view[0] + view[2]) / 2, (view[1] + view[3]) / 2
        row = self.cursor().execute("""
            SELECT country FROM divisions WHERE subtype IN ('country', 'dependency', 'region') AND country IS NOT NULL
            ORDER BY (ST_X(geometry) - ?) ** 2 + (ST_Y(geometry) - ?) ** 2, id LIMIT 1""", [cx, cy]).fetchone()
        return view, row[0] if row else None

    def match_points(self, ids: list[str], points: list[tuple[float, float]]) -> dict[str, int]:
        """For each division id, the first point (1-based rank) inside its area, or near its point (less than the
        point_area_radius_m of its subtype)."""
        if not ids or not points:
            return {}
        radii = load_config()["policy"].get("point_area_radius_m", {})
        cases = " ".join(f"WHEN '{k}' THEN {float(v)}" for k, v in radii.items() if k != "default")
        radius = f"(CASE d.subtype {cases} ELSE {float(radii.get('default', 1000))} END)" if cases else str(float(radii.get("default", 1000)))
        rows = self.cursor().execute(f"""
            WITH p AS (SELECT unnest(?) AS rk, unnest(?) AS lon, unnest(?) AS lat)
            SELECT d.id, min(p.rk) FROM divisions d CROSS JOIN p LEFT JOIN areas a ON a.id = d.id
            WHERE d.id IN (SELECT unnest(?))
              AND ((a.gs IS NOT NULL AND ST_Contains(a.gs::GEOMETRY, ST_Point(p.lon, p.lat)))
                   OR ST_Distance_Sphere(ST_Point(ST_X(d.geometry), ST_Y(d.geometry)), ST_Point(p.lon, p.lat)) <= {radius})
            GROUP BY d.id""", [list(range(1, len(points) + 1)), [p[0] for p in points], [p[1] for p in points], ids]).fetchall()
        return {r[0]: int(r[1]) for r in rows}

    def search(self, name: str, *, type_hint: str | None = None, context: str | None = None,
               limit: int = 8, fuzzy: bool = True, view: Sequence[float] | None = None) -> list[Candidate]:
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
        # Short forms and old names (data file).
        aliases = name_aliases()
        for x in list(q_list):
            ws = x.split()
            for i, w in enumerate(ws):
                if w in aliases:
                    q_list.append(" ".join(ws[:i] + [aliases[w]] + ws[i + 1:]))
            if x in aliases:
                q_list.append(aliases[x])
        # The key is the name without spaces (the key of the web name shards). It gives the matches of
        # "name_norm OR name_nospace".
        rows = cur.execute(f"""
            SELECT id, max({KIND_SCORE}) AS s FROM names WHERE name_nospace IN (SELECT replace(unnest(?), ' ', ''))
            GROUP BY id
        """, [q_list]).fetchall()
        scores = {r[0]: float(r[1]) for r in rows}
        if not scores:
            # Fallback: Overture names can end with a level word ("Mumbai Suburban District").
            q2 = [f"{x} {suffix}" for x in q_list for suffix in ("district", "city")]
            rows = cur.execute(f"""
                SELECT id, max({KIND_SCORE}) AS s FROM names WHERE name_nospace IN (SELECT replace(unnest(?), ' ', ''))
                GROUP BY id
            """, [q2]).fetchall()
            scores = {r[0]: float(r[1]) * 0.98 for r in rows}
        if fuzzy and not scores and len(n) >= 4:
            # Keys with the same first FUZZY_PREFIX characters (one or a few web name shards). The similarity is
            # multiplied by the score of the name kind, so that a transliteration does not win over a primary name.
            nk = n.replace(" ", "")
            rows = cur.execute(f"""
                SELECT n.id, max(jaro_winkler_similarity(n.name_nospace, $nk) * {KIND_SCORE}) AS s
                FROM names n JOIN divisions d ON d.id = n.id
                WHERE d.subtype IN ('country', 'region', 'county', 'locality', 'macrohood', 'neighborhood')
                  AND coalesce(d.class, '') NOT IN ('hamlet')
                  AND left(n.name_nospace, {FUZZY_PREFIX}) = left($nk, {FUZZY_PREFIX})
                  AND jaro_winkler_similarity(n.name_nospace, $nk) >= 0.85
                  AND damerau_levenshtein(n.name_nospace, $nk) <= CASE WHEN length($nk) >= 10 THEN 2 ELSE 1 END
                GROUP BY n.id ORDER BY s DESC, n.id LIMIT 50
            """, {"nk": nk}).fetchall()
            scores = {r[0]: float(r[1]) * 0.9 for r in rows}
        if not scores:
            return []
        info = self.describe(list(scores))
        cfg = load_config()
        ranking = cfg["policy"]["ranking"]
        (x0, y0, x1, y1), view_country = self.view(view, cfg)
        hint = type_hint or hint_from_name
        h = {"district": "district", "state": "state", "city": "city", "town": "city", "country": "country",
             "union_territory": "union_territory"}.get(hint, hint) if hint else None
        ctx = norm_name(context) if context else ""
        cands = []
        for id_, s in scores.items():
            d = info.get(id_)
            if not d:
                continue
            policy = country_policy(cfg["policy"], d["country"])
            if d["subtype"] == "region" and policy["require_region_code"] and not d["region"]:
                continue
            prior = SUBTYPE_PRIOR.get((d["subtype"], d["class"]), SUBTYPE_PRIOR.get(d["subtype"], 0.0))
            score = s + prior
            if d["has_area"]:
                score += 0.1
            if d["population"]:
                score += min(0.1, math.log10(max(d["population"], 1)) / 100)
            if h and d["subtype"] in policy["admin_levels"].get(h, []):
                score += 0.5
            if ctx and any(ctx in norm_name(a) or norm_name(a) in ctx for a in d["ancestors"]):
                score += 0.3
            if d["lon"] is None or not (x0 <= d["lon"] <= x1 and y0 <= d["lat"] <= y1):
                score -= ranking["view_outside"]
            if d["country"] != view_country:
                score -= ranking["view_other_country"]
            where = ", ".join(a for a in reversed(d["ancestors"][-2:])) if d["ancestors"] else ""
            kind = d["subtype"] if not d["class"] else f"{d['subtype']} ({d['class']})"
            desc = f"{d['name']}: {kind}" + (f" in {where}" if where else "") + ("" if d["country"] == view_country else f", country {d['country']}")
            cands.append(Candidate(id=id_, name=d["name"], source="overture", subtype=d["subtype"],
                                   description=desc, score=round(score, 4), ancestors=d["ancestor_ids"]))
        cands.sort(key=lambda c: (-c.score, c.id))
        return cands[:limit]


@lru_cache(maxsize=4)
def get_store(path: str | None = None) -> Store:
    return Store(path)
