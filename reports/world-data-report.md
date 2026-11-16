# World data report (plan-008, phase 0)

Date: 2026-11-16. Overture release `2026-10-21.0`. Raw numbers: `reports/world-data.json`.

## 1. Build

Command:

```sh
GEOPARSE_SCOPE=world uv run python -m geoparse.data.build_extract
GEOPARSE_SCOPE=world uv run python scripts/export_web.py data --out data/build-world/web
GEOPARSE_SCOPE=world uv run python scripts/measure_world.py
```

| Step | Time | Output |
|---|---|---|
| Divisions from S3 | 27 s | 4,700,999 rows, 361 MB |
| Division areas from S3 (two passes) | 159 s | 1,082,287 rows, 3.3 GB |
| Simplify areas (0.001 degrees) | 38 s | |
| Layers and layer distances (STRtree) | 47 s | 620,734 rows |
| `geoparse.duckdb` | 100 s | 7.0 GB |
| Web export | 2 s | |

Machine: Apple M-series, 15 cores, 24 GB. The build did not use the GPU desktop.

Layer distance check: for the Indian areas, the world coastline distances are equal to the India build. One county changes at the border tolerance, because the world border layer has all land borders.

## 2. Flat files (one file for each table)

| File | Size |
|---|---|
| `areas.parquet` | 619 MB |
| `divisions.parquet` | 512 MB |
| `names.parquet` | 158 MB |
| `layer_dist.parquet` | 15 MB |
| `layers.parquet` | 9 MB |
| **Total** | **1,313 MB** |

In `divisions.parquet`, the `ancestors` column is 255 MB (50%) and `id` is 91 MB.

## 3. Simplification (0.001 degrees)

| Subtype | Areas | Raw WKB | Simplified WKB | Ratio |
|---|---|---|---|---|
| locality | 556,094 | 2,923 MB | 301 MB | 9.7 |
| county | 38,937 | 1,315 MB | 139 MB | 9.5 |
| neighborhood | 325,055 | 719 MB | 73 MB | 9.9 |
| region | 3,929 | 473 MB | 57 MB | 8.3 |
| localadmin | 21,502 | 318 MB | 37 MB | 8.7 |
| country | 219 | 98 MB | 22 MB | 4.5 |
| macrohood | 47,293 | 131 MB | 11 MB | 12.0 |
| microhood | 89,205 | 59 MB | 9 MB | 6.3 |
| dependency | 53 | 2 MB | 1 MB | 1.1 |

Gate of phase 0: the world `areas` data is less than 1 GB. No change to the simplification is necessary.

## 4. Files for each country

Layout: `divisions`, `areas` and `layer_dist` for each country. Sort: subtype, then Hilbert curve. Row groups of 10,000.

| Item | Value |
|---|---|
| Countries (country codes) | 273 |
| Total | 793 MB (40% less than the flat files, because the sort gives better compression) |
| Median country | 0.37 MB |
| Countries above 25 MB | 7 |
| Countries above 50 MB | 2 |
| Countries above 100 MB | 0 |

Largest countries:

| Country | Divisions | Areas | Layer distances | Total |
|---|---|---|---|---|
| CN | 41.6 MB | 38.1 MB | 0.8 MB | 80.5 MB |
| RU | 13.8 MB | 49.8 MB | 2.8 MB | 66.4 MB |
| FR | 24.8 MB | 20.5 MB | 0.9 MB | 46.3 MB |
| IN | 25.7 MB | 16.9 MB | 0.2 MB | 42.8 MB |
| US | 15.5 MB | 25.0 MB | 0.8 MB | 41.3 MB |
| BR | 11.2 MB | 19.9 MB | 0.2 MB | 31.3 MB |
| DE | 9.1 MB | 15.4 MB | 0.6 MB | 25.1 MB |
| JP | 15.8 MB | 7.2 MB | 0.1 MB | 23.1 MB |
| ID | 9.4 MB | 10.1 MB | 0.3 MB | 19.8 MB |
| PL | 8.9 MB | 9.5 MB | 0.7 MB | 19.1 MB |

## 5. Global name index

Columns: `name_norm`, `name_nospace`, `kind`, `id`, `country`, `subtype`, `class`, `population`. Sort: `name_norm`, then population. Row groups of 10,000. Empty `name_norm` values are not in the index.

| Item | Value |
|---|---|
| Rows | 4,662,101 |
| File | 133 MB |
| Row groups | 456 |
| Footer | 1.4 MB |

Cost of one lookup (2,008 names: a random sample and 8 common names), from the row-group statistics:

| Lookup | Row groups (median, p95, max) | Data (median, p95, max) |
|---|---|---|
| Exact `name_norm` | 1, 1, 2 | 0.29, 0.31, 0.58 MB |
| Prefix (3 characters, for fuzzy search) | 1, 8, 11 | 0.30, 1.74, 3.02 MB |

The first lookup also reads the footer (1.4 MB). Common names (springfield, san jose, victoria, london, paris) are in one row group each.

## 6. Problems found

1. **Names in non-Latin scripts.** `NAME_NORM_SQL` removes all characters other than `a-z` and `0-9`. 1,555,448 names become empty. 580,215 divisions (12%) have no searchable name. Most are in CN (272,343), RU (138,928), JP (89,297) and IR (33,764). Phase 1 must add Unicode normalization (NFKD, remove accents, keep letters of all scripts) or a transliteration. The Python gazetteer and the TS gazetteer must use the same function.
2. **Lookup by `name_nospace`.** The gazetteer uses `name_norm IN (...) OR name_nospace IN (...)`. The file is sorted by `name_norm`, so the `name_nospace` condition cannot use the row-group statistics. A range read of this condition reads the full file. Phase 1 must use one sorted key for both lookups (for example, a second row for each name with `kind = nospace`).
3. **Size of `ancestors`.** This column is 50% of the flat `divisions` file. In the files for each country it is smaller, but it is still the largest column. A parent pointer and a lookup at query time can replace it. This is optional.
4. **Country codes.** The data has 273 country codes and 219 country divisions. Some dependencies and disputed areas have their own code. Phase 3 must define the policy for them.

## 7. Not done in this phase

Range-read latency from Cloudflare R2 in Chromium, Firefox and WebKit. This test needs an upload to R2. The numbers in section 5 give the number of row groups and bytes. They do not give the time.
