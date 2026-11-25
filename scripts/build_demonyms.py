"""Write geoparse/data/demonyms.yaml: the English demonyms of countries and first-level regions (Wikidata P1549), as
names of the place ("Indian states" are the states of India; plan-039).

The gazetteer uses a demonym only if it is the whole name text ("Indian Ocean" stays the ocean). A demonym is kept if
its place is an exact country or region name of the extract. A demonym of two different places is dropped
("Congolese"). Historical states lose to the current name ("Russian": Russia, not the Russian Empire), and a name
that contains another name loses to it ("Danish": Denmark, not the Kingdom of Denmark).

Usage: GEOPARSE_SCOPE=world uv run python scripts/build_demonyms.py
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict

import yaml

from geoparse.config import PACKAGE_DIR
from geoparse.execute.data import Store

SPARQL = "https://query.wikidata.org/sparql"
CLASSES = ["wdt:P31 wd:Q6256", "wdt:P31 wd:Q3624078", "wdt:P31/wdt:P279 wd:Q10864048",
           "wdt:P31/wdt:P279/wdt:P279 wd:Q10864048"]
# Words that are not a demonym of one place.
SKIP = {"easterner", "northwesterner", "westerner", "southerner", "northerner"}
OUT = PACKAGE_DIR / "data" / "demonyms.yaml"


def query(cls: str) -> list[tuple[str, str]]:
    q = (f'SELECT ?label ?dem WHERE {{ ?item {cls} . ?item wdt:P1549 ?dem . FILTER(LANG(?dem) = "en") '
         f'?item rdfs:label ?label . FILTER(LANG(?label) = "en") }}')
    req = urllib.request.Request(f"{SPARQL}?{urllib.parse.urlencode({'query': q})}",
                                 headers={"Accept": "application/sparql-results+json",
                                          "User-Agent": "geoparse-build/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        rows = json.load(r)["results"]["bindings"]
    return [(x["dem"]["value"].strip(), x["label"]["value"].strip()) for x in rows]


def main() -> None:
    store = Store()
    places: dict[str, set[str]] = defaultdict(set)
    for cls in CLASSES:
        for dem, label in query(cls):
            if dem.lower() in SKIP or dem.lower() == label.lower() or " resident" in dem or " people" in dem:
                continue
            places[dem].add(label)
    known: dict[str, bool] = {}

    def is_place(name: str) -> bool:
        if name not in known:
            known[name] = any(c.subtype in ("country", "dependency", "region")
                              for c in store.search(name, fuzzy=False, limit=5))
        return known[name]

    out, dropped = {}, []
    for dem, labels in sorted(places.items(), key=lambda x: x[0].lower()):
        found = sorted(x for x in labels if is_place(x))
        # "Kingdom of Denmark" and "Denmark": the shorter name.
        found = [x for x in found if not any(y != x and re.fullmatch(rf".+ of (the )?{re.escape(y)}", x, re.I) for y in found)]
        if len(found) == 1:
            out[dem.lower()] = found[0]
        elif len(found) > 1:
            dropped.append(f"{dem}: {found}")
    head = ("# English demonyms of countries and first-level regions (Wikidata P1549) as names of the place.\n"
            "# Written by scripts/build_demonyms.py. Used only for the whole name text (\"Indian\", not \"Indian Ocean\").\n")
    OUT.write_text(head + yaml.safe_dump(out, allow_unicode=True, sort_keys=True))
    print(f"{len(out)} demonyms written to {OUT}; {len(dropped)} with two places dropped: {dropped}")


if __name__ == "__main__":
    main()
