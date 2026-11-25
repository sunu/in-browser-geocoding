# Gold suite `world_heldout`: provider `config`

Records: 29. Depth 0: 29. Depth 1 (two levels): 0.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 93% (27/29) | 93% (27/29) | - | 0 | 0.97 |
| pick_template | 100% (29/29) | 100% (29/29) | - | 0 | 1.00 |
| pick_template_flat | 90% (26/29) | 90% (26/29) | - | 0 | 0.82 |
| pick_split | 100% (29/29) | 100% (29/29) | - | 0 | 1.00 |
| is_subquery | 100% (24/24) | 100% (24/24) | - | 0 | 1.00 |
| select_source | 100% (8/8) | 100% (8/8) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 86% (12/14) | 86% (12/14) | - | 0 | 0.86 |
| fill_closed_slot.category | 100% (5/5) | 100% (5/5) | - | 0 | 1.00 |
| fill_closed_slot.predicate | 100% (2/2) | 100% (2/2) | - | 0 | 0.99 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| x004 | pick_family | 0 | hierarchy | features | 0.7949274999999998 |
| x011 | pick_template_flat | 0 | neighbors | children_touching | 0.33601400000000003 |
| x022 | pick_template_flat | 0 | neighbors | children_touching | 0.7030080000000001 |
| x024 | pick_family | 0 | hierarchy | features | 0.5147889999999999 |
| x024 | fill_closed_slot.admin_level | 0 | state | country | 0.04198360000000001 |
| x026 | fill_closed_slot.admin_level | 0 | state | country | 0.04198360000000001 |
| x028 | pick_template_flat | 0 | neighbors | children_touching | 0.40913 |

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
| 0 | 93% (27/29) | 1.67 s | 4.8 | 1.5 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| x024 | voivodeships of Poland | children | level: expected 'state', got None |
| x026 | coastal voivodeships of Poland | children_with_predicate | level: expected 'state', got None |
