# Gold suite `world_heldout2`: provider `config`

Records: 34. Depth 0: 34. Depth 1 (two levels): 0.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 94% (32/34) | 94% (32/34) | - | 0 | 0.99 |
| pick_template | 100% (34/34) | 100% (34/34) | - | 0 | 1.00 |
| pick_template_flat | 97% (33/34) | 97% (33/34) | - | 0 | 0.77 |
| pick_split | 100% (34/34) | 100% (34/34) | - | 0 | 0.99 |
| is_subquery | 100% (27/27) | 100% (27/27) | - | 0 | 1.00 |
| select_source | 100% (9/9) | 100% (9/9) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 100% (20/20) | 100% (20/20) | - | 0 | 1.00 |
| fill_closed_slot.category | 100% (3/3) | 100% (3/3) | - | 0 | 1.00 |
| fill_closed_slot.predicate | 100% (2/2) | 100% (2/2) | - | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| y015 | pick_family | 0 | predicate_filter | features | 0.9600346666666667 |
| y015 | pick_template_flat | 0 | children_with_predicate | along_coast | 0.5556040000000001 |
| y034 | pick_family | 0 | hierarchy | features | 0.8445415 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| features | 100% (3/3) | 100% (3/3) | 100% (3/3) | 0 | 100% (3/3) |
| hierarchy | 100% (19/19) | 95% (18/19) | 95% (18/19) | 0 | 100% (19/19) |
| lookup | 100% (8/8) | 100% (8/8) | 100% (8/8) | 0 | 100% (8/8) |
| modifier | 100% (1/1) | 100% (1/1) | 100% (1/1) | 0 | 100% (1/1) |
| predicate_filter | 100% (2/2) | 100% (2/2) | 100% (2/2) | 0 | 100% (2/2) |
| set_algebra | 100% (1/1) | 100% (1/1) | 100% (1/1) | 0 | 100% (1/1) |
| ALL | 100% (34/34) | 97% (33/34) | 97% (33/34) | 0 | 100% (34/34) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 97% (33/34) | 1.45 s | 4.6 | 1.6 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| y028 | regions bordering Dodoma | neighbors | level: expected 'state', got 'none' |
