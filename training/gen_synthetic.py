"""Generate synthetic training pairs (query -> frame) from the templates (plan-005 section 3.2).

Usage: uv run python -m training.gen_synthetic --n 20000 --out training/data/synthetic.jsonl

Each record: {"query", "frame", "template", "source": "synthetic", "depth"}.
Gold and held-out queries are removed from the output.
"""
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

from geoparse.execute.data import get_store
from geoparse.options import lexicon
from geoparse.t5.frames import Frame, check_frame

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- value pools


def load_places(rng: random.Random) -> dict[str, list[str]]:
    con = get_store().cursor()

    def names(sql):
        return sorted({re.sub(r"\s+", " ", r[0]).strip() for r in con.execute(sql).fetchall()
                       if r[0] and re.match(r"^[A-Za-z][A-Za-z .'-]+$", r[0])})

    states = names("SELECT coalesce(name_en, name) FROM divisions WHERE subtype='region' AND country='IN' AND region IS NOT NULL")
    districts = names("SELECT coalesce(name_en, name) FROM divisions WHERE subtype='county' AND country='IN'")
    cities = names("SELECT coalesce(name_en, name) FROM divisions WHERE subtype='locality' AND class IN ('city','town') AND country='IN'")
    hoods = names("""
        SELECT coalesce(d.name_en, d.name) FROM divisions d JOIN areas a USING (id)
        WHERE d.subtype IN ('macrohood','neighborhood') AND d.country='IN'
          AND list_has_any(d.ancestors, (SELECT list(id) FROM divisions WHERE subtype='locality' AND class='city'
                AND name IN ('Bengaluru','Mumbai','Delhi','New Delhi','Chennai','Hyderabad','Kolkata','Pune','Ahmedabad')))
    """)
    # Names with a number or a block word ("Jayanagar 4th Block", "Sector 5") are names too (plan-039), not a slot
    # and a quantity: 300 of them.
    numbered = [h for h in hoods if len(h) < 30 and re.search(r"\d|block|sector|phase|stage", h, re.I) and "ward" not in h.lower()]
    hoods = [h for h in hoods if len(h) < 30 and not re.search(r"\d|ward|block|sector|phase|stage", h, re.I)]
    rng.shuffle(hoods)
    rng.shuffle(numbered)
    hoods = hoods[:3000] + numbered[:300]
    countries = ["India", "Nepal", "Bangladesh", "Pakistan", "China", "Bhutan", "Myanmar", "Sri Lanka"]
    landmarks = ["Charminar", "India Gate", "Gateway of India", "Qutub Minar", "Red Fort", "Marine Drive", "Hawa Mahal",
                 "Victoria Memorial", "Mysore Palace", "Bangalore Palace", "Lalbagh", "Cubbon Park", "Howrah Bridge",
                 "Golden Temple", "Taj Mahal", "Lotus Temple", "Juhu Beach", "Marina Beach", "Connaught Place",
                 "Chandni Chowk", "Kempegowda Airport", "Chhatrapati Shivaji Terminus", "Majestic", "Silk Board",
                 "Hitech City", "Bandra Kurla Complex", "Cyber City", "Electronic City", "Brigade Road", "MG Road",
                 "Linking Road", "Park Street", "Anna Salai", "Residency Road", "Church Street", "Commercial Street"]
    suffixes = ["Main Road", "Road", "metro station", "bus stand", "railway station", "market", "circle", "junction",
                "bus stop", "flyover", "signal", "cross"]
    pois = landmarks + [f"{rng.choice(hoods)} {rng.choice(suffixes)}" for _ in range(1500)]
    lex = [a for e in lexicon().values() for a in e["aliases"]]
    places = {"state": states, "district": districts, "city": cities, "hood": hoods, "country": countries,
              "poi": pois, "lex": lex}
    places.update(load_world(rng))
    places["demonym"] = load_demonyms(set(states) | set(places["w_country"]) | set(places["w_region"]) | {"India"})
    return places


def load_demonyms(targets: set[str]) -> list[tuple[str, str]]:
    """(demonym, place) pairs of geoparse/data/demonyms.yaml whose place is in the name pools ("Indian", "India")."""
    import yaml

    raw = yaml.safe_load((ROOT / "geoparse" / "data" / "demonyms.yaml").read_text()) or {}
    low = {t.lower(): t for t in targets}
    return sorted((" ".join(w[:1].upper() + w[1:] for w in k.split(" ")), low[v.lower()]) for k, v in raw.items()
                  if v.lower() in low and re.match(r"^[a-z][a-z' -]+$", k))


def load_world(rng: random.Random) -> dict[str, list[str]]:
    """Names from the world data (plan-027): countries, regions and counties of other countries, natural features by
    kind. Empty lists if the world data is not built."""
    import duckdb

    path = ROOT / "data" / "build-world" / "geoparse.duckdb"
    if not path.exists():
        return {"w_country": [], "w_region": [], "w_county": [], **{f"n_{k}": [] for k in NATURAL_KINDS}}
    con = duckdb.connect(str(path), read_only=True)

    def names(sql):
        return sorted({re.sub(r"\s+", " ", r[0]).strip() for r in con.execute(sql).fetchall()
                       if r[0] and re.match(r"^[A-Za-z][A-Za-z .'-]+$", r[0]) and len(r[0]) < 32})

    out = {
        "w_country": names("SELECT coalesce(name_en, name) FROM divisions WHERE subtype = 'country'"),
        "w_region": names("SELECT coalesce(name_en, name) FROM divisions WHERE subtype = 'region' AND country <> 'IN' AND region IS NOT NULL"),
        "w_county": names("SELECT coalesce(name_en, name) FROM divisions WHERE subtype = 'county' AND country <> 'IN' USING SAMPLE 6000 ROWS"),
    }
    for k in NATURAL_KINDS:
        out[f"n_{k}"] = names(f"SELECT name FROM divisions WHERE subtype = 'natural' AND class = '{k}'")
    con.close()
    return out


LEVEL = {
    "district": ["districts", "district", "dists", "zillas", "districts", "counties", "local government areas", "LGAs"],
    "state": ["states", "state", "provinces", "states", "regions", "regions", "prefectures"],
    "city": ["cities", "towns", "city", "big cities", "metros", "urban centres", "major cities", "cities and towns"],
    "union_territory": ["union territories", "UTs"],
    "country": ["countries", "nations"],
    "village": ["villages", "village", "hamlets"],
    "other": ["wards", "mandals", "tehsils", "taluks", "talukas", "blocks", "panchayats", "municipalities",
              "sub-districts", "circles", "localities", "neighbourhoods", "areas",
              # World level words that the data maps for each country (plan-038): "departments of Bretagne".
              "departments", "voivodeships", "governorates", "oblasts", "cantons", "communes", "parishes"],
}
PRED_PRE = {
    "on_river": ["riverside", "riverine", "river"],
    "in_mountains": ["mountain", "mountainous", "hilly", "hill", "highland"],
    "coastal": ["coastal", "seaside", "sea-facing", "maritime", "littoral", "beach", "shoreline"],
    "landlocked": ["landlocked", "inland", "interior", "non-coastal", "land-locked"],
    "border": ["border", "frontier", "bordering", "boundary"],
}
PRED_POST = {
    "on_river": ["on a river", "along a river", "on the river", "with a river", "that a river flows through"],
    "in_mountains": ["in the mountains", "on a mountain range", "in the hills", "in the highlands"],
    "coastal": ["on the coast", "near the sea", "by the sea", "along the coast", "touching the sea", "with a coastline",
                "that touch the sea", "on the seashore", "facing the sea", "near the coast", "with a beach",
                "that have a coastline", "on the shore", "next to the ocean", "by the ocean"],
    "landlocked": ["without a coastline", "away from the sea", "with no sea coast", "not on the coast",
                   "far from the coast", "with no access to the sea", "that do not touch the sea", "without a beach"],
    "border": ["on the international border", "along the border", "near the border", "on the frontier",
               "touching another country", "next to the international boundary", "on the Pakistan border"],
}
DIR_PART = {"north": ["northern", "north", "upper", "top", "north part of"], "south": ["southern", "south", "lower", "bottom"],
            "east": ["eastern", "east"], "west": ["western", "west"], "northeast": ["north-eastern", "northeastern", "north east"],
            "northwest": ["north-western", "northwestern", "north west"], "southeast": ["south-eastern", "southeastern"],
            "southwest": ["south-western", "southwestern"], "central": ["central", "middle"]}
DIR_OUT = {"north": ["north", "to the north", "above"], "south": ["south", "to the south", "below"], "east": ["east", "to the east"],
           "west": ["west", "to the west"], "northeast": ["north-east", "northeast"], "northwest": ["north-west"],
           "southeast": ["south-east"], "southwest": ["south-west"]}
CATEGORIES = ["hospitals", "hospital", "clinics", "pharmacies", "chemists", "medical shops", "medicine shops", "doctors",
              "dentists", "schools", "colleges", "universities", "libraries", "kindergartens", "restaurants", "places to eat",
              "eateries", "cafes", "coffee shops", "bars", "pubs", "fast food joints", "railway stations", "train stations",
              "metro stations", "airports", "bus stations", "bus stands", "bus stops", "petrol pumps", "petrol bunks",
              "fuel stations", "gas stations", "banks", "ATMs", "cash machines", "police stations", "fire stations",
              "post offices", "government offices", "temples", "mosques", "churches", "gurudwaras", "places of worship",
              "parks", "gardens", "hotels", "lodges", "places to stay", "museums", "beaches", "stadiums", "malls",
              "shopping malls", "supermarkets", "grocery stores", "markets", "hospitls", "restaraunts", "atms"]
CAT_KEY = {
    "hospitals": "hospital", "hospital": "hospital", "hospitls": "hospital", "clinics": "clinic", "doctors": "clinic",
    "pharmacies": "pharmacy", "chemists": "pharmacy", "medical shops": "pharmacy", "medicine shops": "pharmacy",
    "dentists": "dentist", "schools": "school", "colleges": "college_university", "universities": "college_university",
    "libraries": "library", "kindergartens": "preschool", "restaurants": "restaurant", "places to eat": "restaurant",
    "eateries": "restaurant", "restaraunts": "restaurant", "cafes": "cafe", "coffee shops": "cafe", "bars": "bar",
    "pubs": "bar", "fast food joints": "fast_food", "railway stations": "train_station", "train stations": "train_station",
    "metro stations": "train_station", "airports": "airport", "bus stations": "bus_station", "bus stands": "bus_station",
    "bus stops": "bus_station", "petrol pumps": "fuel", "petrol bunks": "fuel", "fuel stations": "fuel",
    "gas stations": "fuel", "banks": "bank", "ATMs": "atm", "cash machines": "atm", "atms": "atm",
    "police stations": "police", "fire stations": "fire_station", "post offices": "post_office",
    "government offices": "government_office", "temples": "temple", "mosques": "mosque", "churches": "church",
    "gurudwaras": "gurudwara", "places of worship": "place_of_worship", "parks": "park", "gardens": "park",
    "hotels": "hotel", "lodges": "hotel", "places to stay": "hotel", "museums": "museum", "beaches": "beach",
    "stadiums": "stadium", "malls": "mall", "shopping malls": "mall", "supermarkets": "supermarket",
    "grocery stores": "supermarket", "markets": "market",
}
assert set(CATEGORIES) <= set(CAT_KEY), set(CATEGORIES) - set(CAT_KEY)

ATTR = ["population", "people", "residents", "inhabitants", "a population"]
# Natural features (plan-027): kind words for natural_in, words after a name for lookups.
NATURAL_KINDS = ["river", "lake", "range", "desert", "plateau", "plain", "basin", "delta", "island", "island_group",
                 "peninsula", "sea", "bay"]
NATURAL_WORDS = {"river": ["rivers", "river", "rivers and streams"], "lake": ["lakes", "lake", "reservoirs"],
                 "range": ["mountain ranges", "mountains", "ranges", "hills", "mountain range"], "desert": ["deserts"],
                 "plateau": ["plateaus", "uplands"], "plain": ["plains"], "basin": ["basins"], "delta": ["deltas"],
                 "island": ["islands"], "island_group": ["island groups", "archipelagos"], "peninsula": ["peninsulas"],
                 "sea": ["seas", "oceans", "seas and oceans"], "bay": ["bays", "gulfs", "bays and gulfs"]}
NATURAL_SUFFIX = {"river": ["river", "River", "nadi"], "range": ["mountains", "range", "hills"], "desert": ["desert", "Desert"],
                  "lake": [], "plateau": ["plateau"], "plain": ["plains"], "basin": ["basin"], "delta": ["delta"]}
RANK = {"largest": ["largest", "biggest", "largest by area"], "smallest": ["smallest", "tiniest", "smallest by area"]}
OP = {"gt": ["over", "more than", "above", "at least", "exceeding", "greater than", "bigger than", "upwards of"],
      "lt": ["under", "less than", "below", "fewer than", "at most", "smaller than"]}

MAJOR_CITIES = ["Bangalore", "Bengaluru", "Mumbai", "Bombay", "Delhi", "New Delhi", "Chennai", "Hyderabad", "Kolkata",
                "Pune", "Ahmedabad", "Jaipur", "Lucknow", "Kochi", "Mysore", "Goa", "Noida", "Gurgaon"]

NUM_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
             10: "ten", 15: "fifteen", 20: "twenty", 25: "twenty five", 50: "fifty", 100: "hundred"}


def fmt_num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def distance(rng: random.Random) -> tuple[str, str]:
    """(surface text, frame value)"""
    unit = rng.choices(["km", "m", "mi"], weights=[6, 3, 1])[0]
    if unit == "km":
        n = rng.choice([0.5, 1, 1.5, 2, 2, 3, 5, 5, 10, 10, 15, 20, 25, 30, 50, 100])
        u = rng.choice(["km", "km", "kms", "kilometres", "kilometers", "kilometre", "Km", "KM", "k"])
    elif unit == "m":
        n = rng.choice([100, 200, 250, 300, 500, 500, 750, 800, 1000, 1500, 2000, 3000, 5000])
        u = rng.choice(["m", "m", "metres", "meters", "mtrs", "metre", "meter"])
    else:
        n = rng.choice([0.5, 1, 2, 3, 5, 10])
        u = rng.choice(["miles", "mile", "mi"])
    r = rng.random()
    if n == 0.5 and unit != "m" and r < 0.5:
        num = rng.choice(["half a", "half"])
        u = u if not u.endswith("s") or u in ("kms",) else u[:-1]
    elif n == 1 and r < 0.3:
        num = "a"
        u = {"kms": "km", "kilometres": "kilometre", "kilometers": "kilometer", "miles": "mile", "metres": "metre",
             "meters": "meter"}.get(u, u)
    elif int(n) == n and int(n) in NUM_WORDS and r < 0.25:
        num = NUM_WORDS[int(n)]
    elif n >= 1000 and r < 0.3:
        num = f"{int(n):,}"
    else:
        num = fmt_num(n)
    sep = "" if (num[-1].isdigit() and rng.random() < 0.3) else " "
    if num.startswith("half") or num == "a":
        sep = " "
    return f"{num}{sep}{u}", f"{fmt_num(n)} {unit}"


def value(rng: random.Random) -> tuple[str, str]:
    kind = rng.choice(["lakh", "million", "crore", "plain", "thousand", "small", "small"])
    if kind == "small":
        n = rng.choice([20, 50, 60, 70, 100, 200, 500, 1000, 2000, 5000, 10000, 25000, 50000])
        return (f"{n:,}" if n >= 1000 and rng.random() < 0.5 else str(n)), str(n)
    if kind == "lakh":
        n = rng.choice([1, 2, 5, 10, 15, 20, 25, 30, 40, 50])
        word = rng.choice(["lakh", "lakhs", "lac", "lacs", "Lakh"])
        num = NUM_WORDS.get(n) if rng.random() < 0.25 and n in NUM_WORDS else str(n)
        return f"{num} {word}", f"{n} lakh"
    if kind == "million":
        n = rng.choice([0.5, 1, 1, 2, 3, 5, 10])
        if n == 0.5:
            return rng.choice(["half a million", "0.5 million"]), "0.5 million"
        if n == 1 and rng.random() < 0.4:
            return rng.choice(["a million", "one million", "1M", "1 mn"]), "1 million"
        return f"{fmt_num(n)} {rng.choice(['million', 'million', 'mn', 'M'])}".replace(" M", "M"), f"{fmt_num(n)} million"
    if kind == "crore":
        n = rng.choice([1, 1.5, 2, 5, 10])
        return f"{fmt_num(n)} {rng.choice(['crore', 'crores', 'cr'])}", f"{fmt_num(n)} crore"
    if kind == "thousand":
        n = rng.choice([10, 20, 50, 100, 200, 500])
        return rng.choice([f"{n} thousand", f"{n}k", f"{n},000", f"{n} K"]), f"{n} thousand"
    n = rng.choice([50000, 100000, 200000, 500000, 1000000, 2000000, 3000000, 5000000])
    return rng.choice([f"{n:,}", str(n)]), str(n)


def typo(rng: random.Random, s: str) -> str:
    if len(s) < 6 or rng.random() > 0.08:
        return s
    i = rng.randrange(1, len(s) - 1)
    op = rng.choice(["drop", "swap", "dup"])
    if op == "drop":
        return s[:i] + s[i + 1:]
    if op == "swap":
        return s[:i] + s[i + 1] + s[i] + s[i + 2:]
    return s[:i] + s[i] + s[i:]


def typo_always(rng: random.Random, s: str) -> str:
    i = rng.randrange(1, len(s) - 1)
    op = rng.choice(["drop", "swap", "dup"])
    if op == "drop":
        return s[:i] + s[i + 1:]
    if op == "swap":
        return s[:i] + s[i + 1] + s[i] + s[i + 2:]
    return s[:i] + s[i] + s[i:]


def case(rng: random.Random, s: str) -> str:
    r = rng.random()
    return s.lower() if r < 0.3 else s


# ---------------------------------------------------------------- generator


class Gen:
    def __init__(self, rng: random.Random, places: dict[str, list[str]]):
        self.r = rng
        self.p = places
        self.keys: dict[str, dict[str, str]] = {}  # span -> {slot type: option key}
        self.subs: set[str] = set()  # texts of sub-queries in this example
        self.lists: dict[str, list[str]] = {}  # list span -> its parts (the frame writes "A | B")
        self.within: dict[str, tuple[str, str]] = {}  # "X in Y" span -> (X, Y) (the frame writes `<slot>.within`)

    def pick(self, xs):
        return self.r.choice(xs)

    def place(self, kinds=("state", "district", "city", "hood")) -> str:
        k = self.r.choice(kinds)
        return case(self.r, typo(self.r, self.pick(self.p[k])))

    def area(self) -> str:
        return self.place(("state", "state", "district", "city"))

    def container(self) -> str:
        return self.place(("state", "state", "state", "district", "country"))

    def anchor(self) -> str:
        r = self.r.random()
        if r < 0.3:
            poi = case(self.r, self.pick(self.p["poi"]))
            if self.r.random() < 0.35:
                # A place with its city or state as context: one anchor, not two places.
                ctx = self.pick(self.p["city"] + MAJOR_CITIES * 20)
                poi = poi + self.pick([", ", " ", ", ", " "]) + case(self.r, ctx)
            return poi
        if r < 0.35:
            return self.pick(self.p["lex"])
        return self.place(("hood", "hood", "city", "district", "state"))

    def note(self, surface: str, slot_type: str, key: str) -> str:
        """Record the true option key of a closed-slot span (training labels for the local model)."""
        self.keys.setdefault(surface, {})[slot_type] = key
        return surface

    def level(self, exclude=()):
        keys = [x for x in LEVEL if x not in exclude]
        k = self.r.choices(keys, weights=[1 if x == "other" else 4 for x in keys])[0]
        lv = self.note(self.word_typo(self.pick(LEVEL[k])), "admin_level", "none" if k == "other" else k)
        return k, lv

    def word_typo(self, phrase: str, p: float = 0.06) -> str:
        """Typos in words of a phrase (not only in place names)."""
        words = phrase.split(" ")
        return " ".join(typo_always(self.r, w) if len(w) >= 5 and self.r.random() < p else w for w in words)

    def parent_or_list(self, level_key: str, depth: int) -> str:
        """A parent, or at depth 0 (35%) a list of 2 to 5 parents: "states of France, Spain and Italy" is the states of
        each name (plan-038)."""
        if depth == 0 and self.r.random() < 0.35:
            one = (lambda: self.world(("w_country",))) if level_key == "state" and self.has_world() and self.r.random() < 0.6 \
                else (lambda: self.parent_for(level_key, 1))
            return self.place_list(one)[0]
        return self.parent_for(level_key, depth)

    def demonym(self, level_key: str) -> str | None:
        """A demonym as the parent ("Indian states", "Texan counties"): a country for states, a country or a region
        for districts and cities ("French departments"). None if there is no such demonym."""
        regions = set(self.p["state"]) | set(self.p.get("w_region", []))
        ok = [d for d, t in self.p.get("demonym", []) if level_key != "state" or t not in regions]
        return case(self.r, self.pick(ok)) if ok else None

    def parent_for(self, level_key: str, depth: int) -> str:
        """A parent region that can contain divisions of the level."""
        if depth == 0 and self.r.random() < 0.12:
            return self.sub_query()[0]
        if self.r.random() < 0.08:
            return self.pick(self.p["lex"])
        kinds = {"state": ("country",), "union_territory": ("country",), "district": ("state", "state", "country"),
                 "city": ("state", "state", "district")}.get(level_key, ("state",))
        k = self.pick(kinds)
        return case(self.r, "India") if k == "country" else case(self.r, typo(self.r, self.pick(self.p[k])))

    def region(self, depth: int, sub_ok: bool = True) -> tuple[str, int]:
        """A region slot: a place name, a list of places, or a sub-query (depth + 1)."""
        if sub_ok and depth == 0 and self.r.random() < 0.15:
            q, f, d = self.sub_query()
            return q, 1
        if self.r.random() < 0.06:
            return self.pick(self.p["lex"]), 0
        if self.r.random() < 0.1:
            return self.place_list(self.area)[0], 0
        if self.r.random() < 0.05:
            # "Springfield in Illinois", "Jayanagar, Bengaluru": a place in a place is one name with a qualifier
            # (`<slot>.within`, plan-039), not a union. The qualifier has no typo (it is an exact name).
            x = self.place(("city", "hood", "district"))
            y = case(self.r, self.pick(self.p[self.pick(("state", "district", "city"))]))
            span = f"{x}{self.pick([' in ', ' in ', ', '])}{y}"
            self.within[span] = (x, y)
            return span, 0
        return self.area(), 0

    def sub_query(self):
        t = self.pick(["children", "children_with_predicate", "children_with_predicate", "neighbors", "buffer",
                       "children_touching", "direction_part"])
        q, f = getattr(self, "t_" + t)(depth=1)
        self.subs.add(q)
        return q, f, 1

    def natural(self, kinds=("river", "river", "range", "range", "lake", "desert", "sea", "bay", "plateau", "delta",
                             "island", "island_group", "plain")) -> str:
        """A natural feature name: "the Alps", "Ganga river", "Lake Victoria" (plan-027)."""
        k = self.pick(kinds)
        pool = self.p.get(f"n_{k}") or self.p["n_river"]
        n = self.pick(pool)
        if NATURAL_SUFFIX.get(k) and self.r.random() < 0.35 and not n.lower().endswith(tuple(NATURAL_SUFFIX[k])):
            n = f"{n} {self.pick(NATURAL_SUFFIX[k])}"
        if self.r.random() < 0.4:
            n = "the " + n
        return case(self.r, typo(self.r, n))

    def world(self, kinds=("w_country", "w_country", "w_region", "w_county")) -> str:
        return case(self.r, typo(self.r, self.pick(self.p[self.pick(kinds)])))

    def has_world(self) -> bool:
        return bool(self.p.get("w_country")) and bool(self.p.get("n_river"))

    def place_list(self, one, n: int | None = None, conj: str | None = None) -> tuple[str, str]:
        """A list of 2 to 4 places joined by commas and "and", "or", "&" or "as well as" (plan-036).
        Returns (span, conjunction)."""
        n = n or self.r.choice([2, 2, 2, 2, 3, 3, 4, 5])
        names: list[str] = []
        while len(names) < n:
            x = one()
            if x.lower() not in (y.lower() for y in names):
                names.append(x)
        conj = conj or self.r.choices(["and", "or", "&", "as well as", "plus", "n", "+"], weights=[12, 6, 2, 2, 1, 1, 1])[0]
        if conj in ("+", "n", "plus") and self.r.random() < 0.5:
            # The same separator between all names ("Bihar n Jharkhand n Odisha", "Texas+Oklahoma").
            sep = self.pick(["+", " + "]) if conj == "+" else f" {conj} "
            span = sep.join(names)
        elif n == 2:
            span = f"{names[0]} {conj} {names[1]}"
        elif self.r.random() < 0.1:
            span, conj = ", ".join(names), "and"
        else:
            oxford = "," if conj in ("and", "or") and self.r.random() < 0.3 else ""
            span = ", ".join(names[:-1]) + f"{oxford} {conj} {names[-1]}"
        self.lists[span] = names
        return span, conj

    def quantified(self, one) -> tuple[str, str | None]:
        """A list of places with or without a quantifier word: (list span, quant span or None). "both", "all of",
        "each of" mean all; "either", "any of" mean any. A plain list ("A and B", "A or B") has no quant span."""
        r = self.r.random()
        if r < 0.35:
            n = self.r.choice([2, 2, 2, 3])
            q = self.pick(["both"] if n == 2 else ["all of", "all three of", "each of", "all"])
            o, _ = self.place_list(one, n, "and")
            return o, self.note(q, "quantifier", "all")
        if r < 0.45:
            o, _ = self.place_list(one, 2, "or")
            return o, self.note(self.pick(["either", "any of"]), "quantifier", "any")
        o, _ = self.place_list(one)
        return o, None

    # Each t_* returns (query, slots). Slot values are spans of the query (or quantities).

    def t_lookup_place(self, depth=0):
        a = self.anchor()
        if self.has_world() and self.r.random() < 0.3:
            a = self.natural() if self.r.random() < 0.6 else self.world()
        if self.r.random() < 0.12:
            a = f"{self.pick(self.p['district'])} {self.pick(['district', 'dist', 'city', 'town'])}"
        elif self.r.random() < 0.25:
            a = case(self.r, self.pick(self.p["poi"])) + self.pick([", ", " "]) + case(self.r, self.pick(MAJOR_CITIES))
        if self.r.random() < 0.06:
            # "Mysuru palace", "Golconda fort": a named place, not a category of features (plan-039).
            a = f"{self.place(('city', 'city', 'hood', 'district'))} {self.pick(['palace', 'fort', 'temple', 'tomb', 'gate', 'bridge', 'ghat', 'Palace', 'Fort'])}"
        form = self.pick(["{a}", "{a}", "show me {a}", "where is {a}", "map of {a}", "{a} location", "locate {a}"])
        return form.format(a=a), {"anchor": a}

    def t_buffer(self, depth=0):
        d, dv = distance(self.r)
        t, _ = (self.anchor(), 0) if depth else self.region(depth)
        if self.has_world() and not depth and self.r.random() < 0.2:
            t = self.natural(("river", "lake", "lake", "range", "bay"))
        form = self.pick(["{d} around {t}", "within {d} of {t}", "{d} radius around {t}", "area within {d} of {t}",
                          "everything within {d} from {t}", "{d} from {t}", "{d} buffer around {t}", "{t} {d} radius",
                          "places within {d} of {t}", "{d} near {t}", "around {t} within {d}", "within a {d} radius of {t}"])
        if self.r.random() < 0.2 and not depth:
            form = self.pick(["near {t}", "around {t}", "close to {t}", "vicinity of {t}", "surroundings of {t}"])
            return form.format(t=t), {"target": t}
        return form.format(d=d, t=t), {"distance": dv, "target": t}

    def t_centroid(self, depth=0):
        t = self.area()
        form = self.pick(["center of {t}", "centre of {t}", "centroid of {t}", "middle point of {t}",
                          "geographic center of {t}", "{t} centroid", "midpoint of {t}"])
        return form.format(t=t), {"target": t}

    def t_direction_part(self, depth=0):
        k = self.pick(list(DIR_PART))
        d = self.note(self.word_typo(self.pick(DIR_PART[k]), 0.2), "direction", k)
        t, _ = self.region(depth, sub_ok=depth == 0)
        form = self.pick(["{d} {t}", "{d} part of {t}", "{d} {t}", "the {d} region of {t}", "{d} half of {t}",
                          "{d} side of {t}", "{d} areas of {t}"])
        if d.endswith(" of"):
            form = "{d} {t}"
        return form.format(d=d, t=t), {"dir": d, "target": t}

    def t_direction_outside(self, depth=0):
        k = self.pick(list(DIR_OUT))
        d = self.note(self.word_typo(self.pick(DIR_OUT[k]), 0.2), "direction", k)
        t = self.anchor()
        form = self.pick(["{d} of {t}", "area {d} of {t}", "region {d} of {t}", "just {d} of {t}", "a little {d} of {t}"])
        return form.format(d=d, t=t), {"dir": d, "target": t}

    def t_children(self, depth=0):
        k, lv = self.level(exclude=("country",))
        p = self.parent_or_list(k, depth)
        if self.has_world() and self.r.random() < 0.2:
            # A natural region as the parent ("districts in the Western Ghats"), or a parent in another country.
            p = self.natural(("range", "range", "desert", "plateau", "delta", "island", "plain")) if self.r.random() < 0.5 else self.world(("w_country", "w_region"))
        if self.r.random() < 0.08:
            form = self.pick(["{l}", "all {l}", "list of {l}", "{l} of India"])
            q = form.format(l=lv)
            return q, ({"level": lv, "parent": "India"} if "India" in q else {"level": lv})
        form = self.pick(["{l} of {p}", "{l} in {p}", "all {l} in {p}", "{p} {l}", "list of {l} in {p}",
                          "show {l} of {p}", "{l} within {p}", "which {l} are in {p}", "what are the {l} of {p}",
                          "{l} under {p}"])
        dem = self.demonym(k) if depth == 0 and self.r.random() < 0.1 else None
        if dem:
            p, form = dem, self.pick(["{p} {l}", "all {p} {l}", "the {p} {l}", "list of {p} {l}", "which are the {p} {l}"])
        return form.format(l=lv, p=p), {"level": lv, "parent": p}

    def t_parent(self, depth=0):
        k, lv = self.level(exclude=("country", "union_territory"))
        c = self.place(("hood", "city", "district"))
        form = self.pick(["{l} that contains {c}", "which {l} is {c} in", "{l} containing {c}",
                          "what {l} is {c} in", "the {l} where {c} is", "in which {l} is {c}"])
        return form.format(l=lv, c=c), {"level": lv, "child": c}

    def t_neighbors(self, depth=0):
        k, lv = self.level(exclude=("union_territory",))
        if not depth and self.r.random() < 0.55:
            one = (lambda: self.world(("w_country",))) if self.has_world() and k == "country" else self.area
            o, qw = self.quantified(one)
            if qw:
                form = self.pick(["{l} that border {q} {o}", "{l} bordering {q} {o}", "{l} next to {q} {o}",
                                  "which {l} touch {q} {o}", "{l} adjacent to {q} {o}", "{l} that share a border with {q} {o}"])
                return form.format(l=lv, q=qw, o=o), {"level": lv, "quant": qw, "of": o}
            form = self.pick(["{l} that border {o}", "{l} bordering {o}", "{l} adjacent to {o}", "{l} next to {o}",
                              "which {l} border {o}", "{l} touching {o}"])
            return form.format(l=lv, o=o), {"level": lv, "of": o}
        o, _ = self.region(depth)
        form = self.pick(["{l} that border {o}", "{l} bordering {o}", "{l} adjacent to {o}", "neighbouring {l} of {o}",
                          "{l} next to {o}", "{l} touching {o}", "{l} sharing a border with {o}", "{l} around {o}",
                          "which {l} border {o}", "{l} that surround {o}", "{l} that share a border with {o}",
                          "{l} that share borders with {o}", "{l} adjoining {o}", "{l} on the border of {o}",
                          "{l} that touch {o}", "which {l} share a boundary with {o}"])
        if self.r.random() < 0.15:
            form = self.pick(["neighbours of {o}", "neighbors of {o}", "{o} neighbours", "what borders {o}"])
            return form.format(o=o), {"of": o}
        if self.has_world() and self.r.random() < 0.25:
            # A natural feature ("countries along the Danube", "states bordering the Bay of Bengal").
            o = self.natural(("river", "river", "sea", "bay", "lake", "range"))
            form = self.pick(["{l} along {o}", "{l} bordering {o}", "{l} that border {o}", "which {l} does {o} flow through",
                              "{l} that {o} passes through", "{l} on {o}", "{l} touching {o}"])
        return form.format(l=lv, o=o), {"level": lv, "of": o}

    def t_children_with_predicate(self, depth=0):
        k, lv = self.level(exclude=("country",))
        pk = self.pick(list(PRED_PRE))
        p = self.parent_or_list(k, depth) if self.r.random() > 0.15 else None
        if self.r.random() < 0.5:
            pr = self.note(self.word_typo(self.pick(PRED_PRE[pk])), "predicate", pk)
            head = f"{pr} {lv}"
        else:
            pr = self.note(self.word_typo(self.pick(PRED_POST[pk])), "predicate", pk)
            head = None
        if p is None:
            q = head if head else f"{lv} {pr}"
            q = self.pick(["{q}", "all {q}", "which {q}", "show {q}"]).format(q=q) if head else self.pick(
                ["{q}", "which {q}", "all {q}"]).format(q=q)
            return q, {"level": lv, "pred": pr}
        if head:
            form = self.pick(["{h} of {p}", "{h} in {p}", "all {h} in {p}", "{p} {h}", "{h} within {p}", "list {h} of {p}"])
            dem = self.demonym(k) if depth == 0 and self.r.random() < 0.1 else None
            if dem:
                # "coastal Brazilian states": the demonym between the predicate and the level.
                return f"{pr} {dem} {lv}", {"level": lv, "pred": pr, "parent": dem}
            return form.format(h=head, p=p), {"level": lv, "pred": pr, "parent": p}
        form = self.pick(["{l} {pr} in {p}", "{l} of {p} {pr}", "{l} in {p} that are {pr}", "{p} {l} {pr}",
                          "{l} {pr} of {p}", "which {l} of {p} are {pr}"])
        return form.format(l=lv, pr=pr, p=p), {"level": lv, "pred": pr, "parent": p}

    def t_children_touching(self, depth=0):
        k, lv = self.level(exclude=("country", "union_territory"))
        p = self.parent_for(k, 1)
        o = self.area()
        if self.has_world() and self.r.random() < 0.4:
            # Along a river, with or without a parent ("districts along the Yamuna").
            o = self.natural(("river", "river", "river", "range", "lake"))
            if self.r.random() < 0.5:
                form = self.pick(["{l} along {o}", "{l} on the banks of {o}", "{l} beside {o}", "{l} that {o} flows through",
                                  "{l} on {o}"])
                return form.format(l=lv, o=o), {"level": lv, "other": o}
            form = self.pick(["{l} of {p} along {o}", "{l} in {p} on the banks of {o}", "{p} {l} along {o}"])
            return form.format(l=lv, p=p, o=o), {"level": lv, "parent": p, "other": o}
        if self.r.random() < 0.3:
            o, qw = self.quantified(self.area)
            if qw:
                form = self.pick(["{l} of {p} that border {q} {o}", "{l} in {p} bordering {q} {o}", "{l} of {p} touching {q} {o}"])
                return form.format(l=lv, p=p, q=qw, o=o), {"level": lv, "parent": p, "quant": qw, "other": o}
        form = self.pick(["{l} of {p} that border {o}", "{l} in {p} bordering {o}", "{p} {l} next to {o}",
                          "{l} of {p} adjacent to {o}", "{l} in {p} touching {o}", "{l} of {p} on the border with {o}"])
        dem = self.demonym(k) if self.r.random() < 0.15 else None
        if dem:
            p, form = dem, self.pick(["{p} {l} bordering {o}", "{p} {l} that border {o}", "which {p} {l} touch {o}",
                                      "{p} {l} next to {o}", "{p} {l} on the border with {o}", "the {p} {l} along {o}"])
        return form.format(l=lv, p=p, o=o), {"level": lv, "parent": p, "other": o}

    def t_union(self, depth=0):
        """Two to five places or sets together: one slot `places` (plan-038). A part can be a sub-query ("Kerala and
        the coastal districts of Karnataka"); "LEVEL of A and B" is not a union (children of a list)."""
        subs = depth == 0 and self.r.random() < 0.35

        def part():
            if subs and self.r.random() < 0.5:
                for _ in range(10):
                    q, _, _ = self.sub_query()
                    if q.split(" ", 1)[0].lower() not in ("show", "list", "which", "what", "all", "the", "a"):
                        return self.pick(["", "", "the "]) + q
            return self.region(1, sub_ok=False)[0]
        pl, _ = self.place_list(part, self.r.choice([2, 2, 3]) if subs else None)
        form = self.pick(["{p}", "{p}", "{p}", "{p}", "both {p}", "{p} together", "union of {p}", "combine {p}",
                          "{p} in one view", "{p} on one map"])
        if form.startswith("both") and (" and " not in pl or pl.count(",")):
            form = "{p}"
        return form.format(p=pl), {"places": pl}

    def t_difference(self, depth=0):
        a, _ = self.region(depth)
        b, _ = self.region(depth, sub_ok=False)
        form = self.pick(["{a} except {b}", "{a} excluding {b}", "{a} without {b}", "{a} minus {b}", "{a} but not {b}",
                          "all of {a} except {b}", "{a} other than {b}", "{a} leaving out {b}", "{a} apart from {b}"])
        return form.format(a=a, b=b), {"a": a, "b": b}

    def t_intersection(self, depth=0):
        a = self.area()
        if self.r.random() < 0.6 and depth == 0:
            b, _ = self.t_buffer(depth=1)
        else:
            b = self.area()
        form = self.pick(["overlap of {a} and {b}", "intersection of {a} and {b}", "part of {a} within {b}",
                          "parts of {a} that are in {b}", "where {a} and {b} overlap", "{a} that overlaps {b}",
                          "portion of {a} inside {b}"])
        if form.startswith("part of") or form.startswith("parts of") or form.startswith("portion"):
            if not b[0].isdigit() and not b.startswith("within"):
                pass
        q = form.format(a=a, b=b)
        if "within within" in q:
            q = q.replace("within within", "within")
            b = b.replace("within ", "", 1)
        return q, {"a": a, "b": b}

    def t_between(self, depth=0):
        a, b = self.anchor(), self.anchor()
        form = self.pick(["between {a} and {b}", "area between {a} and {b}", "region between {a} and {b}",
                          "the land between {a} and {b}", "everything between {a} and {b}", "{a} to {b} corridor"])
        return form.format(a=a, b=b), {"a": a, "b": b}

    def t_along_coast(self, depth=0):
        r = self.place(("state", "district"))
        if self.r.random() < 0.35:
            form = self.pick(["coastal belt of {r}", "coastline of {r}", "coastal strip of {r}", "{r} coast",
                              "coastal area of {r}", "{r} shoreline", "sea coast of {r}"])
            return form.format(r=r), {"region": r}
        d, dv = distance(self.r)
        form = self.pick(["{d} along the coast of {r}", "{d} from the coast in {r}", "{d} coastal strip of {r}",
                          "within {d} of the sea in {r}", "{d} along the coastline of {r}", "{d} inland from the {r} coast"])
        return form.format(d=d, r=r), {"distance": dv, "region": r}

    def t_along_border(self, depth=0):
        r = self.place(("state", "district"))
        if self.r.random() < 0.35:
            form = self.pick(["border belt of {r}", "boundary strip of {r}", "{r} border area", "border areas of {r}"])
            return form.format(r=r), {"region": r}
        d, dv = distance(self.r)
        form = self.pick(["{d} along the border of {r}", "{d} from the boundary of {r}", "{d} on either side of the {r} border",
                          "within {d} of the {r} border"])
        return form.format(d=d, r=r), {"distance": dv, "region": r}

    def t_along_intl_border(self, depth=0):
        r = self.pick(self.p["state"])
        if self.r.random() < 0.35:
            form = self.pick(["international border belt of {r}", "international border area in {r}"])
            return form.format(r=r), {"region": r}
        d, dv = distance(self.r)
        form = self.pick(["{d} along the international border in {r}", "{d} from the international border in {r}",
                          "within {d} of the international boundary in {r}", "{d} of the country border in {r}"])
        return form.format(d=d, r=r), {"distance": dv, "region": r}

    def t_shared_border(self, depth=0):
        world = self.has_world() and self.r.random() < 0.6
        one = (lambda: self.world(("w_country",))) if world else (lambda: self.place(("state", "state", "district")))
        if self.r.random() < 0.15:
            # Two names with no separator: "India Pakistan border" (a space is a separator in this template only).
            pl = f"{one()} {one()}"
            return self.pick(["{p} border", "the {p} border", "{p} boundary"]).format(p=pl), {"places": pl}
        pl, _ = self.place_list(one, self.r.choice([2, 2, 2, 2, 3, 3, 4]), "and" if self.r.random() < 0.85 else "&")
        if self.r.random() < 0.35:
            d, dv = distance(self.r)
            form = self.pick(["{d} along the border between {p}", "{d} zone along the border of {p}",
                              "{d} strip along the border between {p}", "{d} along the borders of {p}"])
            return form.format(d=d, p=pl), {"distance": dv, "places": pl}
        form = self.pick(["border between {p}", "the border between {p}", "boundary between {p}", "border of {p}",
                          "the frontier between {p}", "shared border of {p}", "the borders between {p}", "border among {p}"])
        return form.format(p=pl), {"places": pl}

    def t_border_with_in(self, depth=0):
        """The part of the border with another place that is inside a place (plan-038): "border area with Bangladesh in
        Tripura", "3 km along the border with Nepal in Bihar"."""
        if self.has_world() and self.r.random() < 0.5:
            o, r = self.world(("w_country",)), self.world(("w_region",))
        else:
            o = case(self.r, self.pick(["Nepal", "Bangladesh", "Pakistan", "China", "Bhutan", "Myanmar", "Sri Lanka"]))
            r = self.place(("state", "state", "district"))
        w = self.pick(["border", "boundary", "frontier"])
        if self.r.random() < 0.4:
            d, dv = distance(self.r)
            form = self.pick(["{d} along the {w} with {o} in {r}", "{d} strip along the {w} with {o} in {r}",
                              "{d} zone along the {w} with {o} in {r}", "{d} belt along the {w} with {o} in {r}"])
            return form.format(d=d, w=w, o=o, r=r), {"distance": dv, "other": o, "region": r}
        form = self.pick(["{w} area with {o} in {r}", "the {w} with {o} in {r}", "{w} region with {o} in {r}",
                          "the {r} part of the {w} with {o}", "the {r} side of the {w} with {o}", "{w} zone with {o} in {r}"])
        return form.format(w=w, o=o, r=r), {"other": o, "region": r}

    def t_natural_in(self, depth=0):
        k = self.pick(NATURAL_KINDS)
        kw = self.note(self.word_typo(self.pick(NATURAL_WORDS[k])), "natural_kind", k)
        r = self.world(("w_country", "w_region")) if self.has_world() and self.r.random() < 0.5 else self.place(("state", "state", "district", "country"))
        form = self.pick(["{k} in {r}", "{k} of {r}", "which {k} are in {r}", "{k} that flow through {r}", "{k} crossing {r}",
                          "{k} that touch {r}", "{r} {k}", "list the {k} in {r}", "what {k} are there in {r}"])
        if k != "river" and "flow" in form:
            form = "{k} in {r}"
        return form.format(k=kw, r=r), {"kind": kw, "region": r}

    def t_children_near(self, depth=0):
        k, lv = self.level(exclude=("country", "union_territory"))
        d, dv = distance(self.r)
        o = self.area() if self.r.random() < 0.7 or not self.has_world() else self.natural(("river", "lake", "range"))
        if self.r.random() < 0.5:
            form = self.pick(["{l} within {d} of {o}", "{l} within {d} from {o}", "{l} less than {d} from {o}",
                              "which {l} are within {d} of {o}"])
            return form.format(l=lv, d=d, o=o), {"level": lv, "distance": dv, "other": o}
        p = self.parent_for(k, 1)
        form = self.pick(["{l} of {p} within {d} of {o}", "{l} in {p} within {d} of {o}", "{p} {l} within {d} of {o}"])
        return form.format(l=lv, p=p, d=d, o=o), {"level": lv, "parent": p, "distance": dv, "other": o}

    def t_children_top(self, depth=0):
        k, lv = self.level(exclude=("country",))
        ok = self.pick(list(RANK))
        p = self.parent_or_list(k, depth)
        if self.r.random() < 0.3:
            # "the most populous state of India": order "most", by "populous".
            o = self.note(self.pick({"largest": ["most", "most"], "smallest": ["least"]}[ok]), "rank_order", ok)
            by = self.note(self.pick(["populous", "populated"]), "attr", "population")
            head, slots = f"{o} {by}", {"order": o, "by": by}
        else:
            o = self.note(self.pick(RANK[ok]), "rank_order", ok)
            head, slots = o, {"order": o}
        slots.update({"level": lv, "parent": p})
        if self.r.random() < 0.6:
            n = self.r.choice([2, 3, 3, 5, 5, 10])
            ns = str(n) if self.r.random() < 0.7 else NUM_WORDS[n]
            slots["n"] = str(n)
            form = self.pick(["{n} {h} {l} of {p}", "top {n} {h} {l} in {p}", "the {n} {h} {l} of {p}"])
            return form.format(n=ns, h=head, l=lv, p=p), slots
        form = self.pick(["the {h} {l} of {p}", "{h} {l} in {p}", "which is the {h} {l} of {p}", "{h} {l} of {p}"])
        return form.format(h=head, l=lv, p=p), slots

    def t_neighbors_with_predicate(self, depth=0):
        k, lv = self.level(exclude=("union_territory",))
        pk = self.pick(["coastal", "landlocked", "coastal", "on_river", "in_mountains"])
        pr = self.note(self.word_typo(self.pick(PRED_PRE[pk])), "predicate", pk)
        o = self.world(("w_country",)) if self.has_world() and k == "country" else self.area()
        form = self.pick(["{p} {l} that border {o}", "{p} {l} bordering {o}", "{p} {l} next to {o}", "{p} {l} adjacent to {o}",
                          "which {p} {l} border {o}", "{p} {l} touching {o}"])
        return form.format(p=pr, l=lv, o=o), {"pred": pr, "level": lv, "of": o}

    def t_children_top_per(self, depth=0):
        """The largest or smallest divisions in each division of a higher level (plan-036)."""
        k, per_k = self.pick([("district", "state"), ("district", "state"), ("city", "state"), ("city", "district"),
                              ("state", "country")])
        lv = self.note(self.word_typo(self.pick(LEVEL[k])), "admin_level", k)
        per = self.note(self.pick({"state": ["state", "province", "region"], "district": ["district", "county"],
                                   "country": ["country", "nation"]}[per_k]), "admin_level", per_k)
        ok = self.pick(list(RANK))
        o = self.note(self.pick(RANK[ok]), "rank_order", ok)
        slots = {"order": o, "level": lv, "per": per}
        each = self.pick(["each", "every"])
        # "states in each country" has no parent; the others are inside one country.
        p = None if per_k == "country" else (
            case(self.r, "India") if not self.has_world() or self.r.random() < 0.5 else self.world(("w_country",)))
        if p is not None and per_k == "state" and depth == 0 and self.r.random() < 0.2:
            # "the largest district in each state of Kerala and Tamil Nadu": a list of the `per` divisions.
            p = self.place_list(lambda: self.pick(self.p["state"]), self.r.choice([2, 2, 3]))[0]
        if self.r.random() < 0.35:
            n = self.r.choice([2, 2, 3, 3, 5])
            ns = str(n) if self.r.random() < 0.7 else NUM_WORDS[n]
            slots["n"] = str(n)
            head = f"{ns} {o}"
        else:
            head = f"the {o}" if self.r.random() < 0.6 else o
        if p is None:
            return f"{head} {lv} in {each} {per}", slots
        slots["parent"] = p
        form = self.pick(["{h} {l} in {e} {per} of {p}", "{h} {l} of {e} {per} in {p}", "{h} {l} in {e} {per} in {p}"])
        return form.format(h=head, l=lv, e=each, per=per, p=p), slots

    def t_features_in(self, depth=0):
        c0 = self.pick(CATEGORIES)
        c = self.note(self.word_typo(c0), "category", CAT_KEY[c0])
        r, _ = self.region(depth) if self.r.random() < 0.4 else (self.place(("hood", "hood", "city", "district")), 0)
        form = self.pick(["{c} in {r}", "{c} inside {r}", "{r} {c}", "all {c} in {r}", "list of {c} in {r}",
                          "show {c} in {r}", "find {c} in {r}", "{c} located in {r}", "where are the {c} in {r}"])
        return form.format(c=c, r=r), {"category": c, "region": r}

    def t_features_near(self, depth=0):
        c0 = self.pick(CATEGORIES)
        c = self.note(self.word_typo(c0), "category", CAT_KEY[c0])
        r, _ = self.region(depth) if self.r.random() < 0.2 else (self.anchor(), 0)
        if self.r.random() < 0.3:
            form = self.pick(["{c} near {r}", "{c} around {r}", "{c} close to {r}", "{c} nearby {r}", "{c} next to {r}",
                              "where can I find {c} near {r}", "{c} in the vicinity of {r}"])
            return form.format(c=c, r=r), {"category": c, "region": r}
        d, dv = distance(self.r)
        form = self.pick(["{c} within {d} of {r}", "{c} {d} from {r}", "{c} within {d} radius of {r}",
                          "{c} around {r} within {d}", "{c} near {r} within {d}", "{c} in a {d} radius around {r}",
                          "{c} less than {d} from {r}"])
        return form.format(c=c, d=d, r=r), {"category": c, "distance": dv, "region": r}

    def t_children_attr(self, depth=0):
        k, lv = self.level(exclude=("country", "union_territory"))
        p = self.parent_for(k, depth) if self.r.random() > 0.1 else None
        a = self.note(self.pick(ATTR), "attr", "population")
        ok = self.pick(list(OP))
        o = self.note(self.pick(OP[ok]), "op", ok)
        v, vv = value(self.r)
        if a in ("people", "residents", "inhabitants"):
            mid = f"with {o} {v} {a}"
            slots = {"level": lv, "op": o, "value": vv, "attr": a}
        else:
            mid = f"{self.pick(['with', 'having', 'where', 'whose'])} {a} {self.pick(['', 'is ', 'of '])}{o} {v}".replace("  ", " ")
            slots = {"level": lv, "attr": a, "op": o, "value": vv}
        if p is None:
            return f"{lv} {mid}", slots
        form = self.pick(["{l} in {p} {m}", "{l} of {p} {m}", "{l} {m} in {p}", "{p} {l} {m}"])
        slots["parent"] = p
        return form.format(l=lv, p=p, m=mid), slots

    UNSUPPORTED_FORMS = [
        "weather in {a}", "how far is {a} from {b}", "distance from {a} to {b}", "route from {a} to {b}",
        "population of {a}", "capital of {a}", "who is the chief minister of {a}", "time in {a}", "{a} pin code",
        "train from {a} to {b}", "flights to {a}", "history of {a}", "best time to visit {a}", "how to reach {a}",
        "is {a} safe", "news from {a}", "{a} temperature today", "translate {a}", "hello", "what can you do",
        "book a cab to {a}", "{a} ka mausam", "{a} mein hospital kahan hai", "cheapest flight {a} {b}",
        "is {a} open on sunday", "ticket price for {a}", "how many people live in {a}", "area of {a} in sq km",
        "what is {a} famous for", "best hotels in {a} under 2000 rupees per night", "traffic near {a} now",
        "petrol price in {a} today", "which language is spoken in {a}", "{a} vs {b} which is better",
        "how old is {a}", "elevation of {a}", "aqi in {a}", "rent prices in {a}",
    ]

    def unsupported(self):
        f = self.pick(self.UNSUPPORTED_FORMS)
        return f.format(a=self.area(), b=self.area()), None


TEMPLATE_WEIGHTS = {
    "lookup_place": 6, "buffer": 8, "centroid": 2, "direction_part": 4, "direction_outside": 3, "children": 6,
    "parent": 3, "neighbors": 8, "children_with_predicate": 9, "children_touching": 5, "union": 7,
    "difference": 4, "intersection": 3, "between": 3, "along_coast": 3, "along_border": 2, "along_intl_border": 2,
    "features_in": 8, "features_near": 8, "children_attr": 6, "unsupported": 5,
    "shared_border": 5, "natural_in": 5, "children_near": 4, "children_top": 5, "neighbors_with_predicate": 3,
    "children_top_per": 4, "border_with_in": 4,
}


def frame_slots(t: str, slots: dict[str, str], g: Gen, templates) -> tuple[dict[str, str], list[str]]:
    """The frame slots of plan-039: a list span as its parts ("A | B"), "X in Y" as X with `<slot>.within = Y`.
    Also the parts that are sub-queries (for the is_subquery questions)."""
    ws = lambda x: re.sub(r"\s+", " ", x).strip()
    lists = {ws(k): [ws(p) for p in v] for k, v in g.lists.items()}
    within = {ws(k): (ws(x), ws(y)) for k, (x, y) in g.within.items()}
    subs = {ws(x) for x in g.subs}
    out, sub_parts = {}, []
    tpl = templates.get(t)
    for k, v in slots.items():
        open_slot = tpl is not None and k in tpl.slots and tpl.slots[k].type in ("region", "anchor")
        if open_slot and v in lists:
            parts = lists[v]
            out[k] = " | ".join(parts)
            sub_parts += [p for p in parts if p in subs or re.sub(r"^the ", "", p) in subs]
        elif open_slot and v in within:
            out[k], out[f"{k}.within"] = within[v]
        else:
            out[k] = v
    return out, sub_parts


def generate(n: int, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    g = Gen(rng, load_places(rng))
    from training.evalset import eval_queries

    exclude = eval_queries()
    names, weights = zip(*TEMPLATE_WEIGHTS.items())
    from geoparse.templates.model import all_templates

    templates = all_templates()
    out, seen = [], set()
    while len(out) < n:
        t = rng.choices(names, weights=weights)[0]
        g.keys, g.subs, g.lists, g.within = {}, set(), {}, {}
        q, slots = g.unsupported() if t == "unsupported" else getattr(g, "t_" + t)()
        if t != "unsupported" and rng.random() < 0.18:
            q = rng.choice(["pls show ", "can u show ", "how do i see ", "i want to see ", "show me ", "find ",
                            "map of ", "can you find ", "", ""]) + q + rng.choice(
                [" on map", " on the map", "?", " pls", " please", "", "", " all in one view"])
        q = re.sub(r"\s+", " ", q).strip()
        if slots:
            slots = {k: re.sub(r"\s+", " ", v).strip() for k, v in slots.items()}
            slots, sub_parts = frame_slots(t, slots, g, templates)
        key = q.lower()
        if key in seen or key in exclude:
            continue
        seen.add(key)
        frame = Frame(template="unsupported") if slots is None else Frame(template=t, slots=slots)
        if slots and check_frame(frame, q, templates):
            continue  # "Rajasthan except Rajasthan": the same text in two slots
        rec = {"query": q, "frame": frame.to_text(), "template": frame.template, "source": "synthetic"}
        if slots:
            tpl = templates[t]
            rec["closed_keys"] = {k: g.keys[v][tpl.slots[k].type] for k, v in slots.items()
                                  if k in tpl.slots and v in g.keys and tpl.slots[k].type in g.keys[v]}
            rec["sub_slots"] = sorted(k for k, v in slots.items() if v in g.subs)
            if sub_parts:
                rec["sub_parts"] = sub_parts
        out.append(rec)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(ROOT / "training" / "data" / "synthetic.jsonl"))
    args = ap.parse_args()
    recs = generate(args.n, args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
    from collections import Counter

    print(Counter(r["template"] for r in recs).most_common())
    for r in recs[:25]:
        print(f"{r['query']!r:60s} -> {r['frame']}")


if __name__ == "__main__":
    main()
