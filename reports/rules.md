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
| Frame coverage: drop the frames that leave out more place names (`_covering`) | Verifier | `parse/pipeline` | 038 | Keep. Done in 039: a name in a closed slot counts as left out |
| A frame whose open slot is the whole text is not valid (not for lookup and list templates) (`_faults`) | Verifier | `parse/pipeline` | 039 | Added |
| A closed slot text (not an admin level) must contain a keyword of its options (`_faults`) | Verifier | `parse/pipeline` | 039 | Added. The decision model gives confidence 1.0 to wrong maps ("palace" to stadium), so a threshold does not work |
| The divisions of a geocoder point: an error message, not an empty set (`op_Children`) | Verifier | `execute/executor` | 039 | Added |
| A union frame needs a list separator | Verifier | `parse/pipeline` | 038 | Removed in 039 phase 4. Now: a union frame needs two or more " \| " parts (the frame structure) |
| List split: separators, fewest parts, comma rule, sub-query parts, fuzzy fallback (`_list_parts`) | Producer | `parse/pipeline` | 036, 038 | Removed in 039 phase 4: T5 writes the parts. The pattern path (no T5) has no lists |
| `LIST_SEP`, `LIST_MARKER` word lists | Producer | `parse/pipeline` | 036, 038 | Removed in 039 phase 4 (the quantifier words stay, as option keywords) |
| "X in Y" with X not inside Y: use Y, with a note | Producer | `parse/pipeline` | 038 | Removed in 039 phase 4: T5 writes `within` or `border_with_in` |
| Qualified name by commas and "in" (`_qualified`) | Producer and verifier | `parse/pipeline` | 025 | Keep the containment check; T5 writes the parts |
| Slot extension to a longer exact name (`_extend_slots`) | Producer | `parse/pipeline` | 038 | Removed in 039 phase 4. No verifier was necessary: no set changed |
| Removal of "all of", "the", "whole of" | Producer | `parse/pipeline` | 036 | Keep only the article removal before the gazetteer search |
| Plain "and" means "any", with a note | Policy | `parse/pipeline` | 036 | Keep |
| Direction word with a typo | Producer | not written | 038 | Do not write: training data with typos |
| `frame_words()` (template and option words) | Data for a verifier | `parse/pipeline` | 038 | Keep (derived from the templates) |
| `is_subquery` (cross-encoder) for region slots | Model | `geoparse/decisions/` | 001 | Replaced in 039 phase 4: the top T5 frame of the slot text (a lookup is a name, any other frame is a sub-query). The parser without T5 still uses the model. The lookup guard of a whole query still uses it |
| Each list part (" \| ") and each `<slot>.within` text is a span of the query; no part is in two slots (`check_frame`) | Verifier | `t5/frames` | 039 | Added (phase 2: the frame format). Phase 4: a text can be in as many parts as the query has it ("Kerala and Kerala") |
| A name with `<slot>.within` needs a candidate inside an exact match of the qualifier (`_within_faults`, `_inside`) | Verifier | `parse/pipeline` | 039 | Added (phase 2). The containment check of `_qualified`, for the frame |
| The conjunction of a frame list: "or" between two parts in the query | Policy | `parse/pipeline` | 039 | Added (phase 2). The parts are spans, so the words between them are known. There is no `conj` slot for T5 to learn |
| A place name that the local data cannot place goes to the geocoder (Photon), with a note: a lookup frame that `is_subquery` calls a set, a low-confidence `select_source`, a name with no local candidate. Not for a text with a plural admin level word ("which states touch the sea"). | Policy | `parse/pipeline` | 039 | Added (user, 2026-11-23) |
| Frames of one group: the frame that covers more of the query wins, within a score margin of 0.5 (`group_frames`) | Verifier | `t5/frames` | 039 | Added (phase 3). "states bordering X" with no level in the top beam lost the level word |
| A closed slot choice with no keyword in the text loses to the one option with a keyword, typos allowed (`fill_closed_slot`, impl `keyword_check`) | Verifier | `decisions/functions`, `decisions/decider` | 039 | Added (phase 3). "nortern Karnataka" gave south |
| Demonym of a country or region as the name of the place, only for the whole name text (`demonyms.yaml`, Wikidata P1549) | Data | `execute/data`, `execute/gazetteer` | 039 | Added (phase 3) |
| Region slot text with a direction word and an exact name is a sub-query, without a model (`direction_rest`) | Producer | `parse/pipeline` | 025 | Removed in 039 phase 4: T5 decides. `_direction_rest` stays in `_frame_override` |
| Region slot text with a level word or a distance is a sub-query, without a model | Producer | `parse/pipeline` | 025 | Removed in 039 phase 4: T5 decides |
| Region slot text that is an exact place name is a place, without T5 (the gazetteer shortcut) | Data for a verifier | `parse/pipeline` | 025 | Kept. Phase 4: also with a level word ("Pune district", "Pune city"); the store reads a singular level word as a type |

Count at the start of plan-039: 4 verifiers (one also a producer), 6 producers, 1 policy, 1 model decision, and
1 data item. Plan-039 added 2 policies (the geocoder fallback, the conjunction of a frame list), 7 verifiers and 1 data item. Phase 4
removed 7 producer rules (the list split, the list word lists, "X in Y", the slot extension, the direction and the
level-or-distance sub-query shortcuts, the union separator check) and the `is_subquery` model call for region slots.

## Measurement at the start of plan-039

Models: T5 v6, cross-encoder v5. Setup: web (T5 frames only). Executed result: the result of the parsed DAG is the
same as the result of the gold DAG. Records that need Photon are not executed.

| Set | Records | Template | DAG | Executed result |
|---|---|---|---|---|
| `india_ref` (200 labelled reference queries) | 200 | 191 | 188 | 149/157 |
| `world_heldout8` (demonyms) | 19 | 19 | 8 | 8/19 |

`india_ref` has 18 queries that the parser must refuse (`t: unsupported`), and 6 records with a data gap (`gap`: a
city that is a point, or a missing ancestor). A data gap has labels, but it is not executed.

## Measurement after plan-039 phase 1 (verifiers)

| Set | Executed result before | After |
|---|---|---|
| `india_ref` | 149/157 | 151/157 |
| `world_heldout8` | 8/19 | 8/19 (the 'Indian' records give an error message, not an empty result) |
| All other gold and held-out sets | | No change |

The India reference set: 6 of 696 parses changed, all as intended (two attributes with no data are refused, "Mysuru
palace" is a lookup, "states in India that touch Pakistan" uses the border with Pakistan).

## Measurement after plan-039 phase 3 (training)

Models: T5 v7, cross-encoder v6. The training data has list parts (" | "), `within`, demonyms, numbered neighbourhood
names, more one-place `neighbors` forms, palace and fort lookups, and typos in the direction words.

| Set | Before (phase 1) | After |
|---|---|---|
| `india_ref` | 151/157 | 152/157 |
| `world_heldout8` (demonyms) | 8/19 | 18/19 |
| `world_heldout7` | 60/73 | 64/73 |
| All other gold and held-out sets | | No change |
| Parse parity fp32 / int8 | 696 / 686 | 696 / 689 (of 696) |

The India reference set: 16 of 696 parses changed (the plan-038 retrain: 16 changed, 9 worse).

- Better (8): "nortern Karnataka", "nothern Gujarat", "areas souht of Hyderabad", "Jayanagar 4th Block" (a local
  name, not the geocoder), "districts around Gurugram that share a border with it", "central location of Nashik
  district in Maharashtra", "disrtict of Bodh Gaya" (the parent district), "coastline buffer gujrat 15 km".
- Worse (4): "bewteen Lucknow and Kanpur" and "btwn hyderabad and secunderabad" (the typo of "between" gives a
  union), "upper northern portion of West Bengal" (north of north), "banks on Park Street Kolkata" (inside the
  geocoder point, not near it).
- Same result, other text (4): three refusal messages, and "Konark Sun Temple state" (the geocoder text).

## Measurement after plan-039 phase 4 (producer rules removed)

Models: T5 v7, cross-encoder v6 (no retraining). Each rule was removed alone, with all checks after it.

| Step | Sets (executed result) | India reference parses changed |
|---|---|---|
| Union separator check | No change (after the fix of the duplicate check for "Kerala and Kerala") | 0 |
| "X in Y" fallback | No change | 0 |
| `_extend_slots` | No change | 2 (other refusal message, still refused) |
| `_list_parts`, `LIST_SEP`, `LIST_MARKER` | No change | 0 |
| `is_subquery` for region slots | No change (with the exact-name shortcut for level words) | 6 |
| Direction shortcut | No change | 0 |
| Level-or-distance shortcut | No change | 0 |

All sets at the end of phase 4: `india_ref` 152/157, held-out 8 18/19, held-out 7 64/73, gold 89/89, heldout 27/27, world
70/70, held-out 2 to 6 the same as phase 3. Parse parity fp32 696/696, int8 690/696. Median parse time: fp32 1.22 s,
int8 1.08 s (phase 3: 1.22 s and 1.05 s).

The 6 changes of `is_subquery`: "Coimbatore airport", "Jaipur airport", "Calangute beach" and "Kovalam beach" are now the
airports or beaches of the place from the local data, not a geocoder point. "marina beach" is worse: the beaches of
"Maria" (a fuzzy match, in Madhya Pradesh). "btwn hyderabad" is wrong before and after.

A verifier that rejects "the divisions of a level inside a place of that level" ("children ; level = district ; parent =
Pune") was tried and removed: the level words of a country ("provinces" in Italy are districts) are not known at the
frame stage, so it rejected "provinces of Sicily".

Code: `geoparse/parse/pipeline.py` 1192 to 1073 lines, `web/src/parse/pipeline.ts` 855 to 747 lines.
