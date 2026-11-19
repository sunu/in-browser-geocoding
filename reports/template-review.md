# Template review against gazet (plan-025, phase 12)

Date: 2026-11-19. Source: https://github.com/developmentseed/gazet, commit 05c2301 (2026-09-25),
`dataset/scripts/sql_templates.py`: 72 SQL templates in 18 families. Gazet writes SQL with a language model; the
templates make its training data. We have 21 templates (DSL DAGs).

## 1. Gazet families that we have

| Gazet family (templates) | Example | Our template |
|---|---|---|
| direct_lookup (lookup_01, 02) | "show me the Alps" | lookup_place (natural features since phase 11) |
| disambiguation (disambiguate_01 to 03) | "Loja, Ecuador" | qualified names (phase 10, comma only) |
| adjacency of divisions (adj_01, 02, 04, 05) | "which countries border Peru" | neighbors |
| containment (contain_01, 03) | "what counties are in Loja" | children |
| containment, parent (contain_02) | "which country is Loja in" | parent |
| buffer (buffer_01, 03) | "50 km buffer around Loja" | buffer |
| difference (diff_01) | "Loja excluding Zamora" | difference |
| set_operations (union_01, 03) | "Loja and Piura" | union, union3 |
| partial_selection (partial_01 to 04) | "the northern half of Loja" | direction_part |
| chained, coast (chained_01, 02, 06, 07, 10, 11) | "coastal states of Mexico" | children_with_predicate |

## 2. Gaps

| # | Gazet (templates) | Example | What we need | Training only? |
|---|---|---|---|---|
| G1 | border_corridor (corridor_01) | "10 km zone along the border between Spain and Portugal" | operator SharedBorder(a, b), template shared_border (with an optional distance) | no |
| G2 | adjacency to natural features (adj_03, adj_09 to 12), intersection (intersect_05) | "which rivers flow through Kerala", "mountain ranges of Nepal", "seas that touch India" | operator NaturalIn(region, kind), template natural_in | no |
| G3 | divisions along a natural feature (adj_06 to 08, intersect_03, 04, 06, contain_05) | "countries along the Danube", "districts the Ganges flows through" | neighbors / children_touching with a natural anchor (works since phase 11) | yes |
| G4 | divisions inside a natural region (contain_04), part of a division inside or outside a natural feature (partial_05, diff_02) | "districts in the Western Ghats", "Karnataka outside the Western Ghats" | children, intersection, difference with a natural anchor (works since phase 11) | yes |
| G5 | buffer of divisions (buffer_02, buffer_11) | "districts within 50 km of Goa", "countries within 100 km of the Nile" | template children_near: Filter(Children(parent), Touches(Buffer(other, d))) | no (template only) |
| G6 | aggregation, window (agg_01 to 04, window_03, 04) | "5 largest districts of Karnataka", "the smallest state of India" | operator Top(set, by: area or population, n, order); template children_top | no |
| G7 | chained, neighbors with a predicate (chained_12, 13) | "coastal countries that border India" | template neighbors_with_predicate: Filter(Neighbors(x), pred) | no (template only) |
| G8 | multi_adjacency (multi_adj_01 to 03) | "states that border both Karnataka and Kerala" | operator Common(a, b) (members of both sets); template neighbors_both | no |
| G9 | chained, natural predicates (chained_04, 05, 08, 09) | "riverside districts of Kerala", "mountain districts of Nepal" | predicates on_river, in_mountains (natural features of a kind as a layer) | no |
| G10 | disambiguation with "in" (disambiguate_01) | "Springfield in Illinois" | the qualified-name rule for "A in B" (no training) | no (rule) |

Not taken: per-region window functions (window_01, 02: "the largest county in each region"), attributes that
only exist in Overture's `is_land` / `is_territorial` (attr_01 to 04), "merge all counties of X" (union_02: the same
area as X).

## 3. Recommendation

Phase 12: operators SharedBorder, NaturalIn, Top, Common; predicates on_river, in_mountains; the rule of G10. Test
each with gold DAGs (exec parity) before any training. Phase 13: templates shared_border, natural_in, children_near,
children_top, neighbors_with_predicate, neighbors_both and the training examples of G3, G4 and of plan-025 phase 13
(the T5 gaps of phase 11), in one T5 training run.

Order by value (estimate): G1, G2, G3/G4 (training only), G6, G5, G7, G9, G8, G10.

## 4. Phase 12 result (2026-11-19)

Operators and predicates in Python and in the browser version. `gold/build_ops.py` writes `gold/ops.jsonl`: 14 DAGs
(no templates yet), expected results from the Python executor on the world data. The browser executor gives the
same result for all of them (`SETS=ops exec_parity.ts`: 11 of 11 sets, 3 of 3 geometries).

| Gap | Part | Test query | Result |
|---|---|---|---|
| G1 | SharedBorder(a, b): a line; a zone is Along(SharedBorder, d) | border between Spain and Portugal; 10 km zone along the border of India and Pakistan | line; 53,279 km² |
| G2 | Naturals(kind, within) | rivers in Karnataka; mountain ranges of Nepal | 6 rivers (Kaveri, Krishna, ...); Himalayas, Siwalik Hills |
| G3 | Neighbors of a natural feature (phase 11) | countries along the Danube | 9 countries |
| G4 | Intersect with a natural feature (phase 11) | Karnataka within the Western Ghats | geometry |
| G5 | Touches(Buffer(x, d)) | districts of Maharashtra within 50 km of Goa | Kolhapur, Sindhudurg |
| G6 | Top(set, by, n, order) | 5 largest districts of Karnataka; the smallest state of India | Belagavi, ...; Lakshadweep |
| G7 | Filter(Neighbors, coastal) | coastal countries that border India | BD, CN, MM, PK |
| G8 | Common(a, b) | states that border both Karnataka and Kerala | Tamil Nadu |
| G9 | predicates on_river, in_mountains | riverside districts of Karnataka; mountain districts of Uttarakhand | 24; 12 of 13 |
| G10 | "A in B" qualified names (exact names; not with a word of a set) | Jayanagar in Bengaluru | unit test |

Fixed on the way:

- Along of a line (a river, a shared border) buffered the two end points of the line, not the line.
- Touches and Intersects with a set as the target test each member (EXISTS), not the union of the set. The union of
  all mountain ranges failed in the browser (GEOS topology error) and took 400 s.
- Touches with a computed geometry (no id) as the target failed in the browser (NULL id type).
- Predicates on countries that are not loaded in the browser computed the distance to the coastline (400 s for
  "coastal countries that border India"). The browser now loads the layer distances of all countries, dependencies
  and regions at start-up (`global/admin_layer_dist.parquet`, 108 KB).

Data limit: Natural Earth 10m has only the large rivers (no river in Kerala).

Other results: the India reference parse changed for 1 query: "hilly districts of Uttarakhand" is now supported (the
new predicate in_mountains). All gold sets and the JS parity checks are unchanged (696/696, int8 681/696, executor
88/88). Two Jev replay answers were recorded again (the predicate options changed).

## 5. Phase 13 result (2026-11-19)

Six templates (shared_border, natural_in, children_near, children_top, neighbors_with_predicate, neighbors_both;
27 in all), two closed option lists (natural_kinds, rank_orders), T5 t5-small v4 and cross-encoder v3.

Training data: synthetic 30,000 (world names and natural features added), paraphrases 13,783 (3,782 new by
anthropic/claude-haiku-5.5, $0.21), decisions 141,975. All evaluation queries (all gold sets, LLM dev and test) are
now removed from every training source (`training/evalset.py`); before, only the two India sets were, and 8
evaluation queries were in the data (6 of them in the data of v3 too). T5 v4: validation exact match 94.6% (v3
94.9%), 246 s on the RTX 3090. Cross-encoder v3: 12.5 minutes.

Rules added in this phase (Python and the browser version), because the decisions were not stable between
training runs:

- A region text with an admin level word or a distance and no exact gazetteer match is a sub-query ("coastal
  districts of Odisha"). The cross-encoder gave 0.14 (v3) and 0.44 (v2) for this; the threshold is 0.2.
- A region text that is an exact gazetteer name, without a level word, a distance or a leading direction word, is a
  place ("Western Ghats").
- If T5 gives natural_in and the whole text is an exact natural feature, the parse is a lookup ("Ganga river").

Results (executed result):

| Set | Phase 12 | Phase 13 |
|---|---|---|
| India gold | 88/89 (DAG 97/98) | 89/89 (DAG 98/98) |
| India held-out | 27/27 | 27/27 |
| World | 70/70 | 69/70 |
| World held-out 1, 2, 3 | 29/29, 34/34, 17/19 | 29/29, 33/34, 17/19 |
| World held-out 4 (natural features) | 16/21 | 20/21 |
| World held-out 5 (new templates, first run of the new models) | - | 23/24 |

JS parity 696/696 (flat and country layout), int8 678/696 (681 before), executor 88/88, operator tests 11/11.
The India reference parse changed for 53 of 696 queries: 20 unsupported queries now parse, 2 parsed queries are now
unsupported, 25 parse to another DAG.

Open errors: "England and Wales" (T5: one place), "coastal regions of Chile" (T5: along_coast), "districts in the
Western Ghats" (the parent becomes a direction part), "districts along the Godavari" (T5: neighbors, 5 of 24
districts), "London, Ontario" and "Alexandria, Virginia" (city or county with the same name, phase 10).
