# Gold suite `gold`: provider `rules`

Records: 98. Depth 0: 85. Depth 1 (two levels): 13.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 97% (108/111) | 97% (95/98) | 100% (13/13) | 0 | 0.95 |
| pick_template | 100% (111/111) | 100% (98/98) | 100% (13/13) | 0 | 0.97 |
| pick_template_flat | 97% (108/111) | 97% (95/98) | 100% (13/13) | 0 | 0.95 |
| pick_split | 100% (111/111) | 100% (98/98) | 100% (13/13) | 0 | 1.00 |
| is_subquery | 100% (114/114) | 100% (101/101) | 100% (13/13) | 0 | 0.88 |
| select_source | 100% (24/24) | 100% (24/24) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 100% (48/48) | 100% (37/37) | 100% (11/11) | 0 | 0.99 |
| fill_closed_slot.attr | 100% (11/11) | 100% (11/11) | - | 0 | 1.00 |
| fill_closed_slot.category | 100% (12/12) | 100% (12/12) | - | 0 | 1.00 |
| fill_closed_slot.direction | 100% (6/6) | 100% (6/6) | - | 0 | 1.00 |
| fill_closed_slot.op | 100% (11/11) | 100% (11/11) | - | 0 | 1.00 |
| fill_closed_slot.predicate | 100% (16/16) | 100% (10/10) | 100% (6/6) | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| g004 | pick_family | 0 | lookup | set_algebra | 1.0 |
| g004 | pick_template_flat | 0 | lookup_place | union | 1.0 |
| g010 | pick_family | 0 | lookup | modifier | 1.0 |
| g010 | pick_template_flat | 0 | lookup_place | direction_part | 1.0 |
| g015 | pick_family | 0 | modifier | features | 0.5 |
| g015 | pick_template_flat | 0 | buffer | features_in | 0.5 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| attribute | 100% (11/11) | 100% (11/11) | 100% (11/11) | 0 | 100% (11/11) |
| features | 100% (12/12) | 100% (12/12) | 100% (12/12) | 0 | - |
| hierarchy | 100% (15/15) | 100% (15/15) | 100% (15/15) | 0 | 100% (15/15) |
| lookup | 91% (10/11) | 91% (10/11) | 91% (10/11) | 1 | 100% (8/8) |
| modifier | 93% (13/14) | 93% (13/14) | 93% (13/14) | 0 | 100% (11/11) |
| predicate_filter | 100% (12/12) | 100% (12/12) | 100% (12/12) | 0 | 100% (12/12) |
| relational | 100% (11/11) | 100% (11/11) | 100% (11/11) | 0 | 100% (11/11) |
| set_algebra | 100% (12/12) | 100% (12/12) | 100% (12/12) | 0 | 100% (12/12) |
| ALL | 98% (96/98) | 98% (96/98) | 98% (96/98) | 1 | 100% (80/80) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 98% (83/85) | 0.09 s | 3.6 | 2.0 |
| 1 | 100% (13/13) | 0.10 s | 7.0 | 4.5 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| g004 | MG Road, Bangalore | None | cannot resolve 'MG Road' in the local extract |
| g015 | 500m around Indiranagar metro station | features_in | template |

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
