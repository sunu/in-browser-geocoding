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
| fill_closed_slot.admin_level | 57% (8/14) | 57% (8/14) | - | 0 | 0.85 |
| fill_closed_slot.category | 100% (5/5) | 100% (5/5) | - | 0 | 1.00 |
| fill_closed_slot.predicate | 100% (2/2) | 100% (2/2) | - | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| x005 | fill_closed_slot.admin_level | 0 | district | state | 1.0 |
| x013 | fill_closed_slot.admin_level | 0 | state | district | 1.0 |
| x022 | fill_closed_slot.admin_level | 0 | state | district | 0.7793950000000001 |
| x024 | pick_template_flat | 0 | children | children_with_predicate | 0.17239000000000004 |
| x024 | fill_closed_slot.admin_level | 0 | state | district | 0.08905480000000002 |
| x026 | fill_closed_slot.admin_level | 0 | state | district | 0.08905480000000002 |
| x028 | fill_closed_slot.admin_level | 0 | state | none | 0.9235191666666667 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| features | 100% (5/5) | 100% (5/5) | 100% (5/5) | 0 | 100% (5/5) |
| hierarchy | 92% (11/12) | 58% (7/12) | 58% (7/12) | 1 | 58% (7/12) |
| lookup | 100% (7/7) | 100% (7/7) | 100% (7/7) | 0 | 100% (7/7) |
| modifier | 100% (1/1) | 100% (1/1) | 100% (1/1) | 0 | 100% (1/1) |
| predicate_filter | 50% (1/2) | 50% (1/2) | 50% (1/2) | 1 | 50% (1/2) |
| set_algebra | 100% (2/2) | 100% (2/2) | 100% (2/2) | 0 | 100% (2/2) |
| ALL | 93% (27/29) | 79% (23/29) | 79% (23/29) | 2 | 79% (23/29) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 79% (23/29) | 3.23 s | 4.3 | 1.1 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| x005 | provinces of Tuscany | children | level: expected 'district', got 'state' |
| x013 | counties of Kenya | children | level: expected 'state', got 'district' |
| x022 | departments bordering Cundinamarca | neighbors | level: expected 'state', got 'district' |
| x024 | voivodeships of Poland | None | the text 'voivodeships' names no known admin_level |
| x026 | coastal voivodeships of Poland | None | no split of the text gives valid values for the slots of children_with_predicate |
| x028 | governorates bordering Cairo | neighbors | level: expected 'state', got 'none' |
