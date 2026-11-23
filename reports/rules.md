# Rule ledger

Each plan that adds, changes or removes a rule in the parser updates this table.

Principle (plan-039): **the models propose, the code verifies, the data holds the facts.**

- A **verifier** rejects a frame that cannot be correct. It does not depend on English. It chooses among the beams of
  the model, so it gets better when the model gets better.
- A **producer** makes or changes a reading of the query in code. Each producer exists two times (Python and
  TypeScript) and usually comes from a small number of queries. Move producers into the frame model, or remove them.
- A **policy** is a choice of the product, not a reading of the text (for example, the default of a quantifier).

Code locations: `t5/frames` is `geoparse/t5/frames.py` and `web/src/core/frames.ts`. `parse/pipeline` is
`geoparse/parse/pipeline.py` and `web/src/parse/pipeline.ts`.

## Ledger (2026-11-23, start of plan-039)

| Rule | Kind | Where | Plan of origin | Action in plan-039 |
|---|---|---|---|---|
| Slot text is a span of the query (`check_frame`) | Verifier | `t5/frames` | 005 | Keep |
| Same text in two region slots | Verifier | `t5/frames` | 038 | Keep |
| Frame coverage: drop the frames that leave out more place names (`_covering`) | Verifier | `parse/pipeline` | 038 | Keep; count a name in a closed slot as left out |
| A union frame needs a list separator | Verifier | `parse/pipeline` | 038 | Remove (the frame lists its parts) |
| List split: separators, fewest parts, comma rule, sub-query parts, fuzzy fallback (`_list_parts`) | Producer | `parse/pipeline` | 036, 038 | Replace: T5 writes the parts |
| `LIST_SEP`, `LIST_MARKER` word lists | Producer | `parse/pipeline` | 036, 038 | Remove (the quantifier words stay, as option keywords) |
| "X in Y" with X not inside Y: use Y, with a note | Producer | `parse/pipeline` | 038 | Replace: T5 writes `within` |
| Qualified name by commas and "in" (`_qualified`) | Producer and verifier | `parse/pipeline` | 025 | Keep the containment check; T5 writes the parts |
| Slot extension to a longer exact name (`_extend_slots`) | Producer | `parse/pipeline` | 038 | Replace by a verifier: prefer the beam with the longer exact name |
| Removal of "all of", "the", "whole of" | Producer | `parse/pipeline` | 036 | Keep only the article removal before the gazetteer search |
| Plain "and" means "any", with a note | Policy | `parse/pipeline` | 036 | Keep |
| Direction word with a typo | Producer | not written | 038 | Do not write: training data with typos |
| `frame_words()` (template and option words) | Data for a verifier | `parse/pipeline` | 038 | Keep (derived from the templates) |
| `is_subquery` (cross-encoder) for region slots | Model | `geoparse/decisions/` | 001 | Replace: the T5 frame of the slot text decides |
| A place name that the local data cannot place goes to the geocoder (Photon), with a note: a lookup frame that `is_subquery` calls a set, a low-confidence `select_source`, a name with no local candidate. Not for a text with a plural admin level word ("which states touch the sea"). | Policy | `parse/pipeline` | 039 | Added (user, 2026-11-23) |

Count at the start of plan-039: 4 verifiers (one also a producer), 6 producers, 1 policy, 1 model decision, and
1 data item. Plan-039 added 1 policy (the geocoder fallback).

## Measurement at the start of plan-039

Models: T5 v6, cross-encoder v5. Setup: web (T5 frames only). Executed result: the result of the parsed DAG is the
same as the result of the gold DAG. Records that need Photon are not executed.

| Set | Records | Template | DAG | Executed result |
|---|---|---|---|---|
| `india_ref` (200 labelled reference queries) | 200 | 191 | 188 | 149/157 |
| `world_heldout8` (demonyms) | 19 | 19 | 8 | 8/19 |

`india_ref` has 18 queries that the parser must refuse (`t: unsupported`), and 6 records with a data gap (`gap`: a
city that is a point, or a missing ancestor). A data gap has labels, but it is not executed.
