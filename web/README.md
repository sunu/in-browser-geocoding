# geoparse in the browser

This directory is a TypeScript version of geoparse that runs entirely in a browser tab. It uses the same models and data as the Python package.

| Part | Browser implementation |
|---|---|
| Parse frames | T5 (int8 ONNX, ONNX Runtime Web), beam search in TypeScript |
| Decisions | Local cross-encoder (int8 ONNX) and rules. No Jev (it needs an API key). |
| Data | DuckDB-WASM with the spatial extension. Small tables are loaded at start; `places.parquet` and the world point files (`poi/`) are read with HTTP range requests. The world data loads the files of each country when a query needs them. |
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

## Deployment

The page is a Cloudflare Worker with static assets. The data and the models are on Cloudflare R2, because many files are larger than the file limit of static assets (25 MiB).

| Part | Location |
|---|---|
| Page (JS, WASM of ONNX Runtime, `bundle.json`) | Worker `geoparse`, domain `gazetini.labs.sunu.in` |
| Data (country layout of one Overture release) | R2 bucket `geoparse-world-test`, `https://files.geoparse.labs.sunu.in/<release>/` |
| Models (int8 ONNX, tokenizers) | Same bucket, `https://files.geoparse.labs.sunu.in/models/<hash>/` |

Deploy (in the repository root, after `npx wrangler@4.164.0 login`):

```sh
GEOPARSE_SCOPE=world uv run python scripts/export_web.py data --layout country --out data/build-world/web
uv run python scripts/deploy_web.py --dry-run     # show the files to upload
uv run python scripts/deploy_web.py               # upload data and models, build and deploy the page
```

The script uploads only new or changed files. It keeps the MD5 of each uploaded file in `.cache/deploy/`. The model path contains a hash of the model files. The page asks for `manifest.json?v=<hash>` and `names/index.json?v=<hash>`. Thus a new model or a new manifest gets a new URL, and no cache purge is necessary.

Settings in the Cloudflare dashboard (zone `sunu.in`):

1. R2 bucket: custom domain `files.geoparse.labs.sunu.in`. CORS: origins `*`, methods `GET` and `HEAD`, headers `*`, exposed headers `Content-Length`, `Content-Range`, `Accept-Ranges`, `ETag`.
2. Cache Rule for host `files.geoparse.labs.sunu.in`: eligible for cache, edge TTL 1 month, browser TTL 1 day, status codes 400–599 not cached. The files of a release do not change.
3. Worker `geoparse`: the deploy script sets the custom domain `gazetini.labs.sunu.in` (and its DNS record). The `_headers` file of the build sets COOP and COEP (ONNX Runtime threads need `SharedArrayBuffer`).

Notes:

- The edge cache keeps one copy of a file for each `Origin` value. A purge by URL in the dashboard removes only the copy for requests without `Origin`. To remove all copies, purge by hostname.
- DuckDB-WASM cannot read a 304 answer, and it needs a 206 answer to a HEAD request with `Range`. The page registers the range-read files with `registerFileURL` and adds a session parameter to their URLs. See `reports/world-data-report.md`, section 11.3.

## Use as a library

```ts
import { load } from "./src/geoparse.ts";

const gp = await load("");                    // base URL of bundle.json, models/, data/
// Other locations: load("", onProgress, dataUrl, { models: modelUrl, dataVersion })
const { parse, result } = await gp.run("districts near the sea in Gujarat");
```
