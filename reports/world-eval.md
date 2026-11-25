# Accuracy outside India (plan-008, phase 7)

Date: 2026-11-17. Overture release `2026-10-21.0`.

## 1. Summary

The parse is correct for 61 of 70 world queries (87%). For the India sets, the parse is correct for 127 of 128 queries (99%). Of the 9 world errors:

- 6 are words for admin levels: "counties", "prefectures", "local government areas" and "municipalities".
- 2 are a wrong gazetteer match ("Minas Gerais").
- 1 is a Kyoto query where the gazetteer has no candidate for Kyoto Prefecture.

The templates, the splits, the categories and the predicates are correct for all world queries. Recommendation: do not retrain T5. Fix the admin level words and the gazetteer problems first (section 5). Then measure again.

## 2. Gold set

`gold/world_src.yaml` has 70 queries: 7 for each of 10 countries (US, GB, FR, DE, BR, JP, AU, NG, MX, ZA). It has place names, admin levels in local words, neighbors, predicates, hospitals and schools, set operations, buffers and directions. All queries have one level (depth 0).

Each record has the map view of its country. The build and the runs give this view to the gazetteer and to the executor. The gold anchor is the top gazetteer candidate with this view. One record has a fixed Overture id (`ids`), because the top candidate is not the correct place ("prefectures bordering Kyoto": Kyoto Prefecture, not Kyoto city). The expected results come from the gold DAG on the world data. They agree with the real geography (for example: 16 German states, 6 countries that border South Africa, 15 landlocked Mexican states).

Build: `GEOPARSE_SCOPE=world uv run python gold/build_gold.py --set world`.

## 3. Setup

The runs use the settings of the browser version (`--setup web`): T5 frames, no split patterns, no NER spans, the providers of the configuration (local cross-encoder and rules), no geocoder. The JS parse gives the same DAG as this Python parse (696 of 696 queries, fp32 models; 685 of 696 with the int8 models of the page).

```sh
GEOPARSE_SCOPE=world uv run python -m gold.run_gold --provider config --setup web --set world --execute
uv run python -m gold.run_gold --provider config --setup web --set gold --execute
uv run python -m gold.run_gold --provider config --setup web --set heldout --execute
```

Reports: `reports/gold-world-config-web.md`, `reports/gold-config-web.md`, `reports/gold-heldout-config-web.md`.

## 4. Results

### 4.1 Full pipeline

| Set | Queries | Template | DAG | Executed result | Median parse time |
|---|---|---|---|---|---|
| India gold | 98 | 99% | 99% (97) | 99% (88 of 89) | 0.61 s (depth 0) |
| India held-out | 30 | 100% | 100% (30) | 100% (27 of 27) | 0.47 s (depth 0) |
| World | 70 | 96% | 87% (61) | 87% (61 of 70) | 2.91 s |

The world parse time is longer, because the world database (6.9 GB) makes the gazetteer lookups slower in Python. The browser loads only the name shards and the countries that a query needs (see `world-data-report.md`).

Note: the parity check script (`gold_cmp.py`, used in phases 2 to 6) gave 115 of 128 for the India sets. That script compares JSON text, so a value of `1000000` is different from `1000000.0`. The gold runner compares canonical DAGs and gives 127 of 128. The regression checks of phases 2 to 6 compare the same script before and after each change, so their results stay valid.

### 4.2 Decisions alone (gold inputs)

| Decision | India gold | India held-out | World |
|---|---|---|---|
| pick_family | 99% | 97% | 97% (68/70) |
| pick_template | 100% | 100% | 100% (70/70) |
| pick_split | 100% | 100% | 100% (70/70) |
| is_subquery | 100% | 100% | 100% (59/59) |
| select_source | 100% | 100% | 96% (22/23) |
| fill_closed_slot.admin_level | 100% | 100% | 88% (28/32) |
| fill_closed_slot.category | 100% | 100% | 100% (10/10) |
| fill_closed_slot.predicate | 100% | 100% | 100% (8/8) |

### 4.3 World errors

| Id | Query | Problem | Cause |
|---|---|---|---|
| w002 | counties of Nevada | level `country`, not `district` | "counties" is a keyword of `district`, but the local model gives `country` (confidence 0.999) |
| w004 | coastal counties of Georgia | level `country` | same |
| w009 | counties of Wales | level `country` | same |
| w038 | prefectures bordering Kyoto | level `none`, and Kyoto city | "prefectures" is not a level word. The gazetteer has no candidate for Kyoto Prefecture ("Kyoto" finds the city and a county) |
| w040 | landlocked prefectures of Japan | unsupported | "prefectures" is not a level word |
| w052 | local government areas of Lagos | unsupported | "local government areas" is not a level word |
| w059 | municipalities of Yucatan | unsupported | in Mexico, municipalities are Overture counties; "municipalities" is a keyword of `city` |
| w030 | Minas Gerais | Photon, not the gazetteer | fuzzy match: "minas" is one edit from the street word "minar" |
| w034 | cities in Minas Gerais with population over 1 million | anchor from Photon, empty result | same |

"departments of Bretagne" (FR) and "provinces of South Africa" (ZA) are correct.

## 5. Recommendation

Do not retrain T5. The template and the split decisions are correct for all world queries. The errors are in the admin level vocabulary and in the gazetteer. Fix these first, in this order:

1. **Admin level words.** Add "prefecture", "local government area", "LGA" and "municipality" to the policy. A level word can mean a different Overture subtype in each country, for example "municipality" is `county` in MX and BR. Put these words in `policy.countries.<CC>`. When the text is an exact keyword of one level, use that level and do not ask the model. This fixes w002, w004, w009, w038, w040, w052 and w059 (7 of 9).
2. **Name suffixes.** "Kyoto" does not find Kyoto Prefecture (`京都府`). "Hokkaido", "Kano" and "Lagos" find their prefecture or state, so the names of these divisions have the short form. Find the prefectures and states with no short name, and add name keys without "Prefecture" (and other level words) at build time.
3. **Street words in the fuzzy match.** Do not give a fuzzy match to a street word ("minar") when the exact name is in the gazetteer ("Minas Gerais" is an exact region name). This fixes w030 and w034.
4. Then build the world gold set again and measure. Retrain the decision model (cross-encoder, on the GPU desktop) only if `fill_closed_slot.admin_level` stays below 95% after item 1.

Other findings from the world data (not in the gold errors):

- "Kyoto" ranks the city above the prefecture, also with the type hint `state`.
- With the NG view, "Lagos" ranks Laos (country) second.
- The gold set has 70 queries, so one error changes the accuracy by 1.4 points. Add more queries before the decision about retraining.

## 6. Phase 8: admin level words and gazetteer fixes

Changes (Python and the browser version):

1. A level word in the text with no typo gives its level without the model, if only one level has the word. Before, "counties" matched "countries" with one typo.
2. New level words: "prefecture", "local government area", "LGA" (options), and "municipality" for MX, CO and PT (`policy.countries.<CC>.level_words`). The country of the map view selects the words.
3. A typo in a street word counts only if the gazetteer has no good match ("Minas Gerais" is not "minar").
4. The gazetteer also tries "<name> prefecture" and "<name> province" (score × 0.98). "Kyoto" with the type hint `state` finds Kyoto Prefecture.

Results:

| Set | Before | After |
|---|---|---|
| India gold | 97/98 | 97/98 |
| India held-out | 30/30 | 30/30 |
| World (70, used to make the fixes) | 61/70 | 70/70 |
| World held-out (29, written after the fixes, before any run) | - | 23/29 (79%) |

The Python reference parse of the India queries changed for 13 of 696 queries. All 13 contain "Connaught Place": "place" was one typo from the street word "palace", so the anchor went to Photon. Now it is the Overture macrohood in New Delhi. The JS parse agrees with the new reference (696/696).

The world set was used to make the fixes, so 70/70 is not a fair measure. The held-out set gives the fair value. Its 6 errors are all admin level words:

| Id | Query | Got | Gold | Cause |
|---|---|---|---|---|
| x005 | provinces of Tuscany | state | district | Italian provinces are Overture counties. "province" is a keyword of `state`. |
| x013 | counties of Kenya | district | state | Kenyan counties are Overture regions. "county" is a keyword of `district`. |
| x022 | departments bordering Cundinamarca | district | state | Colombian departments are Overture regions. French departments are counties. |
| x024 | voivodeships of Poland | unsupported | state | unknown word |
| x026 | coastal voivodeships of Poland | unsupported | state | unknown word |
| x028 | governorates bordering Cairo | none | state | unknown word |

x005 and x013 are errors of change 1: the keyword gives a wrong level with confidence 1.0. The meaning of a level word depends on the country. A word list for each country does not scale to more than 200 countries.

Options for the next step:

1. **Level from the structure of the data.** For "X of <parent>", use the first level below the parent that has children. For "X bordering <place>", use the level of the place. Use the level word only when the data has more than one possible level. This needs no word list and works in all countries.
2. **Level words for each country from a data source** (for example Wikidata "instance of" labels of the divisions: "province of Italy", "county of Kenya"). This is accurate but needs a new build step.
3. **Retrain the decision model** with world examples. This does not fix x005 and x013, because the same word has two meanings.

Recommendation: option 1, then a new held-out set (the current one is now used).

## 7. Phase 9: level words from the data, level from the structure

Changes (Python and the browser version):

1. **Level words from the data.** Overture divisions have `local_type`, the English name of the division type in
   its country (KE regions "county", IT counties "province", CO regions "department", EG regions "governorate"). For
   each country, the values of at least 20% of the regions (level `state`) and counties (level `district`) are level
   words of that country (`local_level_words`; in the browser, `level_words` in `manifest.json`). They replace the
   MX, CO and PT config entries. The words "country", "city", "town" and "village" are not used
   (`policy.local_type_skip`): JP counties are "city", GB regions are "country".
2. **Config words win over data words.** The `local_type` of some countries is not the usual English word: SE and PT
   regions are "region" (the Swedish counties, the Portuguese districts), UA oblasts are "province" and UA raions
   are "region". `policy.countries.<CC>.level_words` has entries for SE, PT and UA.
3. **Level from the structure.** In `children` and `children_with_predicate`, an unknown level word ("voivodeships",
   "oblasts", "cantons") gives no level. The executor then uses the highest subtype below the parent. This applies
   only when the text names the parent and the parent is a country or a dependency. Below a state, an unknown word
   is a level that the data does not have ("talukas of Maharashtra", "blocks in Ranchi"): the query stays
   unsupported.
4. **View country.** The country of the map view is the nearest admin point of the countries whose extent contains
   the view center. Before, a view of Italy gave the Vatican (its point is nearest to the center of Italy). This
   also changed the map-view ranking for views near small countries.
5. **Speed of the Python version.** `Store.describe` reads the ancestor names in one lookup, and the executor
   filters the divisions before it joins the areas. Before, "regions of Italy" took 78 s on the world data; now
   0.5 s. The results did not change. The world gold set runs in 1 minute (before: more than 10 minutes).

Results:

| Set | DAG | Executed result | admin_level (decision alone) |
|---|---|---|---|
| India gold (98) | 97/98 | 88/89 | 100% (48/48) |
| India held-out (30) | 30/30 | 27/27 | 100% (14/14) |
| World (70) | 70/70 | 70/70 | 100% (32/32) |
| World held-out 1 (29, used in phase 8) | 27/29 | 29/29 | 86% (12/14) |
| World held-out 2 (34, new), first run | 30/34 (88%) | 32/34 (94%) | 90% (18/20) |
| World held-out 2, after change 2 | 33/34 | 34/34 | 100% (20/20) |

`gold/world_heldout2_src.yaml` was written after the phase 9 code and before any run: 34 queries in 12 countries
(TR, PK, VN, PE, CL, SE, NL, PT, TZ, NZ, CH, UA). The first run is the fair value. Change 2 used its two errors
(y017 "counties of Sweden", y024 "districts of Portugal"), so the second run is not a fair value.

The remaining DAG errors are not errors in the result. With change 3, the DAG has no level, and the gold DAG has
`state` (x024, x026 "voivodeships of Poland", y034 "oblasts of Ukraine"). In y028 ("regions bordering Dodoma") the
DAG has no level, and the executor uses the level of Dodoma. The executed results are correct.

The India reference parse changed for 5 of 696 queries. All 5 are unsupported before and after; only the reason
changed (for example "the text 'talukas' names no known admin_level"). The JS parse agrees with the reference
(696/696 for the flat layout and for the country layout).

Retraining: `fill_closed_slot.admin_level` is 100% on the India sets and 90% on the first run of the new held-out
set. The two errors come from the data labels, not from the model. Do not retrain for the admin levels. The level
words of the config (SE, PT, UA) are a temporary fix: the Wikidata labels of the division types (plan-025, phase 11)
can replace them.

Limits:

- The view country selects the level words. "counties of Kenya" with a US view gives `district`.
- An unknown word below a country always gives the first level below it. A word for a lower level gives the
  wrong level ("parishes of Ecuador" gives the provinces).

## 8. Phase 10: qualified names and directions in region slots

Changes (Python and the browser version):

1. **Qualified names.** "A, B" or "A, B, C" (no "and"): the best gazetteer candidate of A that is inside an exact
   match of each later name. The DAG is `Resolve(A, id, context="B")`. Exact names first; if no exact name of A is
   inside B, the fuzzy names ("Sanfransisco, California": "San Fransisco" is an exact name of a neighborhood in
   another country). If no candidate is inside, the parse continues as before ("Kerala, Tamil Nadu" is a union,
   "MG Road, Bangalore" goes to Photon). This applies to the whole query and to region slots ("hospitals in
   Paris, Texas").
2. **Directions in region slots.** A slot text that is a direction word of 4 or more letters and an exact place
   name ("northern France") is a subquery, without the model. A text that is itself an exact name stays a name
   ("Central Delhi", "East Godavari").
3. **Executor:** `Children` of a direction part used the id of the source and returned all children of the whole
   place. Now it uses the geometry of the part ("districts in eastern Germany": 160 of 399).

Results:

| Set | Template | DAG | Executed result |
|---|---|---|---|
| Held-out 3 (19, new: 12 qualified names, 4 directions in slots, 3 that must not change) | 19/19 | 17/19 | 17/19 |
| World, held-out 1, held-out 2 | no change | no change | no change |
| India gold, India held-out | no change | no change | no change |

The India reference parse did not change (696 queries). JS parity: 696/696 (flat and country layout), int8
681/696, executor 88/88.

The two errors of held-out 3 are the choice between a city and a county with the same name: "London, Ontario"
gives London county, "Alexandria, Virginia" gives the county record of the independent city. The rule finds the
correct place; the ranking prefers the county, as it does for "London" alone. A policy "prefer the city when a city
and a county have the same name and one contains the other" can fix this, but it also changes India (for example
Pune city and Pune district). Measure it separately before a change.

Not in this phase: names without a comma ("Paris Texas") and qualified names that are not in the gazetteer
("MG Road, Bangalore" stays Photon).

## 9. Test runs

The checks run on the GPU desktop (24 cores) in parallel (`checks.sh`): the gold sets, the India reference and the
unit tests together, then the parity checks (each in 4 processes, `parity.ts --shards 4`, `ORT_THREADS=2`). Total:
11 minutes (before: 24 minutes in sequence).

The live smoke tests run on the desktop in Chromium. Headless Firefox and WebKit on the desktop (Pop!_OS 22.04)
have no WebGL, and the map needs WebGL. Run them on the Mac when a change touches the loading, the data or the
drawing code. Open item: the page shows no message if WebGL is not available.

Results:

| Set | Template | DAG | Executed result |
|---|---|---|---|
| Held-out 4 (21, new: natural features), first run | 16/21 | 14/21 | 14/21 (67%) |
| Held-out 4, after change 2 | 16/21 | 16/21 | 16/21 (76%) |
| Held-out 3, held-out 2, held-out 1, world | no change | no change | no change |
| India gold, India held-out | no change | no change | no change |

The first run is the fair value. Change 2 used its two errors ("Lake Victoria", "10 km around Lake Geneva": Photon,
because "lake" is a street word). The India reference parse did not change (696 queries). JS parity: 696/696 (flat
and country layout), int8 681/696, executor 88/88.

The 5 remaining errors are template choices of the T5 model, which has no training examples for these forms:

| Query | T5 template | Correct |
|---|---|---|
| Ganga river | along_border | lookup_place |
| districts along the Yamuna | children_with_predicate | children_touching (no parent) |
| the Alps, the Andes | children ("Alps" as a level word) | lookup_place |
| districts in the Western Ghats | lookup_place | children (natural parent) |

The data, the search and the executor give the correct result for these queries when the template is correct
(gold DAGs, exec_parity). Add training examples for them in plan-025 phase 13.

Limits:

- "the Amazon rainforest": Natural Earth has no forests. "Amazon basin" is the nearest feature. An open data set of
  ecoregions (for example WWF, CC BY 4.0) can add forests.
- "Amazon" alone: the state Amazonas and the Amazon River have close scores (the decision model chooses).
- The browser loads the name shards again after this release: the new names change most shards (about 195 MB).

## 10. Lists of places, the any/all quantifier and ranking per parent (plan-036)

Changes (Python and the browser version):

1. **Lists of places.** A region slot can hold a list: "France, Switzerland and Germany", "France or Germany". The
   list is the `Union` of its names. Commas alone do not make a list ("Paris, Texas" is a qualified name). A name that
   contains "and" stays one name ("Bosnia and Herzegovina"): the split with the fewest parts in which each part is an
   exact name wins.
2. **Quantifier.** `neighbors` and `children_touching` have an optional slot `quant` (`any` or `all`). "both", "all
   of" and "each of" give `all`. "either", "any of" and "or" give `any`. A plain "and" gives `any`, and the result
   shows a note: "'and' between the places is read as 'or' (any of them); say 'both' or 'all of' for all of them".
3. **Operators.** `Neighbors(quant=all)` and `Touches(quant=all)`: within the tolerance of each member.
   `SharedBorder` takes one set of 2 or more places: the union of the borders between each pair, with a note for 3
   or more places. `Top(per=level)`: the top n in each division of the `per` level.
4. **Templates.** `neighbors_both` is removed (it is `neighbors` with `quant=all`). `shared_border` has one slot
   `places`. New template `children_top_per` ("the largest district in each state of India"). 27 templates.
5. **Models.** T5 v5 (val exact match 0.947; v4: 0.9457) and cross-encoder v4 (new decision
   `fill_closed_slot.quantifier`, val 61/61). New training data: lists, quantifier words and `children_top_per` in the
   synthetic generator, and 2,739 LLM paraphrases of list queries ($0.21).

Results (browser setup, `--setup web`):

| Set | Template | DAG | Executed result |
|---|---|---|---|
| Held-out 6 (28, new: lists, any/all, ranking per parent, names with "and"), first run | 27/28 | 26/28 | 27/28 (96%) |
| Held-out 5 | 24/24 | 23/24 | 23/24 (24/24 before) |
| Held-out 4 | 21/21 | 21/21 (20/21 before) | 21/21 |
| Held-out 3 | 19/19 | 17/19 | 17/19 (no change) |
| Held-out 2 | 34/34 | 34/34 (33/34 before) | 34/34 |
| Held-out 1, world | no change | no change | no change |
| India gold | 98/98 | 97/98 (98/98 before) | 89/89 (no change) |
| India held-out | no change | no change | no change |

JS parity: 696/696 (flat and country layout), int8 683/696 (681 before), executor 88/88, operator tests 15/15.

Errors:

| Set | Query | Result | Cause |
|---|---|---|---|
| Held-out 6 | districts of Kerala and Goa | `Union(Children(Kerala), Goa)` | Template choice (T5 and the decision model choose `union`) |
| Held-out 6 | England and Wales | `Union(England ∪ Wales, England ∪ Wales)` | T5 puts the full text in both slots. The result is correct. |
| Held-out 5 | districts in the Aravalli range | The districts of Aravalli district | The top T5 frame drops "range" |
| India gold | Kerala and coastal districts of Karnataka | The two parts in the other order | The result is the same. The DAG comparison is not commutative. |

The India reference parse (696 informal queries, no gold labels) changed for 28 queries. By eye: 13 are better, 8 have
no change in quality, 7 are worse.

- Better: lists in a slot ("coastal districts of Odisha, Andhra Pradesh and West Bengal", "5 km around Charminar,
  Hitec City and Secunderabad", "West Bengal without Kolkata and Howrah"), typos ("nothern Gujarat", "Wich state is
  Siliguri in?", "bewteen Lucknow and Kanpur"), and 3 wrong parses that are now `Unsupported`.
- Worse: "madhya pradesh except bhopal n indore" ("n" is not a list separator; it goes to Photon as one name), two
  intersections ("Ernakulam intersect with 10 km along the coast of Kerala" loses Ernakulam), "areas souht of
  Hyderabad" (now `Unsupported`), "nortern Karnataka" (northeast), "banglore airport" (Photon) and "border area with
  Bangladesh in Tripura" (the union of Bangladesh and Tripura).

Browser smoke test (Chromium, the plan-036 queries, `SET=lists`): all results and notes are correct, except
"the largest county in each region of Kenya". It gives 1 county. In Overture the 47 counties of Kenya are the
`state` level and Kenya has no level above them, so "county" and "region" are both `state` and `Top(per=state)` has
no groups. This is a silent wrong answer. The executor must give an error when no row has a parent at the `per`
level.

Follow-ups (plan-037):

- `Top(per=level)` gives an error if no member is inside a division of the `per` level. "the largest county in each
  region of Kenya" now shows "these places are not inside any division of the level 'state'".
- " n " is a list separator. "madhya pradesh except bhopal n indore" is now `Difference(Madhya Pradesh,
  Union(Bhopal, Indore))`. This is the only change in the India reference parse.
- The gold DAG comparison ignores the order of the parts of a union. India gold DAG: 98/98.

All other sets, JS parity (696/696, int8 683/696), executor 88/88 and the operator tests 15/15 did not change.
