# Gold suite: provider `jev`

Records: 98. Depth 0: 85. Depth 1 (two levels): 13.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 95% (106/111) | 95% (93/98) | 100% (13/13) | 0 | 0.89 |
| pick_template | 98% (109/111) | 98% (96/98) | 100% (13/13) | 0 | 0.99 |
| pick_template_flat | 99% (110/111) | 99% (97/98) | 100% (13/13) | 0 | 0.98 |
| pick_split | 99% (110/111) | 99% (97/98) | 100% (13/13) | 0 | 0.97 |
| is_subquery | 100% (114/114) | 100% (101/101) | 100% (13/13) | 0 | 0.95 |
| select_source | 100% (24/24) | 100% (24/24) | - | 0 | 0.99 |
| fill_closed_slot.admin_level | 100% (48/48) | 100% (37/37) | 100% (11/11) | 0 | 0.99 |
| fill_closed_slot.attr | 100% (11/11) | 100% (11/11) | - | 0 | 1.00 |
| fill_closed_slot.category | 100% (12/12) | 100% (12/12) | - | 0 | 1.00 |
| fill_closed_slot.direction | 100% (6/6) | 100% (6/6) | - | 0 | 1.00 |
| fill_closed_slot.op | 100% (11/11) | 100% (11/11) | - | 0 | 1.00 |
| fill_closed_slot.predicate | 100% (16/16) | 100% (10/10) | 100% (6/6) | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| g020 | pick_family | 0 | modifier | lookup | 0.28 |
| g077 | pick_split | 0 | {"level": "districts", "parent": "Kerala", "opseg": "more than", "v... | {"level": "districts", "parent": "Kerala", "opseg": "more than", "v... | 0.74 |
| g080 | pick_family | 0 | attribute | predicate_filter | 0.5 |
| g090 | pick_family | 0 | hierarchy | predicate_filter | 0.86 |
| g090 | pick_template | 0 | children | neighbors | 0.56 |
| g090 | pick_template_flat | 0 | children | children_touching | 0.82 |
| g091 | pick_template | 0 | children_with_predicate | children_touching | 0.06 |
| g092 | pick_family | 0 | hierarchy | predicate_filter | 0.4 |
| g096 | pick_family | 0 | attribute | set_algebra | 0.62 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| attribute | 82% (9/11) | 82% (9/11) | 82% (9/11) | 2 | 82% (9/11) |
| features | 92% (11/12) | 92% (11/12) | 92% (11/12) | 1 | - |
| hierarchy | 73% (11/15) | 73% (11/15) | 73% (11/15) | 3 | 73% (11/15) |
| lookup | 100% (11/11) | 100% (11/11) | 100% (11/11) | 0 | 100% (8/8) |
| modifier | 93% (13/14) | 93% (13/14) | 86% (12/14) | 1 | 82% (9/11) |
| predicate_filter | 92% (11/12) | 92% (11/12) | 92% (11/12) | 1 | 92% (11/12) |
| relational | 91% (10/11) | 91% (10/11) | 82% (9/11) | 1 | 82% (9/11) |
| set_algebra | 92% (11/12) | 92% (11/12) | 92% (11/12) | 1 | 92% (11/12) |
| ALL | 89% (87/98) | 89% (87/98) | 87% (85/98) | 10 | 85% (68/80) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 91% (77/85) | 0.08 s | 3.7 | 2.1 |
| 1 | 62% (8/13) | 0.11 s | 6.6 | 4.5 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| g020 | south bangalore | None | low confidence for pick_family (0.28) |
| g023 | east of Pune | direction_outside | DAG differs |
| g028 | dists of odisha | None | low confidence for pick_family (0.28) |
| g030 | which district is Whitefield in | None | low confidence for disambiguate (0.04) |
| g053 | overlap of Bengaluru Urban and 10 km around Whitefield | None | low confidence for disambiguate (0.18) |
| g056 | area between Pune and Mumbai | between | DAG differs |
| g057 | region between chennai and pondicherry | None | low confidence for disambiguate (0.08) |
| g073 | petrol pumps near Whitefield | None | low confidence for disambiguate (0.14) |
| g080 | states of India with population over 10 crore | None | low confidence for is_subquery (0.16) |
| g090 | districts of states that border Goa | None | low confidence for is_subquery (0.12) |
| g091 | coastal districts of states that border Goa | None | low confidence for pick_template (0.06) |
| g092 | districts that border coastal districts of Odisha | children_with_predicate | template |
| g096 | cities with population over 1 million in states that border Gujarat | None | cannot resolve 'cities' in the local extract |

### Nested template pairs in the gold suite

| Outer | Inner | Count |
|---|---|---|
| intersection | buffer | 2 |
| features_near | children_with_predicate | 1 |
| features_in | children_with_predicate | 1 |
| buffer | children | 1 |
| union | children_with_predicate | 1 |
| difference | children_with_predicate | 1 |
| children | neighbors | 1 |
| children_with_predicate | neighbors | 1 |
| neighbors | children_with_predicate | 1 |
| children_attr | neighbors | 1 |
| between | children_with_predicate | 1 |
| direction_part | children | 1 |
