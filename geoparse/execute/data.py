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

# Level words at the end of region names that have no short form ("Kyoto Prefecture"). The search also tries
# "<name> <suffix>".
REGION_SUFFIXES = ("prefecture", "province")
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


def plural(word: str) -> str:
    """English plural of the last word ("county" -> "counties", "federal subject" -> "federal subjects")."""
    if re.search(r"[^aeiou]y$", word):
        return word[:-1] + "ies"
    return word + ("es" if re.search(r"(s|x|z|ch|sh)$", word) else "s")


def local_level_words(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, list[str]]]:
    """Admin level words of each country from the Overture `local_type` of its regions (level `state`) and
    counties (level `district`): the values of at least policy.local_type_min_share of the rows, singular and
    plural. The words of policy.local_type_skip are not used."""
    pol = load_config()["policy"]
    skip = set(pol["local_type_skip"])
    rows = con.execute("""
        SELECT country, subtype, w, n / sum(n) OVER (PARTITION BY country, subtype)
        FROM (SELECT country, subtype, lower(trim(local_type)) AS w, count(*) AS n FROM divisions
              WHERE subtype IN ('region', 'county') AND country IS NOT NULL AND local_type IS NOT NULL GROUP BY 1, 2, 3)
        ORDER BY 1, 2, 3""").fetchall()
    out: dict[str, dict[str, list[str]]] = {}
    for cc, subtype, w, share in rows:
        if share >= pol["local_type_min_share"] and w and w not in skip:
            out.setdefault(cc, {}).setdefault("state" if subtype == "region" else "district", []).extend([w, plural(w)])
    return out


class Store:
    """Read-only access to geoparse.duckdb. One connection; cursors per thread."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else build_dir() / "geoparse.duckdb"
        if not self.path.exists():
            raise FileNotFoundError(f"{self.path} not found. Run: uv run python -m geoparse.data.build_extract")
        self._con = duckdb.connect(str(self.path), read_only=True)
        self._con.execute("LOAD spatial; SET geometry_always_xy = true;")
        self._local = threading.local()
        self._level_words: dict[str, dict[str, list[str]]] | None = None
        self._extents: dict[str, tuple[float, ...]] | None = None

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

    def level_words(self, country: str | None) -> dict[str, list[str]]:
        """Admin level words of one country from the data (local_level_words)."""
        if self._level_words is None:
            self._level_words = local_level_words(self.cursor())
        return self._level_words.get(country or "", {})

    # ------------------------------------------------------------ gazetteer

    def describe(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        if not ids:
            return {}
        cur = self.cursor()
        rows = cur.execute("""
            SELECT d.id, d.name, d.subtype, d.class, d.region, d.country, d.population,
                   EXISTS (SELECT 1 FROM areas a WHERE a.id = d.id) AS has_area, d.ancestors,
                   ST_X(d.geometry) AS lon, ST_Y(d.geometry) AS lat
            FROM divisions d WHERE d.id IN (SELECT unnest(?))
        """, [ids]).fetchall()
        # Names of the ancestors (region, county, locality, macrohood), the nearest first. One lookup for all rows.
        names = dict(cur.execute("""
            SELECT id, name FROM divisions WHERE id IN (SELECT unnest(?))
              AND subtype IN ('region', 'county', 'locality', 'macrohood')""",
            [sorted({a for r in rows for a in (r[8] or [])})]).fetchall())
        out = {}
        for id_, name, subtype, cls, region, country, pop, has_area, anc_ids, lon, lat in rows:
            anc_ids = [a for a in (anc_ids or []) if a != id_]
            out[id_] = {"name": name, "subtype": subtype, "class": cls, "region": region, "country": country,
                        "population": pop, "ancestors": [names[a] for a in reversed(anc_ids) if a in names],
                        "has_area": has_area, "lon": lon, "lat": lat, "ancestor_ids": anc_ids}
        return out

    def view(self, view: Sequence[float] | None, cfg: dict[str, Any]) -> tuple[Sequence[float], str | None]:
        """Map view (xmin, ymin, xmax, ymax) and the country of its center: the nearest admin point of the countries
        whose extent (of the division points) contains the center, or of all countries if none does. The extent
        keeps out a small country near the center (the Vatican for a view of Italy). No view: data.bbox and
        data.country."""
        if not view:
            return cfg["data"]["bbox"], cfg["data"]["country"]
        cx, cy = (view[0] + view[2]) / 2, (view[1] + view[3]) / 2
        if self._extents is None:
            self._extents = {c: tuple(round(v, 5) for v in b) for c, *b in self.cursor().execute("""
                SELECT country, min(ST_X(geometry)), min(ST_Y(geometry)), max(ST_X(geometry)), max(ST_Y(geometry))
                FROM divisions WHERE country IS NOT NULL GROUP BY 1""").fetchall()}
        inside = [c for c, b in self._extents.items() if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]]
        row = self.cursor().execute(f"""
            SELECT country FROM divisions WHERE subtype IN ('country', 'dependency', 'region') AND country IS NOT NULL
              {"AND country IN (SELECT unnest(?))" if inside else ""}
            ORDER BY (ST_X(geometry) - ?) ** 2 + (ST_Y(geometry) - ?) ** 2, id LIMIT 1""",
            [inside, cx, cy] if inside else [cx, cy]).fetchone()
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
        # Overture names of some regions end with a level word and have no short form ("Kyoto Prefecture").
        rows = cur.execute(f"""
            SELECT id, max({KIND_SCORE}) AS s FROM names WHERE name_nospace IN (SELECT replace(unnest(?), ' ', ''))
            GROUP BY id
        """, [[f"{x} {suffix}" for x in q_list for suffix in REGION_SUFFIXES]]).fetchall()
        for id_, s in rows:
            scores[id_] = max(scores.get(id_, 0.0), float(s) * 0.98)
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
