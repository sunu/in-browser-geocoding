"""Paraphrase queries that test language understanding (not vocabulary). No gold labels."""
import sys

from geoparse.api import parse

QUERIES = [
    "districts near the coast in Gujurat",
    "districts near the sea in Gujarat",
    "states by the ocean",
    "which states touch the sea",
    "coastal states",
    "states without a coastline",
    "districts in Kerala away from the sea",
    "districts of Tamil Nadu that have a beach",
    "seaside districts of Andhra Pradesh",
    "states with no access to the sea",
    "districts on India's frontier in Rajasthan",
    "Gujarat districts on the Pakistan border",
    "big cities in Karnataka with more than ten lakh residents",
    "metros in Maharashtra with over a million people",
    "the top half of Karnataka",
    "a little north of Pune",
    "clinics close to Indiranagar",
    "places to eat in Koramangala",
    "where can I get medicines near Jayanagar",
    "petrol bunks around Whitefield",
]
prov = sys.argv[1] if len(sys.argv) > 1 else "jev"
ok = 0
for q in QUERIES:
    r = parse(q, prov)
    ok += r.ok
    print(f"{q!r:62s} {r.template if r.ok else 'UNSUPPORTED'} {r.slots if r.ok else r.unsupported.reason}"[:230])
print(f"parsed {ok}/{len(QUERIES)}")
