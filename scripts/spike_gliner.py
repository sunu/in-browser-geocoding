"""Spike 0(b): run GLiNER-small (ONNX, int8) on 10 English queries."""
import time

from geoparse.parse.gliner_onnx import get_model

QUERIES = [
    "Koramangala",
    "2 km around MG Road Bangalore",
    "coastal states in India",
    "hospitals within 2 km of coastal districts of Odisha",
    "schools near Indiranagar",
    "northern Karnataka",
    "districts that border Pune",
    "Kerala and Tamil Nadu except Palakkad",
    "between Mysore and Bengaluru",
    "cities in maharastra with populaton over 1 million",
]
LABELS = ["location", "landmark", "street", "facility type"]

t0 = time.time()
m = get_model()
print(f"load: {time.time() - t0:.2f}s")
lat = []
for q in QUERIES:
    t0 = time.time()
    spans = m.predict(q, LABELS, threshold=0.3)
    lat.append(time.time() - t0)
    print(f"{lat[-1]*1000:6.0f} ms  {q!r}")
    for s in spans:
        print(f"           {s.text!r:28s} {s.label:14s} {s.score}")
lat.sort()
print(f"median latency: {lat[len(lat)//2]*1000:.0f} ms, max: {lat[-1]*1000:.0f} ms")
