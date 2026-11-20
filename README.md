# geoparse

geoparse is an experimental Python library. It converts a natural-language location query into a geometry or into a set of entities. The language is English.

The extract has two scopes:

- `country` (default): India, with the full Overture places table.
- `world`: all countries. It has no places table. It has world point files for hospitals and schools.

The browser version of geoparse is **gazetini**. It uses the world scope. It is live at <https://gazetini.labs.sunu.in>. See `web/README.md`.

Examples:

| Query | Result |
|---|---|
| `Koramangala` | One area (Overture) |
| `2 km around MG Road Bangalore` | One buffer polygon |
| `coastal states in India` | 13 state and union territory polygons |
| `hospitals within 2 km of coastal districts of Odisha` | A set of points (Photon) |

## How it works

1. GLiNER (gliner-small-v2.1, int8 ONNX) and regular expressions find the place names, distances, and numbers in the query.
2. A fine-tuned T5 model (t5-small) gives the best parse frames for the query (beam search): template, slot texts, and quantities. If T5 gives no usable frame, the parser uses the literal split patterns of the templates.
3. Decision functions choose the template family, the template, and the frame (split).
4. Each region slot is a place name or a sub-query. A sub-query starts at step 1 again. The depth limit is 2.
5. The decision functions fill the closed slots (level, predicate, direction, category, attribute, comparison).
6. The parser puts the slot values into the DAG form of the template. The result is a DAG (JSON) of fixed operators (`geoparse/dsl/schema.py`). The executor compiles each DAG node to DuckDB SQL over the local extract.

There are 27 templates in 8 families (`geoparse/templates/*.yaml`). The models do not write the DAG or the SQL. They choose a template and fill its slots.

The decision models hold no geographic facts. All facts are in data: the Overture extract, the natural features, the lexicon, and the layers.

### Models

| Model | Base | Task |
|---|---|---|
| Frame model (`models/t5/current`) | `t5-small`, fine-tuned | Parse frames (step 2) |
| Local decision model (`models/local/current`) | `cross-encoder/ms-marco-MiniLM-L12-v2`, fine-tuned | Decisions (steps 3 and 5, and `is_subquery`). The model gives a score to each option. A softmax over the options gives the probabilities. |
| GLiNER | `gliner-small-v2.1` (int8 ONNX) | Place name spans (step 1). Python only. |

### Decisions

Each decision is a function with a fixed signature. The config file selects a provider for each decision.

| Provider | Use |
|---|---|
| `local` | Local decision model (cross-encoder). Default for `pick_family`, `pick_template`, `pick_split`, `fill_closed_slot`, and `is_subquery`. |
| `rules` | Code and data. Default for `bind_anchor`, `select_source`, and `disambiguate`. Also the baseline for tests and offline use. |
| `jev` | TypeSafe Jev (`typesafe/jev-1.13`) through the OpenRouter Decisions API. The first provider. The local model replaced it (`reports/local-model-report.md`). It needs `OPENROUTER_API_KEY`. |

If a decision has a confidence below its threshold, the parser returns `Unsupported` with the full trace. It does not guess. The parser writes each decision to `logs/decisions-<date>.jsonl` and each `Unsupported` result to `logs/unsupported-<date>.jsonl`.

### Sources

| Source | Use |
|---|---|
| Overture divisions (release `2026-10-21.0`) | Countries, states, districts, cities, localities, neighborhoods |
| Overture places | Points of interest for the `Features` operator. Country scope: slim extract (5.4 million rows). World scope: hospitals and schools only (`poi/`). |
| Natural Earth 10m coastline | The `coastline` layer |
| Natural Earth 10m physical files | Natural features: rivers, lakes, regions, seas, and geographic lines |
| Wikidata | English names of natural features, and populations |
| Photon (`photon.komoot.io`) | Streets, landmarks, addresses, and the other points of interest |

## Setup

1. Install `uv`.
2. Install the dependencies:

   ```sh
   uv sync --extra ner
   ```

3. Copy `.env.example` to `.env`. Set `GEOPARSE_USER_AGENT` to a value that identifies you. Set `OPENROUTER_API_KEY` only if you use the `jev` provider or make LLM paraphrases.
4. Build the local extract. This step reads Overture from S3 and takes approximately 4 minutes:

   ```sh
   uv run python -m geoparse.data.build_extract
   ```

   The output is in `data/build/`. The main file is `geoparse.duckdb` (approximately 770 MB, with the places table). The places step takes approximately 9 minutes.

   For the world extract, set `GEOPARSE_SCOPE=world`. The output is in `data/build-world/` (approximately 7 GB). Use the same environment variable when you run the parser or the gold suite on the world data.

   ```sh
   GEOPARSE_SCOPE=world uv run python -m geoparse.data.build_extract
   ```

5. Get the T5 model and put it in `models/t5/current` (a directory or a link). Without the model, the parser uses the literal patterns only.
6. Get the local decision model and put it in `models/local/current`. Without it, use the `rules` or the `jev` provider.

   To train the two models, see [Model training](#model-training).

## Usage

```python
from geoparse import parse, execute, run

p = parse("coastal districts of Odisha")   # ParseResult: DAG or Unsupported, plus the decision trace
r = execute(p.dag)                          # Result: features with GeoJSON geometry
rr = run("hospitals in Koramangala")        # parse and execute
print(rr.result.geojson())
```

To use one provider for all decisions, give its name: `parse(query, provider="rules")`.

## Test UI

The Streamlit UI shows the parse result, the decision trace, the DAG, the SQL, and the result on a map. It also has a DAG editor to execute a DAG without the parser.

```sh
uv sync --extra ner --extra ui
uv run streamlit run app/streamlit_app.py
```

## Browser version

`web/` is gazetini, a TypeScript version that runs entirely in the browser: T5 and the local decision model in ONNX Runtime Web, and DuckDB-WASM for the world data. The page loads the data of each country only when a query needs it. It does not use GLiNER or the literal patterns. The page is at <https://gazetini.labs.sunu.in> (Cloudflare Worker, with the data and the models on R2). See `web/README.md`.

## Configuration

All policy decisions are in `geoparse/data/config.yaml`. Examples:

- `union_territories_are_states`: union territories count as states.
- `coastal_tolerance_m`: the maximum distance to the coastline for "coastal".
- `admin_levels`: the Overture subtypes for each level name.
- `decisions.providers` and `decisions.thresholds`: the provider and the threshold for each decision.

## Model training

T5 frame model:

```sh
uv run python -m training.gen_synthetic --n 24000          # synthetic pairs
uv run python -m training.paraphrase para --n-seeds 4000    # LLM paraphrases (OpenRouter)
uv run python -m training.paraphrase testset --name llm_dev # dev set for error analysis
# On a GPU machine, in training/remote/:
uv run python train_t5.py --model t5-small --out runs/t5-small --epochs 8
uv run python -m training.eval_t5 --t5 models/t5/current --pipeline jev --set llm_dev
```

Local decision model:

```sh
uv run python -m training.build_decisions                   # decision questions from synthetic data, paraphrases, and Jev logs
# On a GPU machine, in training/remote/:
uv run python train_xenc.py --data data/decisions.jsonl --out runs/xenc-minilm
```

To export both models for the browser (int8 ONNX), run `uv run python scripts/export_onnx.py`.

## Repository layout

```
geoparse/
  decisions/   Decision type, providers, rules, decision functions, logger
  templates/   Templates (YAML, one file for each family) and the pattern matcher
  parse/       Pipeline, recursion, span extraction (GLiNER ONNX)
  dsl/         DAG schema, text form parser, validator
  execute/     DuckDB executor, gazetteer, Photon geocoder
  data/        Extract build script, web data layout, config, options, categories, lexicon, name aliases
  t5/          T5 frame format and inference
app/           Streamlit test UI
gold/          Gold suites (India and world), held-out sets, builder, runner
training/      Synthetic data, LLM paraphrases, LLM dev and test sets, T5 and decision model training and evaluation
reports/       Spike and evaluation reports
scripts/       ONNX and web export, deployment, spikes, latency measurement, informal stress queries
tests/         Unit tests, operator tests on a synthetic world, recorded fixtures
web/           gazetini, the browser version
```

## Tests

```sh
uv run pytest
```

The tests make no network calls. The Jev and Photon tests use recorded responses in `tests/fixtures/`. The pipeline tests need the local extract. If the extract is not there, pytest skips them.

If you change an instruction text or a template description, the recorded Jev responses do not match. Record them again:

```sh
uv run python -m gold.run_gold --provider jev --jev-mode cached
```

## Gold suite

- `gold/gold_src.yaml`: 98 India queries with gold labels for the template, each slot, and each nested level.
- `gold/heldout_src.yaml`: 30 India queries for reports only. Do not tune on them.
- `gold/world_src.yaml`: 70 queries in 10 countries (world scope). For reports only.
- `gold/world_heldout_src.yaml` to `gold/world_heldout5_src.yaml`: world held-out sets. For reports only.
- `gold/build_gold.py`: writes the gold DAG and the expected result IDs to `gold/*.jsonl`.
- `gold/run_gold.py`: scores each decision alone and the full pipeline. `--provider config` uses the providers in the config file. `--setup web` uses the browser setup (T5 frames only, no GLiNER).

```sh
uv run python -m gold.build_gold
uv run python -m gold.run_gold --provider config --execute
uv run python -m gold.run_gold --provider config --setup web --set heldout --execute
GEOPARSE_SCOPE=world uv run python -m gold.build_gold --set world
GEOPARSE_SCOPE=world uv run python -m gold.run_gold --provider config --setup web --set world --execute
```
