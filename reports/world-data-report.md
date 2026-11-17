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

5. **Divisions with no country.** Some divisions have no `country` value. They go to the partition `__HIVE_DEFAULT_PARTITION__`. Phase 1 must put them in a named partition or remove them.

## 7. Range-read latency from Cloudflare R2

Setup:

- Bucket `geoparse-world-test` (location APAC), public `r2.dev` URL, CORS for GET and HEAD.
- Files: `global/names.parquet` (section 5) and the files of CN, IN and LU.
- Client: Kolkata, India. The nearest Cloudflare location is CCU. The `r2.dev` answers come from MRS (Marseille).
- Test: `web/latency.html` and `web/scripts/latency_check.ts`. DuckDB-WASM with the settings of `web/src/execute/db.ts`. 20 exact name lookups and 5 prefix lookups, each in a new DuckDB instance, with and without `parquet_metadata_cache`.

Single range requests with curl: 0.41 to 1.03 s to the first byte.

| Browser | Metadata cache | First lookup | Exact lookup (median, p95) | Prefix lookup (median, max) | Requests (25 lookups) | Data |
|---|---|---|---|---|---|---|
| Chromium | off | 8.7 s | 2.26, 3.33 s | 1.17, 5.77 s | 106 | 12.9 MB |
| Chromium | on | 6.7 s | 1.59, 2.67 s | 1.07, 5.49 s | 106 | 12.9 MB |
| Firefox | off | 7.9 s | 2.14, 4.07 s | 2.03, 4.47 s | 106 | 13.8 MB |
| Firefox | on | 5.2 s | 1.91, 6.64 s | 1.79, 5.27 s | 106 | 13.8 MB |
| WebKit | off | 6.1 s | 2.13, 6.39 s | 1.77, 4.66 s | 106 | 13.8 MB |
| WebKit | on | 5.2 s | 1.95, 3.26 s | 1.90, 4.58 s | 106 | 13.8 MB |

Full download of the files of one country (`fetch()`, all three files in parallel):

| Browser | LU (0.2 MB) | IN (42.7 MB) | CN (80.4 MB) |
|---|---|---|---|
| Chromium | 1.7 s | 15.3 s | 6.0 s |
| Firefox | 0.9 s | 3.0 s | 2.6 s |
| WebKit | 0.9 s | 4.1 s | 2.8 s |

Conclusions:

1. The time of one lookup is the request latency, not the bandwidth. Each lookup uses approximately 4 requests in sequence, at 0.4 to 0.6 s each. The data for each lookup is small (approximately 0.5 MB).
2. With `r2.dev`, a name lookup with DuckDB range reads takes approximately 2 s. A query with 2 or 3 names takes 4 to 6 s. This is too slow.
3. The metadata cache removes only part of the time. The number of requests does not change.
4. Full downloads are fast. CN (80 MB) takes 3 to 6 s.
5. The Chromium IN time (15.3 s) is one slow sample. The other browsers took 3 to 4 s for the same files.

## 8. Range-read latency with a custom domain and the edge cache

Setup changes from section 7:

- Custom domain `files.geoparse.labs.sunu.in` on the bucket (zone `sunu.in`, minimum TLS 1.2).
- Cache Rule on the zone: host `files.geoparse.labs.sunu.in`, eligible for cache, edge TTL 1 month, browser TTL 1 day.
- The answers still come from MRS (Marseille). Ping from the client: 160 to 210 ms.

Single requests with curl, cached (`cf-cache-status: HIT`), 300 kB range:

| Connection | Time to first byte | Total |
|---|---|---|
| New connection (TCP and TLS) | 0.41 to 0.57 s | |
| Reused HTTP/2 connection | 0.15 s | 0.22 s |

Browsers, second run (edge cache warm):

| Browser | Metadata cache | First lookup | Exact lookup (median, p95) | Prefix lookup (median, max) |
|---|---|---|---|---|
| Chromium | off | 7.7 s | 0.72, 1.14 s | 0.62, 2.39 s |
| Chromium | on | 5.0 s | 0.52, 0.85 s | 0.37, 1.74 s |
| Firefox | off | 5.8 s | 1.01, 1.34 s | 1.00, 1.90 s |
| Firefox | on | 5.3 s | 0.99, 1.30 s | 0.85, 1.90 s |
| WebKit | off | 7.6 s | 1.23, 4.04 s | 1.03, 3.64 s |
| WebKit | on | 6.3 s | 1.01, 1.40 s | 0.94, 1.97 s |

Full download of the files of one country: IN (42.7 MB) 2.4 to 4.3 s, CN (80.4 MB) 3.2 to 7.5 s.

Conclusions:

1. The edge cache makes the exact lookups 2 to 4 times faster. Chromium: 0.5 s. Firefox and WebKit: 1.0 s.
2. The first lookup still takes 5 to 8 s (footer and metadata of a 133 MB file, many requests).
3. One request on a reused connection takes approximately 0.2 s from this client. The name shards of plan-010 (one `fetch()` for each lookup) are expected to take approximately 0.2 s for each lookup, and no first-lookup cost except `index.json`.
4. The Cloudflare location is far from the client (free plan). Requests from India cannot be faster than approximately 0.15 s.

## 9. Country layout and name shards (phase 1b)

Command:

```sh
GEOPARSE_SCOPE=world uv run python scripts/export_web.py data --layout country --out data/build-world/web
```

The export compares the output with the tables in `geoparse.duckdb` (`verify_country_layout`): the same rows in the country files, each key in one shard, the index agrees with the shards.

### 9.1 Name sources

New name sources (plan-013): all values of `names.common`, all values of `names.rules`, and Latin keys from transliteration at build time (Cyrillic and Greek tables, pinyin for Chinese names in CN, TW, HK, MO, SG).

| Kind | Name rows | Divisions |
|---|---|---|
| primary | 4,700,999 | 4,700,999 |
| common | 2,862,424 | 1,423,065 |
| translit | 1,570,435 | 1,046,083 |
| en | 884,723 | 884,723 |
| alt | 823,352 | 513,892 |

Divisions with no Latin key: 143,187 (before: 580,215). CN: 172 (before: 272,343). RU: 2 (before: 138,928). Most of the remaining divisions are in JP (90,003) and IR (33,512). Japanese and Arabic-script transliteration is not done (plan-013).

### 9.2 Sizes

| Part | Files | Size |
|---|---|---|
| Country files (`divisions`, `areas`, `layer_dist`) | 272 countries | 811.5 MB (CN 81.9, RU 67.4, FR 47.3, IN 43.8, US 42.1 MB) |
| `global/admin.parquet` (attributes of countries, dependencies, regions, counties, localadmin) | 1 | 3.5 MB |
| `global/admin_areas.parquet` (polygons of countries, dependencies, regions) | 1 | 45.6 MB |
| `global/layers.parquet` | 1 | 9.4 MB |
| Name shards | 1,082 (median 181 kB, maximum 272 kB) | 194.2 MB |
| `names/index.json` | 1 | 87 kB |

Name shard design:

- Key: the name key without spaces. Two names with equal keys have equal keys without spaces, so one key gives the same matches as `name_norm OR name_nospace`.
- One row for each key and division (the best name kind). 8,940,614 rows.
- `n`: an integer id. The country `divisions` file maps `n` to the Overture id. Before this change, the Overture id column used 199 MB of 496 MB.
- `region_n`, `county_n`: integer references to `global/admin.parquet`. `locality_name` is a string (localities are not in `admin.parquet`).
- `name_en` only when it is different from `name`.

### 9.3 Latency of a name lookup with shards

Setup as in section 8 (custom domain, edge cache, client in Kolkata). Test: `MODE=shards web/scripts/latency_check.ts`. Each lookup finds the shard in `index.json`, downloads the shard with one `fetch()`, and queries it with DuckDB-WASM. Third run (edge cache warm):

| Browser | `index.json` | First lookup | Exact lookup (median, p95) | Prefix lookup (median, max) |
|---|---|---|---|---|
| Chromium | 0.58 s | 1.14 s | 0.21, 0.24 s | 0.19, 0.49 s |
| Firefox | 0.65 s | 0.99 s | 0.21, 0.25 s | 0.18, 0.49 s |
| WebKit | 0.79 s | 1.06 s | 0.42, 3.26 s | 0.47, 1.25 s |

The second run gave WebKit 0.22 s (median) and 0.35 s (p95). The WebKit values of the third run are one slow sample.

Note: the browser tests of sections 7 and 8 added a query parameter (`?s=...`) to each URL. The edge cache key contains the query string, so these requests did not use the edge cache. The values in section 8 for the browsers are therefore values without the edge cache.

Result: an exact lookup takes approximately 0.2 s (target: less than 0.3 s). The first lookup also loads `index.json` and opens the connection (approximately 1 s).

## 10. World data in the page (phase 4)

Setup: page on the Vite dev server, data from `https://files.geoparse.labs.sunu.in/2026-10-21.0` (custom domain, edge cache), client in Kolkata, start view on India. Test: `PAGE="http://localhost:5180/?data=https://files.geoparse.labs.sunu.in/2026-10-21.0" npx tsx web/scripts/world_smoke.ts <browser>`. The map view is set on the country of each query. Logs: `logs/world-r2-<browser>.log`.

Changes:

- `manifest.json` has a `bbox` for each country (extent of the division points). The gazetteer uses it for the bounds of the view penalty.
- The gazetteer loads only the countries that can be in the result (bounded loading). Check: `web/scripts/bounded_check.ts`, the same candidates as the old rule in 80 of 80 cases (20 names, 4 views), 136 country loads (old rule: 348).
- `global/layers.parquet` (9.4 MB) is loaded only for a query with a `Layer` operation.
- The description of a place gives the country relative to the country of the view.
- The page detects the layout from the content of `manifest.json`, not from the content type.

### 10.1 Start-up

| Browser | Ready | Data |
|---|---|---|
| Chromium | 15.2 s | 47.4 MB |
| Firefox | 11.5 s | 47.3 MB |
| WebKit | 11.3 s | 47.4 MB |

Data at start-up: `global/admin.parquet` 3.5 MB, `country=IN` 43.8 MB (`divisions` 26.9, `areas` 16.8, `layer_dist` 0.2), `manifest.json` and `names/index.json` 0.03 MB. The total transfer (models and WASM included) is approximately 220 MB.

### 10.2 Queries

Time from submit to result, and data downloaded for the query. The first query in a country loads the files of that country.

| View | Query | Chromium | Firefox | WebKit | Data | Result |
|---|---|---|---|---|---|---|
| IN | Kerala except Palakkad | 3.3 s | 1.1 s | 2.1 s | 2.4 MB | 1 |
| IN | districts near the sea in Gujarat | 4.1 s | 2.7 s | 4.7 s | 9.6 MB | 16 |
| US | counties of Nevada | 33.5 s | 13.0 s | 13.0 s | 89.0 MB | 0 (wrong) |
| US | states that border Nevada | 0.8 s | 0.9 s | 2.1 s | 0 | 5 |
| US | Springfield | 7.6 s | 6.4 s | 6.7 s | 18.9 MB | 1 |
| FR | Lyon | 6.9 s | 6.8 s | 6.8 s | 48.1 MB | 1 |
| FR | districts of Bretagne | 3.3 s | 1.6 s | 2.0 s | 0.2 MB | 4 |
| BR | cities in Minas Gerais with population over 1 million | 7.4 s | 7.2 s | 11.3 s | 33.4 MB | 0 (wrong) |
| BR | Recife | 2.3 s | 1.5 s | 2.4 s | 0.2 MB | 1 |
| JP | Osaka | 14.8 s | 12.3 s | 16.8 s | 92.0 MB | 1 |
| JP | Hokkaido | 2.2 s | 0.9 s | 1.3 s | 0.2 MB | 1 |
| US | San Jose | 10.8 s | 10.1 s | 10.2 s | 9.7 MB | 1 |
| IN | San Jose | 13.0 s | 12.9 s | 12.5 s | 8.9 MB | 1 |

Console errors: 0 in all browsers.

Results:

- A query in a country that is already loaded takes 1–4 s. Most of this time is the parse.
- The first query in a large country takes 7–17 s. Most of this time is the download (JP 92 MB, US 89 MB, FR 48 MB).
- "San Jose" loads 3–4 small countries (bounded loading) and makes 10–14 requests. The time is in the requests, not in the data.
- "counties of Nevada": the parser reads "counties" as the level "country". The executor then loads `global/admin_areas.parquet` (45.6 MB) and tests the country polygons. Execute time: Chromium 26.0 s, Firefox 5.6 s, WebKit 5.2 s.
- "Minas Gerais" goes to Photon: "minas" is one edit from the street word "minar".

## 11. Hospitals and schools (phase 5)

### 11.1 Build

Command: `GEOPARSE_SCOPE=world uv run python -m geoparse.data.build_extract --only-poi`, then `GEOPARSE_SCOPE=world uv run python scripts/export_web.py poi --out data/build-world/web`. One scan of the Overture places theme on S3: 15.6 minutes.

| File | Category items | Rows | Size | Row groups |
|---|---|---|---|---|
| `poi/hospitals.parquet` | hospital | 502,004 | 25.2 MB | 50 |
| `poi/schools.parquet` | school, preschool | 1,729,263 | 86.1 MB | 169 |

Columns: `id`, `name`, `cats`, `confidence`, `lon`, `lat`. Minimum confidence: `policy.places_min_confidence` (0.5). Hilbert sort on the world extent, row groups of 10,000 rows.

The schools file has more rows than the estimate of section 2.3 of plan-008 (706,067). The match uses all levels of the taxonomy hierarchy, as the India places file does. Rows by first category: `place_of_learning` 902,184, `school` 694,411, `child_care_and_day_care` 77,802, `public_school` 53,211.

Other categories (clinics, pharmacies, banks and others) have no world file. The executor uses Photon for them and adds a note to the result.

### 11.2 Queries

Setup as in section 10. Test: `SET=poi PAGE=... npx tsx web/scripts/world_smoke.ts <browser>`. Logs: `logs/poi-r2-<browser>.log`. Time is from submit to result. "POI" is the requests and bytes for the point file only.

| View | Query | Results | Chromium | Firefox | WebKit | POI requests | POI data |
|---|---|---|---|---|---|---|---|
| IN | hospitals in Ernakulam | 503 | 3.3 s | 3.5 s | 5.0 s | 9 | 1.4–1.8 MB |
| IN | schools in Pune | 3,339 | 5.3 s | 5.1 s | 6.1 s | 9 | 1.4–1.8 MB |
| US | hospitals in San Francisco | 151 | 12.2 s | 11.6 s | 12.6 s | 8 | 0.7–0.8 MB |
| US | schools in Reno | 168 | 8.4 s | 6.6 s | 7.6 s | 11 | 1.0–1.1 MB |
| FR | hospitals in Lyon | 118 | 8.8 s | 8.1 s | 9.0 s | 8 | 0.7–0.8 MB |
| BR | schools in Recife | 1,063 | 7.0 s | 7.4 s | 7.7 s | 9 | 1.4–1.8 MB |
| JP | hospitals in Sapporo | 523 | 8.3 s | 9.8 s | 9.8 s | 12 | 1.7–2.2 MB |
| FR | pharmacies in Lyon (Photon) | 36 | 14.4 s | 11.0 s | 19.3 s | 0 | 0 |

Console errors: 0 in all browsers.

Results:

- The Features operation takes 1.3–2.9 s over R2 (0.05–0.7 s from the local dev server). The time is in 8–12 range requests at the latency of section 8.
- Most of the time of the first query in a country is the download of the country files (for example US 58 MB: "San Francisco" loads 6 countries).
- A category with no world file uses Photon: 9 tiles with 1 s between the requests (9–16 s).

### 11.3 Firefox and cached HEAD responses

For a URL in `read_parquet()`, DuckDB-WASM first sends a HEAD request without `Range`. Then it sends a HEAD request with `Range: bytes=0-` and needs the answer 206. If the server allows caching (R2: `max-age=86400`), Firefox answers the second request from its cache with 200. DuckDB-WASM then cannot open the file. The page now registers each range-read file with `registerFileURL` and gives the name to `read_parquet()`. DuckDB then does not send the HEAD request without `Range`.

The Vite dev server sends `Cache-Control: no-cache`. Firefox then sends conditional requests, and DuckDB-WASM cannot read a 304 answer. The dev server removed the conditional headers only for `/data/`. It now also does this for `/countries/` and `/world/`.
