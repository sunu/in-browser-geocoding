# Gold suite `world_heldout`: provider `config`

Records: 29. Depth 0: 29. Depth 1 (two levels): 0.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 100% (29/29) | 100% (29/29) | - | 0 | 1.00 |
| pick_template | 100% (29/29) | 100% (29/29) | - | 0 | 1.00 |
| pick_template_flat | 97% (28/29) | 97% (28/29) | - | 0 | 0.94 |
| pick_split | 100% (29/29) | 100% (29/29) | - | 0 | 1.00 |
| is_subquery | 100% (24/24) | 100% (24/24) | - | 0 | 0.98 |
| select_source | 100% (8/8) | 100% (8/8) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 86% (12/14) | 86% (12/14) | - | 0 | 0.87 |
| fill_closed_slot.category | 100% (5/5) | 100% (5/5) | - | 0 | 1.00 |
| fill_closed_slot.predicate | 100% (2/2) | 100% (2/2) | - | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| x024 | pick_template_flat | 0 | children | children_with_predicate | 0.17239000000000004 |
| x024 | fill_closed_slot.admin_level | 0 | state | district | 0.08905480000000002 |
| x026 | fill_closed_slot.admin_level | 0 | state | district | 0.08905480000000002 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| features | 100% (5/5) | 100% (5/5) | 100% (5/5) | 0 | 100% (5/5) |
| hierarchy | 100% (12/12) | 92% (11/12) | 92% (11/12) | 0 | 100% (12/12) |
| lookup | 100% (7/7) | 100% (7/7) | 100% (7/7) | 0 | 100% (7/7) |
| modifier | 100% (1/1) | 100% (1/1) | 100% (1/1) | 0 | 100% (1/1) |
| predicate_filter | 100% (2/2) | 50% (1/2) | 50% (1/2) | 0 | 100% (2/2) |
| set_algebra | 100% (2/2) | 100% (2/2) | 100% (2/2) | 0 | 100% (2/2) |
| ALL | 100% (29/29) | 93% (27/29) | 93% (27/29) | 0 | 100% (29/29) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 93% (27/29) | 1.49 s | 4.5 | 1.2 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| x024 | voivodeships of Poland | children | level: expected 'state', got None |
| x026 | coastal voivodeships of Poland | children_with_predicate | level: expected 'state', got None |
