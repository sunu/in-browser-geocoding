# Gold suite `world_heldout4`: provider `config`

Records: 21. Depth 0: 21. Depth 1 (two levels): 0.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 81% (17/21) | 81% (17/21) | - | 0 | 0.96 |
| pick_template | 95% (20/21) | 95% (20/21) | - | 0 | 1.00 |
| pick_template_flat | 76% (16/21) | 76% (16/21) | - | 0 | 0.49 |
| pick_split | 86% (18/21) | 86% (18/21) | - | 3 | 0.99 |
| is_subquery | 91% (10/11) | 91% (10/11) | - | 0 | 0.95 |
| select_source | 88% (14/16) | 88% (14/16) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 100% (3/3) | 100% (3/3) | - | 0 | 1.00 |
| fill_closed_slot.direction | 100% (1/1) | 100% (1/1) | - | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| n001 | pick_split | 0 | {"anchor": "Ganga river"} | null | coverage miss |
| n002 | pick_family | 0 | lookup | hierarchy | 0.8799600000000001 |
| n002 | pick_template_flat | 0 | lookup_place | children | 0.009538000000000046 |
| n003 | pick_family | 0 | lookup | hierarchy | 0.8405274999999998 |
| n004 | pick_split | 0 | {"level": "district", "parent": "Uttar Pradesh", "other": "Ganga ri... | null | coverage miss |
| n005 | select_source | 0 | overture | photon | 0.8 |
| n006 | select_source | 0 | overture | photon | 0.8 |
| n008 | pick_template | 0 | children_touching | children_with_predicate | 0.987816 |
| n008 | pick_template_flat | 0 | children_touching | children_with_predicate | 0.28917400000000004 |
| n008 | pick_split | 0 | {"level": "district", "parent": "India", "other": "Yamuna"} | null | coverage miss |
| n013 | pick_family | 0 | lookup | hierarchy | 0.84433 |
| n014 | is_subquery | 0 | false | true | 0.81192 |
| n016 | pick_template_flat | 0 | lookup_place | direction_part | 0.13874600000000004 |
| n017 | pick_template_flat | 0 | lookup_place | direction_part | 0.30604999999999993 |
| n018 | pick_family | 0 | lookup | hierarchy | 0.824714 |
| n018 | pick_template_flat | 0 | lookup_place | children | 0.03947400000000001 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| hierarchy | 50% (1/2) | 50% (1/2) | 50% (1/2) | 1 | 50% (1/2) |
| lookup | 77% (10/13) | 77% (10/13) | 77% (10/13) | 2 | 77% (10/13) |
| modifier | 100% (3/3) | 100% (3/3) | 100% (3/3) | 0 | 100% (3/3) |
| predicate_filter | 67% (2/3) | 33% (1/3) | 67% (2/3) | 0 | 67% (2/3) |
| ALL | 76% (16/21) | 71% (15/21) | 76% (16/21) | 3 | 76% (16/21) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 76% (16/21) | 1.49 s | 4.4 | 2.1 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| n001 | Ganga river | along_border | template |
| n008 | districts along the Yamuna | children_with_predicate | template |
| n013 | the Alps | None | the text 'Alps' names no known admin_level |
| n014 | districts in the Western Ghats | None | the text is not one place name, and no other template matches |
| n018 | the Andes | None | the text 'Andes' names no known admin_level |
