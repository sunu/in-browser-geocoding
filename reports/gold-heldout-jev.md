# Gold suite `heldout`: provider `jev`

Records: 30. Depth 0: 27. Depth 1 (two levels): 3.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 100% (33/33) | 100% (30/30) | 100% (3/3) | 0 | 0.95 |
| pick_template | 97% (32/33) | 97% (29/30) | 100% (3/3) | 0 | 0.98 |
| pick_template_flat | 100% (33/33) | 100% (30/30) | 100% (3/3) | 0 | 0.97 |
| pick_split | 100% (33/33) | 100% (30/30) | 100% (3/3) | 0 | 1.00 |
| is_subquery | 100% (36/36) | 100% (33/33) | 100% (3/3) | 0 | 0.96 |
| select_source | 100% (9/9) | 100% (9/9) | - | 0 | 1.00 |
| fill_closed_slot.admin_level | 100% (14/14) | 100% (11/11) | 100% (3/3) | 0 | 1.00 |
| fill_closed_slot.attr | 100% (1/1) | 100% (1/1) | - | 0 | 1.00 |
| fill_closed_slot.category | 100% (3/3) | 100% (3/3) | - | 0 | 1.00 |
| fill_closed_slot.direction | 100% (2/2) | 100% (2/2) | - | 0 | 1.00 |
| fill_closed_slot.op | 100% (1/1) | 100% (1/1) | - | 0 | 1.00 |
| fill_closed_slot.predicate | 100% (6/6) | 100% (4/4) | 100% (2/2) | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| h028 | pick_template | 0 | children_with_predicate | children_touching | 0.4 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| attribute | 100% (1/1) | 100% (1/1) | 100% (1/1) | 0 | 100% (1/1) |
| features | 100% (3/3) | 100% (3/3) | 100% (3/3) | 0 | - |
| hierarchy | 100% (5/5) | 100% (5/5) | 100% (5/5) | 0 | 100% (5/5) |
| lookup | 100% (4/4) | 100% (4/4) | 100% (4/4) | 0 | 100% (2/2) |
| modifier | 100% (5/5) | 100% (5/5) | 100% (5/5) | 0 | 100% (4/4) |
| predicate_filter | 80% (4/5) | 80% (4/5) | 80% (4/5) | 1 | 80% (4/5) |
| relational | 100% (2/2) | 100% (2/2) | 100% (2/2) | 0 | 100% (2/2) |
| set_algebra | 100% (5/5) | 100% (5/5) | 100% (5/5) | 0 | 100% (5/5) |
| ALL | 97% (29/30) | 97% (29/30) | 97% (29/30) | 1 | 96% (23/24) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 100% (27/27) | 0.47 s | 3.9 | 2.1 |
| 1 | 67% (2/3) | 0.11 s | 6.3 | 3.7 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| h028 | coastal districts of states bordering Kerala | None | low confidence for is_subquery (0.12) |

### Nested template pairs in the gold suite

| Outer | Inner | Count |
|---|---|---|
| children_with_predicate | neighbors | 1 |
| features_in | children_with_predicate | 1 |
| union | children_with_predicate | 1 |
