# Gold suite `gold`: provider `config`

Records: 98. Depth 0: 85. Depth 1 (two levels): 13.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 99% (110/111) | 99% (97/98) | 100% (13/13) | 0 | 1.00 |
| pick_template | 100% (111/111) | 100% (98/98) | 100% (13/13) | 0 | 1.00 |
| pick_template_flat | 95% (106/111) | 95% (93/98) | 100% (13/13) | 0 | 0.93 |
| pick_split | 100% (111/111) | 100% (98/98) | 100% (13/13) | 0 | 0.97 |
| is_subquery | 100% (114/114) | 100% (101/101) | 100% (13/13) | 0 | 0.94 |
| select_source | 100% (24/24) | 100% (24/24) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 100% (48/48) | 100% (37/37) | 100% (11/11) | 0 | 1.00 |
| fill_closed_slot.attr | 100% (11/11) | 100% (11/11) | - | 0 | 1.00 |
| fill_closed_slot.category | 100% (12/12) | 100% (12/12) | - | 0 | 1.00 |
| fill_closed_slot.direction | 100% (6/6) | 100% (6/6) | - | 0 | 1.00 |
| fill_closed_slot.op | 100% (11/11) | 100% (11/11) | - | 0 | 1.00 |
| fill_closed_slot.predicate | 100% (16/16) | 100% (10/10) | 100% (6/6) | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| g006 | pick_template_flat | 0 | lookup_place | union | 0.10104599999999997 |
| g010 | pick_template_flat | 0 | lookup_place | direction_part | 0.013128000000000029 |
| g066 | pick_template_flat | 0 | features_in | features_near | 0.10424999999999995 |
| g088 | pick_family | 0 | set_algebra | predicate_filter | 0.945862 |
| g090 | pick_template_flat | 0 | children | children_touching | 0.9137980000000001 |
| g092 | pick_template_flat | 0 | neighbors | children_with_predicate | 0.6900580000000001 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| attribute | 100% (11/11) | 100% (11/11) | 100% (11/11) | 0 | 100% (11/11) |
| features | 100% (12/12) | 100% (12/12) | 100% (12/12) | 0 | 100% (9/9) |
| hierarchy | 100% (15/15) | 100% (15/15) | 100% (15/15) | 0 | 100% (15/15) |
| lookup | 100% (11/11) | 100% (11/11) | 100% (11/11) | 0 | 100% (8/8) |
| modifier | 100% (14/14) | 100% (14/14) | 100% (14/14) | 0 | 100% (11/11) |
| predicate_filter | 100% (12/12) | 100% (12/12) | 100% (12/12) | 0 | 100% (12/12) |
| relational | 100% (11/11) | 100% (11/11) | 100% (11/11) | 0 | 100% (11/11) |
| set_algebra | 92% (11/12) | 92% (11/12) | 92% (11/12) | 1 | 92% (11/12) |
| ALL | 99% (97/98) | 99% (97/98) | 99% (97/98) | 1 | 99% (88/89) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 100% (85/85) | 1.30 s | 4.6 | 1.3 |
| 1 | 92% (12/13) | 3.20 s | 8.4 | 2.7 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| g053 | overlap of Bengaluru Urban and 10 km around Whitefield | None | low confidence for is_subquery (0.02) |

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
