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

1. The parser finds the templates whose split patterns match the query.
2. Decision functions choose the template family, the template, and the split.
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

   The output is in `data/build/`. The main file is `geoparse.duckdb` (approximately 380 MB).

## Usage

```python
from geoparse import parse, execute, run

p = parse("coastal districts of Odisha")   # ParseResult: DAG or Unsupported, plus the decision trace
r = execute(p.dag)                          # Result: features with GeoJSON geometry
rr = run("hospitals in Koramangala")        # parse and execute
print(rr.result.geojson())
```

To use one provider for all decisions, give its name: `parse(query, provider="rules")`.

## Configuration

All policy decisions are in `geoparse/data/config.yaml`. Examples:

- `union_territories_are_states`: union territories count as states.
- `coastal_tolerance_m`: the maximum distance to the coastline for "coastal".
- `admin_levels`: the Overture subtypes for each level name.
- `decisions.providers` and `decisions.thresholds`: the provider and the threshold for each decision.

## Repository layout

```
geoparse/
  decisions/   Decision type, providers, rules, decision functions, logger
  templates/   Templates (YAML, one file for each family) and the pattern matcher
  parse/       Pipeline, recursion, span extraction (GLiNER ONNX)
  dsl/         DAG schema, text form parser, validator
  execute/     DuckDB executor, gazetteer, Photon geocoder
  data/        Extract build script, config, options, categories, lexicon
gold/          Gold suite, held-out set, builder, runner
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
