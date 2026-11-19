# Gold suite `world`: provider `config`

Records: 70. Depth 0: 70. Depth 1 (two levels): 0.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 97% (68/70) | 97% (68/70) | - | 0 | 0.98 |
| pick_template | 100% (70/70) | 100% (70/70) | - | 0 | 1.00 |
| pick_template_flat | 96% (67/70) | 96% (67/70) | - | 0 | 0.93 |
| pick_split | 100% (70/70) | 100% (70/70) | - | 0 | 0.99 |
| is_subquery | 100% (59/59) | 100% (59/59) | - | 0 | 0.96 |
| select_source | 100% (23/23) | 100% (23/23) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 100% (32/32) | 100% (32/32) | - | 0 | 1.00 |
| fill_closed_slot.attr | 100% (1/1) | 100% (1/1) | - | 0 | 1.00 |
| fill_closed_slot.category | 100% (10/10) | 100% (10/10) | - | 0 | 1.00 |
| fill_closed_slot.direction | 100% (3/3) | 100% (3/3) | - | 0 | 1.00 |
| fill_closed_slot.op | 100% (1/1) | 100% (1/1) | - | 0 | 1.00 |
| fill_closed_slot.predicate | 100% (8/8) | 100% (8/8) | - | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| w009 | pick_template_flat | 0 | children | children_with_predicate | 0.03692800000000007 |
| w012 | pick_family | 0 | modifier | lookup | 0.931656 |
| w016 | pick_family | 0 | hierarchy | features | 0.12614799999999993 |
| w016 | pick_template_flat | 0 | children | features_in | 0.0776920000000001 |
| w064 | pick_template_flat | 0 | lookup_place | direction_part | 0.2110939999999999 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| attribute | 100% (1/1) | 100% (1/1) | 100% (1/1) | 0 | 100% (1/1) |
| features | 100% (10/10) | 100% (10/10) | 100% (10/10) | 0 | 100% (10/10) |
| hierarchy | 100% (23/23) | 100% (23/23) | 100% (23/23) | 0 | 100% (23/23) |
| lookup | 100% (16/16) | 100% (16/16) | 100% (16/16) | 0 | 100% (16/16) |
| modifier | 100% (7/7) | 100% (7/7) | 100% (7/7) | 0 | 100% (7/7) |
| predicate_filter | 100% (8/8) | 100% (8/8) | 100% (8/8) | 0 | 100% (8/8) |
| set_algebra | 100% (5/5) | 100% (5/5) | 100% (5/5) | 0 | 100% (5/5) |
| ALL | 100% (70/70) | 100% (70/70) | 100% (70/70) | 0 | 100% (70/70) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 100% (70/70) | 3.02 s | 4.5 | 1.3 |
