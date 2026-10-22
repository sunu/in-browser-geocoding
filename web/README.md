# geoparse in the browser

This directory is a TypeScript version of geoparse that runs entirely in a browser tab. It uses the same models and data as the Python package.

| Part | Browser implementation |
|---|---|
| Parse frames | T5 (int8 ONNX, ONNX Runtime Web), beam search in TypeScript |
| Decisions | Local cross-encoder (int8 ONNX) and rules. No Jev (it needs an API key). |
| Data | DuckDB-WASM with the spatial extension. Small tables are loaded at start; `places.parquet` is read with HTTP range requests. |
| Geocoder | Photon (from the browser) |
| Map | MapLibre GL, OpenFreeMap basemap |

## Limits of this version

- The parser uses T5 frames only. The literal split patterns of the Python package are not ported. If T5 gives no usable frame, the result is `Unsupported`.
- No GLiNER spans. The whole slot text is the anchor.
- Area polygons are the simplified ones (approximately 100 m). The Python version uses the full polygons for output.

## Setup

1. Build the Python side first (see the README in the repository root): the extract, the T5 model, and the local decision model.
2. Export the browser files:

   ```sh
   uv run python scripts/export_onnx.py        # web/public/models (ONNX, int8)
   uv run python scripts/export_web.py all     # web/public/bundle.json and web/public/data
   ```

3. Install and start:

   ```sh
   cd web
   npm install
   npm run dev                                 # http://localhost:5173
   ```

The server must support HTTP range requests and send `Accept-Ranges: bytes` for `/data/`. The Vite config does this for the dev server. Static hosts such as S3 or Cloudflare do this by default.

## Checks

```sh
npm test                                      # unit tests (Vitest)
uv run python ../scripts/web_reference.py     # Python reference parses (run in the repository root)
npx tsx scripts/parity.ts                     # JS parse = Python parse (fp32 models)
npx tsx scripts/parity.ts --int8              # with the int8 models
npx tsx scripts/exec_parity.ts                # JS executor = gold expected IDs
npx tsx scripts/browser_smoke.ts [chromium|firefox|webkit] [--reload]   # headless: load, queries, console errors (dev server must run)
npx tsx scripts/load_check.ts chromium firefox webkit chrome            # page load in several browsers
npx tsx scripts/screenshot.ts "a query"       # screenshot to test/screenshot.png
```

## Use as a library

```ts
import { load } from "./src/geoparse.ts";

const gp = await load("");                    // base URL of bundle.json, models/, data/
const { parse, result } = await gp.run("districts near the sea in Gujarat");
```
