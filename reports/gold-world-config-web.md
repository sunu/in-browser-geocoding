# Gold suite `world`: provider `config`

Records: 70. Depth 0: 70. Depth 1 (two levels): 0.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 94% (66/70) | 94% (66/70) | - | 0 | 0.98 |
| pick_template | 100% (70/70) | 100% (70/70) | - | 0 | 1.00 |
| pick_template_flat | 91% (64/70) | 91% (64/70) | - | 0 | 0.83 |
| pick_split | 99% (69/70) | 99% (69/70) | - | 0 | 0.99 |
| is_subquery | 100% (59/59) | 100% (59/59) | - | 0 | 1.00 |
| select_source | 100% (23/23) | 100% (23/23) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 100% (32/32) | 100% (32/32) | - | 0 | 1.00 |
| fill_closed_slot.attr | 100% (1/1) | 100% (1/1) | - | 0 | 1.00 |
| fill_closed_slot.category | 100% (10/10) | 100% (10/10) | - | 0 | 1.00 |
| fill_closed_slot.direction | 100% (3/3) | 100% (3/3) | - | 0 | 0.99 |
| fill_closed_slot.op | 100% (1/1) | 100% (1/1) | - | 0 | 0.98 |
| fill_closed_slot.predicate | 100% (8/8) | 100% (8/8) | - | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| w012 | pick_family | 0 | modifier | lookup | 0.912946 |
| w013 | pick_family | 0 | set_algebra | lookup | 0.967444 |
| w013 | pick_template_flat | 0 | union | lookup_place | 0.20996199999999998 |
| w013 | pick_split | 0 | {"a": "England", "b": "Wales"} | {"a": "England and Wales", "b": "England and Wales"} | 0.952874 |
| w016 | pick_family | 0 | hierarchy | features | 0.658642 |
| w031 | pick_template_flat | 0 | neighbors | children_touching | 0.0013000000000000789 |
| w038 | pick_family | 0 | hierarchy | features | 0.3378655 |
| w038 | pick_template_flat | 0 | neighbors | children_touching | 0.38313549999999996 |
| w051 | pick_template_flat | 0 | neighbors | children_touching | 0.502108 |
| w058 | pick_template_flat | 0 | neighbors | children_touching | 0.4746619999999999 |
| w066 | pick_template_flat | 0 | neighbors | children_touching | 0.5861940000000001 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| attribute | 100% (1/1) | 100% (1/1) | 100% (1/1) | 0 | 100% (1/1) |
| features | 100% (10/10) | 100% (10/10) | 100% (10/10) | 0 | 100% (10/10) |
| hierarchy | 100% (23/23) | 100% (23/23) | 100% (23/23) | 0 | 100% (23/23) |
| lookup | 100% (16/16) | 100% (16/16) | 100% (16/16) | 0 | 100% (16/16) |
| modifier | 100% (7/7) | 100% (7/7) | 100% (7/7) | 0 | 100% (7/7) |
| predicate_filter | 100% (8/8) | 100% (8/8) | 100% (8/8) | 0 | 100% (8/8) |
| set_algebra | 100% (5/5) | 80% (4/5) | 80% (4/5) | 0 | 100% (5/5) |
| ALL | 100% (70/70) | 99% (69/70) | 99% (69/70) | 0 | 100% (70/70) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 99% (69/70) | 1.63 s | 5.0 | 1.6 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| w013 | England and Wales | union | a: expected 'England', got {'list': ['England', 'Wales'], 'conj': 'and', 'quant': None}; b: expected 'Wales', got {'l... |
