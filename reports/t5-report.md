# Report: T5 candidate generator (plan-005)

Date: 2026-10-22.

## 1. Summary

A fine-tuned t5-small model now generates the candidate parse frames. Jev chooses among them and fills the closed slots. The hand-written split patterns are a fallback only.

| Measure | Patterns only (before) | T5 v3 + Jev (now) |
|---|---|---|
| LLM test set, 294 unseen queries, full pipeline | not measured (most fail) | 87.8 % |
| LLM dev set, 279 queries, full pipeline | 84.2 % (first T5 run) | 92.5 % |
| Paraphrase set, 20 queries (no labels) | 11 of 20 parse | all 20 parse; checked by hand |
| Gold suite, 98 queries, correct DAG | 99 % | 99 % |
| Held-out set, 30 queries, correct DAG | 100 % | 100 % |
| Median parse latency, LLM test (live Jev, first run) | | 1.16 s |

## 2. Model selection

| Model | Size (fp32) | LLM dev top 1 | LLM test top 1 | LLM test top 4 | Median latency (Mac CPU) |
|---|---|---|---|---|---|
| t5-small v1 (synthetic + paraphrases) | 243 MB | 91.0 % | 91.2 % | 97.3 % | 112 ms |
| t5-small v2 (generator v2) | 243 MB | 94.3 % | 94.6 % | 98.0 % | 113 ms |
| t5-small v3 (v2 + anchors with city context) | 243 MB | 94.3 % | 92.2 % | 98.3 % | 111 ms |
| flan-t5-base v2 | 963 MB | 93.5 % | 94.2 % | 98.6 % | 312 ms |

Decision: **t5-small v3** (`models/t5/current`). flan-t5-base is not more accurate, and it is 3 times slower and 4 times larger. v2 and v3 are equal on the dev set; v3 fixes "MG Road, Bangalore" (a street with its city, which v2 read as two places). The test-set difference between v2 and v3 (2.4 points, 7 queries) is in the range of run-to-run variation (standard error approximately 1.4 points on 294 queries). I did not select by test score.

"Top 1" compares the core of the frame: template, open-slot texts, and quantities.

## 3. Training data

| Source | Rows | Cost |
|---|---|---|
| Synthetic (`training/gen_synthetic.py`, v2) | 24,000 | 0 |
| Paraphrases (`anthropic/claude-haiku-5.5`) | 10,007 | $0.45 |
| LLM dev set (`anthropic/claude-sonnet-5.5`) | 279 | under $1 |
| LLM test set (`anthropic/claude-sonnet-5.5`) | 294 | under $1 |

Training: RTX 3090. t5-small, 8 epochs: 211 s. flan-t5-base, 6 epochs: 589 s.

Test leakage: I looked at the errors of the first (pilot) model on the LLM test set before I made generator v2. The v2 changes are generic (typos in all words, plain numbers, informal words, more level words). After that, I used only the dev set for error analysis. v2 improved dev and test by the same amount (3.3 and 3.4 points), which shows the changes are not specific to the test set.

## 4. Errors on the LLM test set (33 of 294)

| Category | Count | Correct behavior? |
|---|---|---|
| Level, attribute, or property not in the data (wards, blocks, subdivisions, literacy rate, sex ratio, hilly) | 13 | Yes. The parser refuses. |
| Low confidence (disambiguate, pick_split, is_subquery) | 8 | Refusal; an answer was possible |
| Name not in the extract (Koregaon Park, Salcete, Delhi NCR) | 6 | Refusal; data gap |
| Wrong template (silent wrong answer) | 5 | No |
| Wrong slot value (silent wrong answer) | 1 | No |

Silent wrong answers: 6 of 294 (2 %). Examples: "boundry strip of Ladakh" gave the international border strip, not the state border strip. "Which Indian states are landlocked" gave parent "Indian".

Also, about 5 test labels are debatable (the LLM wrote them).

## 5. Changes in the pipeline

- T5 frames are the candidates. Frames that differ only in closed-slot text or quantities are one group. The best frame of a group gives the quantities. Jev never chooses a number.
- If the best frame is `unsupported` with probability 0.5 or more, the parser returns `Unsupported` at once (0.1 s).
- Patterns: used only if T5 gives no usable frame (`t5.use_patterns: fallback`).
- Closed slots always have a "none" option. Jev judges the meaning; there is no vocabulary check.
- Name aliases (`geoparse/data/name_aliases.yaml`): short forms and old names. This is a temporary list. See `plans/improvement-ideas.md` (Wikidata).
- New level `village`.
- `is_subquery` description now includes lists ("Kolkata and Howrah").
- **Geocoder for all anchors** (`geocoder.anchor_scope: all`). Landmarks in complex queries ("between Charminar and Hitec City") go to Photon. This needs your approval.
- Provider network errors: retry, then `Unsupported` with the reason (no crash).

## 6. Open items

1. Approve or reject `geocoder.anchor_scope: all`.
2. The ONNX export for the browser is not done.
3. The rules baseline is weaker now (gold 95 %), because the vocabulary checks were removed. One gold test is marked as an expected failure.

## 7. POI extract (plan-004 section 2)

- `data/build/places.parquet`: 5,430,152 rows, 271 MB (estimate was 283 MB). Build time: 9 minutes (S3 read).
- `geoparse.duckdb` with the places table: 704 MB.
- `Features` now runs in DuckDB on the places table: approximately 15 ms for a neighbourhood. Photon took up to 19 s for a large region (rate limit).
- Category tree: 9 groups, 48 items, matched against the Overture `basic_category` and every level of the taxonomy hierarchy.
- Policy: `places_min_confidence` (0.5), `max_features` (10,000), `point_area_radius_m` (a radius for places that have only a point, for example the Koramangala macrohood).
- Gold feature queries now have expected IDs (local data). Example: "hospitals in Koramangala": 76 places (Photon found 27 in a larger box).

## 8. Next steps for the data in T5 training

- Lists inside a slot ("noida and ghaziabad") sometimes give an extra slot `c`, so the frame is not valid. Add list examples for `difference` and `union` slots.
- Run-to-run variation is large. Train 3 seeds and report the mean, or use an ensemble of the beams.
