# Gold suite `gold`: provider `jev`

Records: 98. Depth 0: 85. Depth 1 (two levels): 13.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 98% (109/111) | 98% (96/98) | 100% (13/13) | 0 | 0.94 |
| pick_template | 99% (110/111) | 99% (97/98) | 100% (13/13) | 0 | 0.99 |
| pick_template_flat | 99% (110/111) | 99% (97/98) | 100% (13/13) | 0 | 0.98 |
| pick_split | 99% (110/111) | 99% (97/98) | 100% (13/13) | 0 | 0.99 |
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
| g020 | pick_family | 0 | modifier | lookup | 0.45 |
| g077 | pick_split | 0 | {"level": "districts", "parent": "Kerala", "opseg": "more than", "v... | {"level": "districts", "parent": "Kerala", "opseg": "more than", "v... | 0.74 |
| g090 | pick_template_flat | 0 | children | children_touching | 0.91 |
| g091 | pick_template | 0 | children_with_predicate | children_touching | 0.06 |
| g096 | pick_family | 0 | attribute | set_algebra | 0.46 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| attribute | 91% (10/11) | 82% (9/11) | 82% (9/11) | 1 | 91% (10/11) |
| features | 100% (12/12) | 100% (12/12) | 100% (12/12) | 0 | - |
| hierarchy | 100% (15/15) | 100% (15/15) | 100% (15/15) | 0 | 100% (15/15) |
| lookup | 100% (11/11) | 100% (11/11) | 100% (11/11) | 0 | 100% (8/8) |
| modifier | 93% (13/14) | 93% (13/14) | 93% (13/14) | 1 | 91% (10/11) |
| predicate_filter | 92% (11/12) | 92% (11/12) | 92% (11/12) | 1 | 92% (11/12) |
| relational | 100% (11/11) | 100% (11/11) | 100% (11/11) | 0 | 100% (11/11) |
| set_algebra | 100% (12/12) | 100% (12/12) | 100% (12/12) | 0 | 100% (12/12) |
| ALL | 97% (95/98) | 96% (94/98) | 96% (94/98) | 3 | 96% (77/80) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 98% (83/85) | 0.12 s | 4.2 | 2.2 |
| 1 | 85% (11/13) | 0.10 s | 6.7 | 4.6 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| g020 | south bangalore | None | low confidence for pick_family (0.28) |
| g077 | districts of Kerala with more than 30 lakh people | children_attr | value: expected 3000000, got 30.0 |
| g091 | coastal districts of states that border Goa | None | low confidence for pick_template (0.06) |
| g096 | cities with population over 1 million in states that border Gujarat | None | the text is not one place name, and no other template matches |

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
