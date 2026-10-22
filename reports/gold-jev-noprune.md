# Gold suite `gold`: provider `jev`

Records: 98. Depth 0: 85. Depth 1 (two levels): 13.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 97% (108/111) | 97% (95/98) | 100% (13/13) | 0 | 0.94 |
| pick_template | 97% (108/111) | 97% (95/98) | 100% (13/13) | 0 | 0.98 |
| pick_template_flat | 97% (108/111) | 97% (95/98) | 100% (13/13) | 0 | 0.97 |
| pick_split | 100% (111/111) | 100% (98/98) | 100% (13/13) | 0 | 1.00 |
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
| g014 | pick_template_flat | 0 | buffer | features_near | 0.75 |
| g020 | pick_family | 0 | modifier | lookup | 0.7 |
| g039 | pick_template | 0 | children_with_predicate | children_touching | 0.94 |
| g039 | pick_template_flat | 0 | children_with_predicate | children_touching | 0.55 |
| g090 | pick_template | 0 | children | neighbors | 0.56 |
| g090 | pick_template_flat | 0 | children | children_touching | 0.93 |
| g091 | pick_template | 0 | children_with_predicate | children_touching | 0.06 |
| g092 | pick_family | 0 | hierarchy | predicate_filter | 0.59 |
| g096 | pick_family | 0 | attribute | set_algebra | 0.47 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported |
|---|---|---|---|---|
| attribute | 91% (10/11) | 91% (10/11) | 91% (10/11) | 1 |
| features | 100% (12/12) | 100% (12/12) | 100% (12/12) | 0 |
| hierarchy | 87% (13/15) | 87% (13/15) | 87% (13/15) | 2 |
| lookup | 100% (11/11) | 100% (11/11) | 100% (11/11) | 0 |
| modifier | 93% (13/14) | 93% (13/14) | 93% (13/14) | 0 |
| predicate_filter | 83% (10/12) | 83% (10/12) | 83% (10/12) | 2 |
| relational | 100% (11/11) | 100% (11/11) | 100% (11/11) | 0 |
| set_algebra | 100% (12/12) | 100% (12/12) | 100% (12/12) | 0 |
| ALL | 94% (92/98) | 94% (92/98) | 94% (92/98) | 5 |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 98% (83/85) | 0.09 s | 4.3 | 2.7 |
| 1 | 69% (9/13) | 0.12 s | 6.5 | 4.8 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| g020 | south bangalore | lookup_place | template |
| g039 | border districts of Punjab | None | template children_touching has no valid split |
| g090 | districts of states that border Goa | None | template neighbors has no valid split |
| g091 | coastal districts of states that border Goa | None | low confidence for pick_template (0.06) |
| g092 | districts that border coastal districts of Odisha | None | template children_touching has no valid split |
| g096 | cities with population over 1 million in states that border Gujarat | None | template intersection has no valid split |

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
