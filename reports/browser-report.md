# Report: geoparse in the browser (plan-007)

Date: 2026-10-22. Code: `web/`.

## 1. Summary

The full geocoder runs in one browser tab: the T5 frame model, the local decision model, the gazetteer, and the DuckDB executor. The only network calls after loading are Parquet range requests (places), Photon (streets and landmarks), and basemap tiles.

| Measure | Result |
|---|---|
| Parse parity with Python (fp32 models), 696 queries | same DAG for 696 of 696 |
| Parse parity with Python (int8 models) | same DAG for 685 of 696 (98.4 %) |
| Executor parity, gold and held-out sets | same IDs for 88 of 88 set results; 28 of 28 geometry results produced |
| Start-up (headless Chromium, local server) | 3.7 s, 228 MB transferred |
| Query time (5 example queries) | 0.3 to 2.2 s; median approximately 1 s |
| Data transferred during the 5 queries | 8.5 MB (range requests) |
| Console errors | 0 |

## 2. Download size at start-up

| File | Size |
|---|---|
| T5 decoder (int8) | 58.5 MB |
| T5 encoder (int8) | 35.5 MB |
| Cross-encoder (int8) | 33.9 MB |
| divisions.parquet | 26.7 MB |
| areas.parquet (simplified polygons) | 22.8 MB |
| ONNX Runtime WASM | 14.2 MB |
| names.parquet | 10.4 MB |
| DuckDB WASM | 7.1 MB |

`places.parquet` (281 MB) is not downloaded. DuckDB-WASM reads only the row groups it needs.

## 3. Model accuracy after int8 quantization

| Model | fp32 | int8 |
|---|---|---|
| T5 top-1 core frame, LLM dev | 94.3 % | 93.6 % |
| T5 top-1 core frame, LLM test | 91.9 % | 91.5 % |
| Cross-encoder, validation questions | 98.0 % | 98.0 % (99.75 % agreement with fp32) |

## 4. Problems found and fixed

1. **Full download of the places file.** DuckDB-WASM sent a GET without a Range header. Fix: open the database with `reliableHeadRequests: true` and `allowFullHTTPReads: false`, and send `Accept-Ranges: bytes` from the dev server.
2. **Concurrent model runs.** ONNX Runtime Web cannot run one session twice at the same time. Fix: a queue for each session.
3. **Basemap.** The CARTO raster tiles now need an API key. Fix: OpenFreeMap (no key).
4. **Bundler.** Vite followed the Node.js-only import of `onnxruntime-node`. Fix: import Node.js-only modules through a variable.

## 5. Open items

1. T5 decoder without a key-value cache: approximately 0.3 to 0.7 s for each T5 call in the browser. A decoder with a cache can make this approximately 3 times faster.
2. The start-up download (228 MB) can be smaller: share the embedding between the T5 encoder and decoder, or use a smaller T5.
3. The literal split patterns and GLiNER are not ported.
4. Model and data files are cached by the browser HTTP cache only. A Cache Storage layer would make the second start faster and work offline.
