# Gold suite `gold`: provider `config`

Records: 98. Depth 0: 85. Depth 1 (two levels): 13.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 99% (110/111) | 99% (97/98) | 100% (13/13) | 0 | 1.00 |
| pick_template | 100% (111/111) | 100% (98/98) | 100% (13/13) | 0 | 1.00 |
| pick_template_flat | 94% (104/111) | 96% (94/98) | 77% (10/13) | 0 | 0.94 |
| pick_split | 99% (110/111) | 99% (97/98) | 100% (13/13) | 0 | 0.98 |
| is_subquery | 99% (113/114) | 99% (100/101) | 100% (13/13) | 0 | 0.97 |
| select_source | 100% (24/24) | 100% (24/24) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 100% (48/48) | 100% (37/37) | 100% (11/11) | 0 | 1.00 |
| fill_closed_slot.attr | 100% (11/11) | 100% (11/11) | - | 0 | 1.00 |
| fill_closed_slot.category | 100% (12/12) | 100% (12/12) | - | 0 | 1.00 |
| fill_closed_slot.direction | 100% (6/6) | 100% (6/6) | - | 0 | 0.99 |
| fill_closed_slot.op | 100% (11/11) | 100% (11/11) | - | 0 | 0.99 |
| fill_closed_slot.predicate | 100% (16/16) | 100% (10/10) | 100% (6/6) | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| g020 | pick_family | 0 | modifier | lookup | 0.9686380000000001 |
| g031 | pick_template_flat | 0 | neighbors | children_touching | 0.44536599999999993 |
| g053 | is_subquery | 0 | true | false | 0.639518 |
| g066 | pick_template_flat | 0 | features_in | features_near | 0.5080499999999999 |
| g088 | pick_split | 0 | {"a": "Kerala", "b": "coastal districts of Karnataka"} | {"a": "coastal districts of Karnataka", "b": "Kerala"} | 0.8043640000000001 |
| g090 | pick_template_flat | 1 | neighbors | children_touching | 0.9309620000000001 |
| g091 | pick_template_flat | 0 | children_with_predicate | neighbors_with_predicate | 0.02814199999999989 |
| g091 | pick_template_flat | 1 | neighbors | children_touching | 0.9309620000000001 |
| g092 | pick_template_flat | 0 | neighbors | children_with_predicate | 0.7798719999999999 |
| g096 | pick_template_flat | 1 | neighbors | children_touching | 0.661292 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| attribute | 100% (11/11) | 100% (11/11) | 100% (11/11) | 0 | 100% (11/11) |
| features | 100% (12/12) | 100% (12/12) | 100% (12/12) | 0 | 100% (9/9) |
| hierarchy | 100% (15/15) | 100% (15/15) | 100% (15/15) | 0 | 100% (15/15) |
| lookup | 100% (11/11) | 100% (11/11) | 100% (11/11) | 0 | 100% (8/8) |
| modifier | 100% (14/14) | 100% (14/14) | 100% (14/14) | 0 | 100% (11/11) |
| predicate_filter | 100% (12/12) | 100% (12/12) | 100% (12/12) | 0 | 100% (12/12) |
| relational | 100% (11/11) | 100% (11/11) | 100% (11/11) | 0 | 100% (11/11) |
| set_algebra | 100% (12/12) | 92% (11/12) | 92% (11/12) | 0 | 100% (12/12) |
| ALL | 100% (98/98) | 99% (97/98) | 99% (97/98) | 0 | 100% (89/89) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 100% (85/85) | 0.48 s | 4.7 | 1.4 |
| 1 | 92% (12/13) | 1.09 s | 9.5 | 3.6 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| g088 | Kerala and coastal districts of Karnataka | union | a: expected 'Kerala', got {'q': 'coastal districts of Karnataka', 't': 'children_with_predicate', 's': {'pred': 'coas... |

### Nested template pairs in the gold suite

| Outer | Inner | Count |
|---|---|---|
| intersection | buffer | 2 |
| features_near | children_with_predicate | 1 |
| features_in | children_with_predicate | 1 |
| buffer | children | 1 |
| union | children_with_predicate | 1 |
| difference | children_with_predicate | 1 |
| children | neighbors | 1 |
| children_with_predicate | neighbors | 1 |
| neighbors | children_with_predicate | 1 |
| children_attr | neighbors | 1 |
| between | children_with_predicate | 1 |
| direction_part | children | 1 |
