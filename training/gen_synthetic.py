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
from geoparse.t5.frames import Frame

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
    hoods = [h for h in hoods if len(h) < 30 and not re.search(r"\d|ward|block|sector|phase|stage", h, re.I)]
    rng.shuffle(hoods)
    hoods = hoods[:3000]
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
    return {"state": states, "district": districts, "city": cities, "hood": hoods, "country": countries,
            "poi": pois, "lex": lex}


LEVEL = {
    "district": ["districts", "district", "dists", "zillas", "districts"],
    "state": ["states", "state", "provinces", "states"],
    "city": ["cities", "towns", "city", "big cities", "metros", "urban centres", "major cities", "cities and towns"],
    "union_territory": ["union territories", "UTs"],
    "country": ["countries", "nations"],
    "village": ["villages", "village", "hamlets"],
    "other": ["wards", "mandals", "tehsils", "taluks", "talukas", "blocks", "panchayats", "municipalities",
              "sub-districts", "circles", "localities", "neighbourhoods", "areas"],
}
PRED_PRE = {
    "coastal": ["coastal", "seaside", "sea-facing", "maritime", "littoral", "beach", "shoreline"],
    "landlocked": ["landlocked", "inland", "interior", "non-coastal", "land-locked"],
    "border": ["border", "frontier", "bordering", "boundary"],
}
PRED_POST = {
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
        """A region slot: a place name, or a sub-query (depth + 1)."""
        if sub_ok and depth == 0 and self.r.random() < 0.15:
            q, f, d = self.sub_query()
            return q, 1
        if self.r.random() < 0.06:
            return self.pick(self.p["lex"]), 0
        return self.area(), 0

    def sub_query(self):
        t = self.pick(["children", "children_with_predicate", "children_with_predicate", "neighbors", "buffer",
                       "children_touching", "direction_part"])
        q, f = getattr(self, "t_" + t)(depth=1)
        self.subs.add(q)
        return q, f, 1

    # Each t_* returns (query, slots). Slot values are spans of the query (or quantities).

    def t_lookup_place(self, depth=0):
        a = self.anchor()
        if self.r.random() < 0.12:
            a = f"{self.pick(self.p['district'])} {self.pick(['district', 'dist', 'city', 'town'])}"
        elif self.r.random() < 0.25:
            a = case(self.r, self.pick(self.p["poi"])) + self.pick([", ", " "]) + case(self.r, self.pick(MAJOR_CITIES))
        form = self.pick(["{a}", "{a}", "show me {a}", "where is {a}", "map of {a}", "{a} location", "locate {a}"])
        return form.format(a=a), {"anchor": a}

    def t_buffer(self, depth=0):
        d, dv = distance(self.r)
        t, _ = (self.anchor(), 0) if depth else self.region(depth)
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
        d = self.note(self.word_typo(self.pick(DIR_PART[k]), 0.1), "direction", k)
        t, _ = self.region(depth, sub_ok=depth == 0)
        form = self.pick(["{d} {t}", "{d} part of {t}", "{d} {t}", "the {d} region of {t}", "{d} half of {t}",
                          "{d} side of {t}", "{d} areas of {t}"])
        if d.endswith(" of"):
            form = "{d} {t}"
        return form.format(d=d, t=t), {"dir": d, "target": t}

    def t_direction_outside(self, depth=0):
        k = self.pick(list(DIR_OUT))
        d = self.note(self.word_typo(self.pick(DIR_OUT[k]), 0.1), "direction", k)
        t = self.anchor()
        form = self.pick(["{d} of {t}", "area {d} of {t}", "region {d} of {t}", "just {d} of {t}", "a little {d} of {t}"])
        return form.format(d=d, t=t), {"dir": d, "target": t}

    def t_children(self, depth=0):
        k, lv = self.level(exclude=("country",))
        p = self.parent_for(k, depth)
        if self.r.random() < 0.08:
            form = self.pick(["{l}", "all {l}", "list of {l}", "{l} of India"])
            q = form.format(l=lv)
            return q, ({"level": lv, "parent": "India"} if "India" in q else {"level": lv})
        form = self.pick(["{l} of {p}", "{l} in {p}", "all {l} in {p}", "{p} {l}", "list of {l} in {p}",
                          "show {l} of {p}", "{l} within {p}", "which {l} are in {p}", "what are the {l} of {p}",
                          "{l} under {p}"])
        return form.format(l=lv, p=p), {"level": lv, "parent": p}

    def t_parent(self, depth=0):
        k, lv = self.level(exclude=("country", "union_territory"))
        c = self.place(("hood", "city", "district"))
        form = self.pick(["{l} that contains {c}", "which {l} is {c} in", "{l} containing {c}",
                          "what {l} is {c} in", "the {l} where {c} is", "in which {l} is {c}"])
        return form.format(l=lv, c=c), {"level": lv, "child": c}

    def t_neighbors(self, depth=0):
        k, lv = self.level(exclude=("union_territory",))
        o, _ = self.region(depth)
        form = self.pick(["{l} that border {o}", "{l} bordering {o}", "{l} adjacent to {o}", "neighbouring {l} of {o}",
                          "{l} next to {o}", "{l} touching {o}", "{l} sharing a border with {o}", "{l} around {o}",
                          "which {l} border {o}", "{l} that surround {o}"])
        if self.r.random() < 0.15:
            form = self.pick(["neighbours of {o}", "neighbors of {o}", "{o} neighbours", "what borders {o}"])
            return form.format(o=o), {"of": o}
        return form.format(l=lv, o=o), {"level": lv, "of": o}

    def t_children_with_predicate(self, depth=0):
        k, lv = self.level(exclude=("country",))
        pk = self.pick(list(PRED_PRE))
        p = self.parent_for(k, depth) if self.r.random() > 0.15 else None
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
            return form.format(h=head, p=p), {"level": lv, "pred": pr, "parent": p}
        form = self.pick(["{l} {pr} in {p}", "{l} of {p} {pr}", "{l} in {p} that are {pr}", "{p} {l} {pr}",
                          "{l} {pr} of {p}", "which {l} of {p} are {pr}"])
        return form.format(l=lv, pr=pr, p=p), {"level": lv, "pred": pr, "parent": p}

    def t_children_touching(self, depth=0):
        k, lv = self.level(exclude=("country", "union_territory"))
        p = self.parent_for(k, 1)
        o = self.area()
        form = self.pick(["{l} of {p} that border {o}", "{l} in {p} bordering {o}", "{p} {l} next to {o}",
                          "{l} of {p} adjacent to {o}", "{l} in {p} touching {o}", "{l} of {p} on the border with {o}"])
        return form.format(l=lv, p=p, o=o), {"level": lv, "parent": p, "other": o}

    def t_union(self, depth=0):
        a, _ = self.region(depth)
        b, _ = self.region(depth, sub_ok=False)
        form = self.pick(["{a} and {b}", "{a} & {b}", "{a} plus {b}", "both {a} and {b}", "{a} as well as {b}",
                          "{a}, {b}", "{a} together with {b}", "{a} or {b}", "{a} n {b}", "{a}+{b}", "{a} + {b}",
                          "{a} and {b} together", "{a} along with {b}"])
        return form.format(a=a, b=b), {"a": a, "b": b}

    def t_union3(self, depth=0):
        a, b, c = self.area(), self.area(), self.area()
        form = self.pick(["{a}, {b} and {c}", "{a}, {b}, {c}", "{a}, {b} & {c}", "{a}, {b}, and {c}", "{a} {b} n {c}",
                          "{a}, {b} n {c}", "{a}+{b}+{c}", "{a}, {b} as well as {c}"])
        return form.format(a=a, b=b, c=c), {"a": a, "b": b, "c": c}

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
    "parent": 3, "neighbors": 5, "children_with_predicate": 9, "children_touching": 4, "union": 4, "union3": 2,
    "difference": 4, "intersection": 3, "between": 3, "along_coast": 3, "along_border": 2, "along_intl_border": 2,
    "features_in": 8, "features_near": 8, "children_attr": 6, "unsupported": 5,
}


def generate(n: int, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    g = Gen(rng, load_places(rng))
    exclude = set()
    for name in ("gold", "heldout"):
        p = ROOT / "gold" / f"{name}.jsonl"
        if p.exists():
            exclude |= {json.loads(l)["query"].lower().strip() for l in p.read_text().splitlines() if l.strip()}
    names, weights = zip(*TEMPLATE_WEIGHTS.items())
    from geoparse.templates.model import all_templates

    templates = all_templates()
    out, seen = [], set()
    while len(out) < n:
        t = rng.choices(names, weights=weights)[0]
        g.keys, g.subs = {}, set()
        q, slots = g.unsupported() if t == "unsupported" else getattr(g, "t_" + t)()
        if t != "unsupported" and rng.random() < 0.18:
            q = rng.choice(["pls show ", "can u show ", "how do i see ", "i want to see ", "show me ", "find ",
                            "map of ", "can you find ", "", ""]) + q + rng.choice(
                [" on map", " on the map", "?", " pls", " please", "", "", " all in one view"])
        q = re.sub(r"\s+", " ", q).strip()
        if slots:
            slots = {k: re.sub(r"\s+", " ", v).strip() for k, v in slots.items()}
        key = q.lower()
        if key in seen or key in exclude:
            continue
        seen.add(key)
        frame = Frame(template="unsupported") if slots is None else Frame(template=t, slots=slots)
        rec = {"query": q, "frame": frame.to_text(), "template": frame.template, "source": "synthetic"}
        if slots:
            tpl = templates[t]
            rec["closed_keys"] = {k: g.keys[v][tpl.slots[k].type] for k, v in slots.items()
                                  if k in tpl.slots and v in g.keys and tpl.slots[k].type in g.keys[v]}
            rec["sub_slots"] = sorted(k for k, v in slots.items() if v in g.subs)
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
