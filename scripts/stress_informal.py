"""Run informal queries without gold labels. Shows the template, slots, or the Unsupported reason."""
import json
import sys

from geoparse.api import parse

QUERIES = [
    "places within 5km radius of koramangala",
    "hospitals around indiranagar 2km",
    "what districts does Karnataka have",
    "which states touch the sea",
    "kerala ka coastal area",
    "bangalore north",
    "districts sharing border with nepal",
    "everything between bangalore and mysore",
    "show me all the coastal districts in india",
    "goa beaches",
    "north karnataka districts",
    "top cities in tamil nadu",
    "hospitals in bangalore except whitefield",
    "states with coastline",
    "area within 10 km of the karnataka goa border",
    "chennai to bangalore",
    "metro stations near MG road",
    "Delhi NCR",
    "union territories of india",
    "districts of karnataka bordering both goa and maharashtra",
]
prov = sys.argv[1] if len(sys.argv) > 1 else "jev"
for q in QUERIES:
    r = parse(q, prov)
    out = r.template + " " + json.dumps(r.slots, ensure_ascii=False) if r.ok else f"UNSUPPORTED: {r.unsupported.reason}"
    print(f"{q!r:60s} -> {out[:150]}")
