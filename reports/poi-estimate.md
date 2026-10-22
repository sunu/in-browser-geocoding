# POI data: size and remote query estimate

Date: 2026-10-22. Overture release `2026-10-21.0`, theme `places`.

## Row counts

| Filter | Rows |
|---|---|
| India bbox (68.0, 6.5, 97.5, 37.2) | 5,430,152 |
| India bbox, confidence >= 0.5 | 3,624,120 |

The bbox also includes parts of nearby countries. A clip to India makes the count smaller.

## Local extract size

Measured on a 1 x 1 degree sample around Bengaluru (230,946 rows). Parquet, zstd, sorted by Hilbert curve.

| Columns | Bytes for each row | Estimate for India (all rows) | Estimate for India (confidence >= 0.5) |
|---|---|---|---|
| All Overture columns | 114 | 620 MB | 413 MB |
| Slim: id, name, basic_category, taxonomy, confidence, lon, lat | 52 | 283 MB | 189 MB |

For comparison, the Geofabrik OSM extract `india-latest.osm.pbf` is 1.71 GB. It needs extra processing (osmium) to get POIs.

## Remote query (DuckDB on S3, no local copy)

Query: hospitals in a small bbox.

| Query | Time |
|---|---|
| First query in a new process (Koramangala) | 8 to 16 s |
| Next query, other area (Indiranagar) | 1.2 s |
| Next query, large area (Goa) | 1.4 s |
| Same query again | 0.3 s |

The first query reads the Parquet metadata of all files. After that, DuckDB caches the metadata.

## Recall compared with Photon

Hospitals in the Koramangala bbox: Overture `places` has 134. Photon returned 27 (with the tag filter and the text "hospital").

## Recommendation

Use a local slim extract with all rows (283 MB). Put a minimum confidence in the policy config. Reasons:

1. The first remote query is too slow (8 to 16 s) for a CLI or a cold start.
2. The local extract has no network dependency and no rate limit.
3. 283 MB is similar to the current `geoparse.duckdb` (380 MB).

Remote queries are possible for a long-running server, because warm queries take 0.3 to 1.4 s.
