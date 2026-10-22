# Phase 0 report: spikes

Date: 2026-10-22.

## (a) Jev through OpenRouter

Script: `scripts/spike_jev.py`. Endpoint: `POST https://openrouter.ai/api/alpha/decisions`. Model: `typesafe/jev-1.13`. The response names the snapshot `typesafe/jev-1.13-20260917`.

Query: "hospitals within 2 km of coastal districts of Odisha".

| Question | Type | Options | Median latency | Cost per call | Input tokens | Answer | Confidence | Same answer in 5 runs |
|---|---|---|---|---|---|---|---|---|
| Template family | choice | 8 | 490 ms | $0.0000232 | 552 | `features` | 1.0 | yes |
| `pick_split` | choice | 4 | 510 ms | $0.0000194 | 463 | correct split | 1.0 | yes |
| `is_subquery` ("coastal districts of Odisha") | noul | 2 | 512 ms | $0.0000154 | 367 | yes, p = 0.98 | 0.96 (`abs(2p-1)`) | yes |
| All three in one request | 3 questions | | 522 ms | $0.0000355 | | same answers | | yes |

Output shape: `answers.<id>` has `type`, `choice`, `probabilities` (one value per option), and `confidence` for a choice. A noul has only `noul` (the probability of yes). `usage.cost` gives the cost in USD.

Findings:

1. The answers did not change in 5 runs. The probabilities did not change either.
2. One request with three questions has the same latency as one request with one question. Thus the orchestrator puts all independent decisions of one level into one request. A depth-2 query then needs about 3 to 5 requests in sequence, not 8 to 10.
3. Cost is very low: about $0.00002 for each request.

## (b) GLiNER-small through ONNX

Script: `scripts/spike_gliner.py`. Model: `onnx-community/gliner_small-v2.1`, file `onnx/model_int8.onnx` (183 MB). Runtime: `onnxruntime` and `tokenizers`. There is no `torch` dependency. Labels: location, landmark, street, facility type.

- Load time: 2.3 s. Latency: 3 ms median, 5 ms max, on an Apple Silicon laptop.
- All place names were found, including the misspelled "maharastra".
- "MG Road" was labeled `street` (0.93).
- Two problems: "coastal states" was labeled `location`, and "northern Karnataka" was one span. A rule step after GLiNER removes predicate, level, and direction words from spans.

## (c) India extract

Script: `geoparse/data/build_extract.py`. Overture release `2026-10-21.0`. Build time: 2 min 20 s.

| File | Rows | Size |
|---|---|---|
| `divisions.parquet` | 360,171 | 25.5 MB |
| `division_area.parquet` | 62,168 | 161.1 MB |
| `coastline.parquet` | 96 lines | 0.1 MB |

Notes:

- The filter is `country = 'IN'` and the India bbox. Overture divisions already have a country, so a clip to the India boundary is not necessary.
- The extract also keeps the country polygons of 10 nearby countries (config `extra_countries`).
- Overture gives `local_type = state` for all 37 Indian regions, also for union territories. The UT list is in the policy config.
- One region has no ISO code (a disputed area from another perspective). The config excludes regions without a code.
- The coastal test with a 3 km tolerance gives 13 regions: 9 states and 4 UTs (AN, DH, LD, PY). This agrees with the expected 9 coastal states.
- The coastal test with a UTM transform of each full state polygon takes 38 s. The executor must use simplified polygons for predicates.

## (d) DuckDB spatial functions

Script: `scripts/spike_duckdb_spatial.py`. DuckDB 2.0.0.

All needed functions are available: `ST_Touches`, `ST_Intersects`, `ST_Within`, `ST_DWithin`, `ST_Buffer`, `ST_Centroid`, `ST_Union_Agg`, `ST_Intersection`, `ST_Difference`, `ST_Transform`, `ST_ConvexHull`, `ST_MakeEnvelope`, `ST_Simplify`, and others.

Notes:

- DuckDB 2.0 needs `SET geometry_always_xy = true`. Without it, `ST_Transform` refuses EPSG:4326 input.
- Overture geometries have the CRS `OGC:CRS84`. All other geometries must use the same CRS, or DuckDB refuses the operation.
- `ST_Transform` accepts a CRS from a column, so each row can use its own UTM zone.
- A 2 km buffer in UTM 43N has an area of 12.49 km². A true circle has 12.57 km². The difference (0.6 %) comes from the polygon approximation of the circle.
