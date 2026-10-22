# Report: phases 1 to 4

Date: 2026-10-22. Model: `typesafe/jev-1.13` (snapshot `jev-1.13-20260917`).

Detailed tables: `reports/gold-jev.md`, `reports/gold-rules.md`, `reports/gold-heldout-*.md`, `reports/gold-jev-noprune.md`.

## 1. Summary

| Measure | Rules | Jev |
|---|---|---|
| Gold suite, correct DAG (98 queries) | 98 % (96) | 99 % (97) |
| Gold suite, depth 1 (13 queries) | 100 % | 100 % |
| Held-out set, correct DAG (30 queries) | 100 % | 100 % |
| Executed result equal to expected (80 queries without network) | 100 % | 99 % |
| Median live latency, depth 0 | 0.1 s | 1.6 s |
| Median live latency, depth 1 | 0.1 s | 3.1 s |
| Mean cost for each query, depth 0 / depth 1 | 0 | $0.00006 / $0.00012 |

Read these numbers with care:

1. I wrote the gold suite, the templates, the rules, and the descriptions. I tuned the code on the gold suite. The rules baseline is therefore optimistic.
2. I wrote the held-out set before the second tuning round. It has the same style as the gold suite. Thus it shows generalization inside the template coverage only.
3. The real limit is pattern coverage. See section 4.

## 2. What is built

- **Decision layer.** `Decision` type, `DecisionProvider` protocol, `JevProvider` (OpenRouter Decisions API, with record and replay), `RulesProvider`, `LocalClassifierProvider` stub. The config selects a provider and a threshold for each decision. Each decision goes to the JSONL log.
- **Decision functions.** `extract_spans`, `pick_family`, `pick_template`, `pick_template_flat`, `pick_split`, `fill_closed_slot` (two steps for categories), `bind_anchor`, `is_subquery`, `select_source`, `disambiguate`.
- **Templates.** 8 families, 21 templates, YAML. Each template has split patterns, a description, examples, typed slots, and a DAG in text form.
- **DSL.** Operator catalog (15 operators and 5 predicates), text form parser, slot substitution, and validator.
- **Executor.** Each DAG node is one DuckDB SQL statement on the local extract. `Features` uses Photon.
- **Data.** India extract (Overture `2026-10-21.0`), Natural Earth coastline, land border layer, lexicon (7 sets), policy config.
- **Gold suite.** 98 records (gold) and 30 records (held-out). Runner with scores for each decision, family, and depth.
- **Tests.** 81 tests. No network.

## 3. Results for each decision

### 3.1 Decisions alone, with gold inputs (Jev, gold suite)

| Decision | Accuracy | Needs the model (more than one option) |
|---|---|---|
| `pick_family` | 99 % (110/111) | 101 of 111, mean 2.3 options |
| `pick_template` | 100 % (111/111) | 14 of 111 |
| `pick_template_flat` | 100 % (111/111) | 101 of 111, mean 2.5 options |
| `pick_split` | 100 % (111/111) | 3 of 111 |
| `is_subquery` | 100 % (114/114) | all |
| `select_source` | 100 % (24/24) | all |
| `fill_closed_slot` (all types) | 100 % (104/104) | most |

### 3.2 Two-step against one-step template choice

With pattern pruning, both methods have the same accuracy. The two-step method needs a second model call in 14 of 111 cases only.

Without pattern pruning (the model sees all 8 families and all 21 templates):

| Method | Accuracy |
|---|---|
| Two steps (family, then template) | 97 % (108/111) |
| One step (21 templates) | 97 % (108/111) |

The errors are the same type in both methods: nested queries ("districts of states that border Goa"), and "border districts" against "districts that border X". Recommendation: keep two steps. The extra call is rare, and the short option lists are easier to read in the logs.

### 3.3 `pick_split`

The plan said that `pick_split` is the weakest step. In this build it is not, for one reason: hard checks in code remove most wrong splits before the model sees them. The checks are:

- A distance segment must parse as a distance.
- A number segment must parse as a number.
- All words of a closed-slot segment must be keywords of its options.
- A place segment cannot contain only level, predicate, and stop words.

After the checks, 108 of 111 splits have one candidate only. Thus composite templates for nested pairs are not necessary now. The nested pairs in the gold suite are in `reports/gold-jev.md`. No pair occurs more than twice.

### 3.4 Latency

Measured live, one query at a time (`scripts/measure_latency.py`):

| Depth | Median | P90 | Max | Mean model calls |
|---|---|---|---|---|
| 0 | 1.60 s | 2.10 s | 2.47 s | 3.5 |
| 1 | 3.14 s | 3.42 s | 3.97 s | 7.0 |

One Jev request takes approximately 0.45 s. The parser runs the independent decisions of one level in parallel threads. Thus the latency depends on the number of steps in sequence, not on the number of calls.

Execution on the local extract: median 0.09 s, max 0.74 s. `Features` queries are slower because of the Photon rate limit (1 request each second).

## 4. Findings

1. **Silent wrong answers from the lookup template (fixed).** If no other template matched, the parser used `lookup` without a model decision. Then it sent the full query to Photon. Example: "what districts does Karnataka have" returned a random point. Fix: before `lookup`, the parser asks `is_subquery` on the full text. If the text describes a set, the result is `Unsupported`.
2. **`disambiguate` with candidates that contain each other (fixed).** "Whitefield" is a locality and a macrohood. "Pune" is a city and a district. Jev gave low confidence (0.04 to 0.18), which is correct. These choices are policy, not language. Now the code merges candidates with the same name when one contains the other. The subtype order in the gazetteer selects one.
3. **Pattern coverage is the ceiling.** A query outside the patterns returns `Unsupported`. Examples from `scripts/stress_informal.py`: "which states touch the sea", "top cities in tamil nadu", "chennai to bangalore". The `logs/unsupported-*.jsonl` file collects these queries for new templates.
4. **Photon is weak for `Features`.** Photon matches the search text against names, also with a tag filter. "cafes in Indiranagar" found 2 cafes, both with "cafe" in the name. A large region needs many tiles: "hospitals in coastal districts of Goa" sent 16 requests and took 19 s.
5. **Population data is incomplete.** Overture has no population for most districts. The `AttrFilter` operator excludes entities without a value and adds a note. Three gold queries for districts return no result.
6. **Coastline data.** The Natural Earth coastline makes Cuttack (Odisha) coastal. The result is the same for tolerances from 500 m to 3 km. Thus the cause is the line, not the tolerance.
7. **Ambiguous names without context.** "MG Road" without a city goes to the first Photon result. "Jayanagar" exists in Bengaluru and in Assam. The gazetteer selects one by a fixed order.

## 5. Recommendations

1. **Places data for `Features`.** Use Overture `places` or an OSM extract for points of interest on the complex path. Keep Photon for streets, addresses, and landmarks. This is the largest quality gap.
2. **Speculative fan-out.** Jev answers many questions in one request with the same latency. Send `pick_family`, each `pick_template`, and the `is_subquery` questions in one request. This can reduce depth-0 latency from approximately 1.6 s to approximately 0.6 s.
3. **Where to train local classifiers.** `is_subquery`, `select_source`, and `fill_closed_slot` are frequent and have few options. They are good first candidates. `pick_family` is the most important decision and has the most errors without pruning. Train it after more logs exist.
4. **Gold suite.** Add queries from people who did not write the templates. The current gold suite cannot show coverage gaps.
5. **Cartographic prominence.** Overture `cartography.prominence` can rank places with the same name (Jayanagar in Bengaluru before Jayanagar in Assam).

## 6. Questions for you

1. Do you approve the use of Photon by the `Features` operator, and of the geocoder for anchors of the `features` family? `plan-002.md` section 2.2 records this change from plan-001.
2. Do you want an Overture `places` extract (or an OSM extract) for `Features`, with Photon for the simple path only?
3. Which decisions do you want to train first from the logs?
