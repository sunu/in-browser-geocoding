# Gold suite `world_heldout3`: provider `config`

Records: 19. Depth 0: 15. Depth 1 (two levels): 4.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 70% (16/23) | 74% (14/19) | 50% (2/4) | 4 | 0.99 |
| pick_template | 83% (19/23) | 79% (15/19) | 100% (4/4) | 4 | 1.00 |
| pick_template_flat | 74% (17/23) | 68% (13/19) | 100% (4/4) | 4 | 0.62 |
| pick_split | 48% (11/23) | 37% (7/19) | 100% (4/4) | 11 | 0.99 |
| is_subquery | 73% (8/11) | 57% (4/7) | 100% (4/4) | 0 | 0.97 |
| select_source | 100% (13/13) | 100% (13/13) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 100% (2/2) | 100% (2/2) | - | 0 | 1.00 |
| fill_closed_slot.category | 100% (3/3) | 100% (3/3) | - | 0 | 1.00 |
| fill_closed_slot.direction | 100% (4/4) | - | 100% (4/4) | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| z001 | pick_split | 0 | {"anchor": "Portland"} | null | coverage miss |
| z002 | pick_split | 0 | {"anchor": "Portland"} | null | coverage miss |
| z003 | pick_family | 0 | lookup | hierarchy | 0.9275844999999998 |
| z003 | pick_template_flat | 0 | lookup_place | children | 0.24384549999999997 |
| z003 | pick_split | 0 | {"anchor": "Cambridge"} | null | coverage miss |
| z004 | pick_family | 0 | lookup | null | coverage miss |
| z004 | pick_template | 0 | lookup_place | null | coverage miss |
| z004 | pick_template_flat | 0 | lookup_place | null | coverage miss |
| z004 | pick_split | 0 | {"anchor": "London"} | null | coverage miss |
| z005 | pick_split | 0 | {"anchor": "Perth"} | null | coverage miss |
| z006 | pick_family | 0 | lookup | null | coverage miss |
| z006 | pick_template | 0 | lookup_place | null | coverage miss |
| z006 | pick_template_flat | 0 | lookup_place | null | coverage miss |
| z006 | pick_split | 0 | {"anchor": "Hyderabad"} | null | coverage miss |
| z007 | pick_family | 0 | lookup | null | coverage miss |
| z007 | pick_template | 0 | lookup_place | null | coverage miss |
| z007 | pick_template_flat | 0 | lookup_place | null | coverage miss |
| z007 | pick_split | 0 | {"anchor": "Aurangabad"} | null | coverage miss |
| z008 | pick_split | 0 | {"anchor": "Victoria"} | null | coverage miss |
| z009 | pick_family | 0 | lookup | null | coverage miss |
| z009 | pick_template | 0 | lookup_place | null | coverage miss |
| z009 | pick_template_flat | 0 | lookup_place | null | coverage miss |
| z009 | pick_split | 0 | {"anchor": "Córdoba"} | null | coverage miss |
| z010 | pick_split | 0 | {"anchor": "Alexandria"} | null | coverage miss |
| z011 | pick_split | 0 | {"category": "schools", "region": "Cambridge"} | {"category": "schools", "region": "Cambridge, England"} | 0.944173 |
| z012 | pick_split | 0 | {"anchor": "Pittsburg"} | null | coverage miss |
| z013 | is_subquery | 0 | true | false | 0.989062 |
| z013 | pick_family | 1 | modifier | lookup | 0.996632 |
| z014 | is_subquery | 0 | true | false | 0.976228 |
| z015 | is_subquery | 0 | true | false | 0.97665 |
| z015 | pick_family | 1 | modifier | lookup | 0.97746 |
| z018 | pick_template_flat | 0 | lookup_place | direction_part | 0.4306690000000001 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| features | 100% (3/3) | 67% (2/3) | 100% (3/3) | 0 | 100% (3/3) |
| hierarchy | 100% (2/2) | 100% (2/2) | 100% (2/2) | 0 | 100% (2/2) |
| lookup | 100% (13/13) | 100% (13/13) | 85% (11/13) | 0 | 85% (11/13) |
| set_algebra | 100% (1/1) | 100% (1/1) | 100% (1/1) | 0 | 100% (1/1) |
| ALL | 100% (19/19) | 95% (18/19) | 89% (17/19) | 0 | 89% (17/19) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 87% (13/15) | 0.37 s | 2.0 | 1.2 |
| 1 | 100% (4/4) | 3.09 s | 8.2 | 2.8 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| z004 | London, Ontario | lookup_place | DAG differs |
| z010 | Alexandria, Virginia | lookup_place | DAG differs |

### Nested template pairs in the gold suite

| Outer | Inner | Count |
|---|---|---|
| children | direction_part | 2 |
| features_in | direction_part | 2 |
