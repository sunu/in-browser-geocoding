# Gold suite `world_heldout2`: provider `config`

Records: 34. Depth 0: 34. Depth 1 (two levels): 0.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 85% (29/34) | 85% (29/34) | - | 0 | 0.94 |
| pick_template | 100% (34/34) | 100% (34/34) | - | 0 | 1.00 |
| pick_template_flat | 94% (32/34) | 94% (32/34) | - | 0 | 0.75 |
| pick_split | 100% (34/34) | 100% (34/34) | - | 0 | 0.99 |
| is_subquery | 100% (27/27) | 100% (27/27) | - | 0 | 1.00 |
| select_source | 100% (9/9) | 100% (9/9) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 100% (21/21) | 100% (21/21) | - | 0 | 1.00 |
| fill_closed_slot.category | 100% (3/3) | 100% (3/3) | - | 0 | 1.00 |
| fill_closed_slot.predicate | 100% (2/2) | 100% (2/2) | - | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| y002 | pick_template_flat | 0 | neighbors | children_touching | 0.1510499999999999 |
| y008 | pick_template_flat | 0 | neighbors | children_touching | 0.13063200000000008 |
| y011 | pick_family | 0 | hierarchy | features | 0.5691579999999999 |
| y014 | pick_family | 0 | hierarchy | features | 0.33948549999999994 |
| y030 | pick_family | 0 | hierarchy | features | 0.8273394999999999 |
| y033 | pick_family | 0 | hierarchy | features | 0.8712500000000001 |
| y034 | pick_family | 0 | hierarchy | features | 0.626282 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| features | 100% (3/3) | 100% (3/3) | 100% (3/3) | 0 | 100% (3/3) |
| hierarchy | 100% (19/19) | 100% (19/19) | 100% (19/19) | 0 | 100% (19/19) |
| lookup | 100% (8/8) | 100% (8/8) | 100% (8/8) | 0 | 100% (8/8) |
| modifier | 100% (1/1) | 100% (1/1) | 100% (1/1) | 0 | 100% (1/1) |
| predicate_filter | 100% (2/2) | 100% (2/2) | 100% (2/2) | 0 | 100% (2/2) |
| set_algebra | 100% (1/1) | 100% (1/1) | 100% (1/1) | 0 | 100% (1/1) |
| ALL | 100% (34/34) | 100% (34/34) | 100% (34/34) | 0 | 100% (34/34) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 100% (34/34) | 1.40 s | 4.7 | 1.7 |
