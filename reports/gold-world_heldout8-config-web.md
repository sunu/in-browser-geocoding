# Gold suite `world_heldout8`: provider `config`

Records: 19. Depth 0: 19. Depth 1 (two levels): 0.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 100% (19/19) | 100% (19/19) | - | 0 | 1.00 |
| pick_template | 100% (19/19) | 100% (19/19) | - | 0 | 1.00 |
| pick_template_flat | 100% (19/19) | 100% (19/19) | - | 0 | 0.84 |
| pick_split | 100% (19/19) | 100% (19/19) | - | 0 | 1.00 |
| is_subquery | 100% (29/29) | 100% (29/29) | - | 0 | 1.00 |
| fill_closed_slot.admin_level | 100% (17/17) | 100% (17/17) | - | 0 | 1.00 |
| fill_closed_slot.attr | 100% (1/1) | 100% (1/1) | - | 0 | 1.00 |
| fill_closed_slot.op | 100% (1/1) | 100% (1/1) | - | 0 | 0.99 |
| fill_closed_slot.predicate | 100% (1/1) | 100% (1/1) | - | 0 | 1.00 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| attribute | 100% (1/1) | 100% (1/1) | 100% (1/1) | 0 | 100% (1/1) |
| hierarchy | 100% (3/3) | 100% (3/3) | 67% (2/3) | 0 | 67% (2/3) |
| lookup | 100% (2/2) | 100% (2/2) | 50% (1/2) | 0 | 50% (1/2) |
| predicate_filter | 100% (13/13) | 100% (13/13) | 31% (4/13) | 0 | 31% (4/13) |
| ALL | 100% (19/19) | 100% (19/19) | 42% (8/19) | 0 | 42% (8/19) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 42% (8/19) | 1.01 s | 5.8 | 1.3 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| s001 | Indian states bordering Nepal | children_touching | DAG differs |
| s002 | which Indian states border Bangladesh | children_touching | DAG differs |
| s003 | French regions | children | DAG differs |
| s004 | French departments bordering Spain | children_touching | DAG differs |
| s005 | Mexican states bordering Texas | children_touching | DAG differs |
| s006 | mexican states that touch texas | children_touching | DAG differs |
| s007 | Spanish provinces bordering Portugal | children_touching | DAG differs |
| s008 | Italian regions bordering Switzerland | children_touching | DAG differs |
| s009 | Canadian provinces bordering Montana | children_touching | DAG differs |
| s012 | American states bordering Canada | children_touching | DAG differs |
| s019 | French Guiana | lookup_place | DAG differs |
