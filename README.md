# geoparse

geoparse is an experimental Python library. It converts a natural-language location query into a geometry or into a set of entities. The scope is India and English.

Examples:

| Query | Result |
|---|---|
| `Koramangala` | One area (Overture) |
| `2 km around MG Road Bangalore` | One buffer polygon |
| `coastal states in India` | 13 state and union territory polygons |
| `hospitals within 2 km of coastal districts of Odisha` | A set of points (Photon) |

## How it works

1. A fine-tuned T5 model (t5-small) gives the best parse frames for the query: template, slot texts, and quantities. If T5 gives no usable frame, the parser uses the literal split patterns of the templates.
2. Decision functions choose the template family, the template, and the frame (split).
3. Each region slot is a place name or a sub-query. A sub-query starts at step 1 again. The depth limit is 2.
4. The decision functions fill the closed slots (level, predicate, direction, category, attribute, comparison).
5. The parser builds a DAG (JSON). The executor compiles each DAG node to DuckDB SQL over the local extract.

The decision models hold no geographic facts. All facts are in data: the Overture extract, the lexicon, and the layers.

### Decisions

Each decision is a function with a fixed signature. The config file selects a provider for each decision.

| Provider | Use |
|---|---|
| `jev` | TypeSafe Jev (`typesafe/jev-1.13`) through the OpenRouter Decisions API |
| `rules` | Rule baseline for tests and offline use |
| `local` | Stub for a later local classifier |

If a decision has a confidence below its threshold, the parser returns `Unsupported` with the full trace. It does not guess. The parser writes each decision to `logs/decisions-<date>.jsonl` and each `Unsupported` result to `logs/unsupported-<date>.jsonl`.

### Sources

| Source | Use |
|---|---|
| Overture divisions (release `2026-10-21.0`) | Countries, states, districts, cities, localities, neighborhoods |
| Overture places (slim extract, 5.4 million rows) | Points of interest for the `Features` operator |
| Natural Earth 10m coastline | The `coastline` layer |
| Photon (`photon.komoot.io`) | Streets, landmarks, addresses, and points of interest |

## Setup

1. Install `uv`.
2. Install the dependencies:

   ```sh
   uv sync --extra ner
   ```

3. Copy `.env.example` to `.env`. Set `OPENROUTER_API_KEY`. Set `GEOPARSE_USER_AGENT` to a value that identifies you.
4. Build the local extract. This step reads Overture from S3 and takes approximately 4 minutes:

   ```sh
   uv run python -m geoparse.data.build_extract
   ```

   The output is in `data/build/`. The main file is `geoparse.duckdb` (approximately 700 MB, with the places table). The places step takes approximately 9 minutes.
5. Get the T5 model and put it in `models/t5/current` (a directory or a link). To train one, see `training/`. Without the model, the parser uses the literal patterns only.

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

## Configuration

All policy decisions are in `geoparse/data/config.yaml`. Examples:

- `union_territories_are_states`: union territories count as states.
- `coastal_tolerance_m`: the maximum distance to the coastline for "coastal".
- `admin_levels`: the Overture subtypes for each level name.
- `decisions.providers` and `decisions.thresholds`: the provider and the threshold for each decision.

## T5 training

```sh
uv run python -m training.gen_synthetic --n 24000          # synthetic pairs
uv run python -m training.paraphrase para --n-seeds 4000    # LLM paraphrases (OpenRouter)
uv run python -m training.paraphrase testset --name llm_dev # dev set for error analysis
# On a GPU machine, in training/remote/:
uv run python train_t5.py --model t5-small --out runs/t5-small --epochs 8
uv run python -m training.eval_t5 --t5 models/t5/current --pipeline jev --set llm_dev
```

## Repository layout

```
geoparse/
  decisions/   Decision type, providers, rules, decision functions, logger
  templates/   Templates (YAML, one file for each family) and the pattern matcher
  parse/       Pipeline, recursion, span extraction (GLiNER ONNX)
  dsl/         DAG schema, text form parser, validator
  execute/     DuckDB executor, gazetteer, Photon geocoder
  data/        Extract build script, config, options, categories, lexicon, name aliases
  t5/          T5 frame format and inference
gold/          Gold suite, held-out set, builder, runner
training/      Synthetic data, LLM paraphrases, LLM dev and test sets, T5 training and evaluation
reports/       Spike and evaluation reports
scripts/       Spikes, latency measurement, informal stress queries
tests/         Unit tests, operator tests on a synthetic world, recorded fixtures
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

- `gold/gold_src.yaml`: 98 queries with gold labels for the template, each slot, and each nested level.
- `gold/heldout_src.yaml`: 30 queries for reports only. Do not tune on them.
- `gold/build_gold.py`: writes the gold DAG and the expected result IDs to `gold/*.jsonl`.
- `gold/run_gold.py`: scores each decision alone and the full pipeline.

```sh
uv run python -m gold.build_gold
uv run python -m gold.run_gold --provider jev --execute
uv run python -m gold.run_gold --set heldout --provider rules
```
