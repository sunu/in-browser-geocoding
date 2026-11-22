# Gold suite `world_heldout6`: provider `config`

Records: 28. Depth 0: 28. Depth 1 (two levels): 0.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 96% (27/28) | 96% (27/28) | - | 0 | 0.99 |
| pick_template | 100% (28/28) | 100% (28/28) | - | 0 | 1.00 |
| pick_template_flat | 89% (25/28) | 89% (25/28) | - | 0 | 0.82 |
| pick_split | 96% (27/28) | 96% (27/28) | - | 0 | 0.99 |
| is_subquery | 100% (11/11) | 100% (11/11) | - | 0 | 1.00 |
| select_source | 100% (3/3) | 100% (3/3) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 100% (19/19) | 100% (19/19) | - | 0 | 1.00 |
| fill_closed_slot.category | 100% (2/2) | 100% (2/2) | - | 0 | 1.00 |
| fill_closed_slot.predicate | 100% (1/1) | 100% (1/1) | - | 0 | 1.00 |
| fill_closed_slot.quantifier | 100% (5/5) | 100% (5/5) | - | 0 | 1.00 |
| fill_closed_slot.rank_order | 100% (3/3) | 100% (3/3) | - | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| u002 | pick_template_flat | 0 | children | union | 0.04657800000000001 |
| u006 | pick_family | 0 | set_algebra | lookup | 0.967444 |
| u006 | pick_template_flat | 0 | union | lookup_place | 0.20996199999999998 |
| u006 | pick_split | 0 | {"a": "England", "b": "Wales"} | {"a": "England and Wales", "b": "England and Wales"} | 0.952874 |
| u013 | pick_template_flat | 0 | neighbors | union | 0.24130399999999996 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| attribute | 100% (3/3) | 100% (3/3) | 100% (3/3) | 0 | 100% (3/3) |
| features | 100% (2/2) | 100% (2/2) | 100% (2/2) | 0 | 100% (2/2) |
| hierarchy | 90% (9/10) | 90% (9/10) | 90% (9/10) | 0 | 90% (9/10) |
| lookup | 100% (3/3) | 100% (3/3) | 100% (3/3) | 0 | 100% (3/3) |
| modifier | 100% (1/1) | 100% (1/1) | 100% (1/1) | 0 | 100% (1/1) |
| predicate_filter | 100% (3/3) | 100% (3/3) | 100% (3/3) | 0 | 100% (3/3) |
| relational | 100% (3/3) | 100% (3/3) | 100% (3/3) | 0 | 100% (3/3) |
| set_algebra | 100% (3/3) | 67% (2/3) | 67% (2/3) | 0 | 100% (3/3) |
| ALL | 96% (27/28) | 93% (26/28) | 93% (26/28) | 0 | 96% (27/28) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 93% (26/28) | 1.66 s | 7.8 | 1.6 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| u002 | districts of Kerala and Goa | union | template |
| u006 | England and Wales | union | a: expected 'England', got {'list': ['England', 'Wales'], 'conj': 'and', 'quant': None}; b: expected 'Wales', got {'l... |
