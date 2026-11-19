# Gold suite `gold`: provider `config`

Records: 98. Depth 0: 85. Depth 1 (two levels): 13.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 98% (109/111) | 98% (96/98) | 100% (13/13) | 0 | 1.00 |
| pick_template | 100% (111/111) | 100% (98/98) | 100% (13/13) | 0 | 0.99 |
| pick_template_flat | 90% (100/111) | 92% (90/98) | 77% (10/13) | 0 | 0.86 |
| pick_split | 100% (111/111) | 100% (98/98) | 100% (13/13) | 0 | 0.99 |
| is_subquery | 97% (111/114) | 97% (98/101) | 100% (13/13) | 0 | 0.93 |
| select_source | 100% (24/24) | 100% (24/24) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 100% (48/48) | 100% (37/37) | 100% (11/11) | 0 | 1.00 |
| fill_closed_slot.attr | 100% (11/11) | 100% (11/11) | - | 0 | 1.00 |
| fill_closed_slot.category | 100% (12/12) | 100% (12/12) | - | 0 | 1.00 |
| fill_closed_slot.direction | 100% (6/6) | 100% (6/6) | - | 0 | 1.00 |
| fill_closed_slot.op | 100% (11/11) | 100% (11/11) | - | 0 | 1.00 |
| fill_closed_slot.predicate | 100% (16/16) | 100% (10/10) | 100% (6/6) | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| g006 | pick_template_flat | 0 | lookup_place | union | 0.40619049999999995 |
| g010 | pick_template_flat | 0 | lookup_place | direction_part | 0.533676 |
| g020 | pick_family | 0 | modifier | lookup | 0.997722 |
| g053 | is_subquery | 0 | true | false | 0.118286 |
| g054 | is_subquery | 0 | true | false | 0.649678 |
| g066 | pick_template_flat | 0 | features_in | features_near | 0.7263820000000001 |
| g085 | pick_template_flat | 0 | features_near | features_in | 0.19387599999999994 |
| g088 | pick_family | 0 | set_algebra | predicate_filter | 0.9935020000000001 |
| g088 | pick_template_flat | 0 | union | children_with_predicate | 0.10705199999999992 |
| g089 | is_subquery | 0 | true | false | 0.07269999999999999 |
| g090 | pick_template_flat | 0 | children | children_touching | 0.917904 |
| g090 | pick_template_flat | 1 | neighbors | children_touching | 0.7674939999999999 |
| g091 | pick_template_flat | 0 | children_with_predicate | neighbors_with_predicate | 0.311134 |
| g091 | pick_template_flat | 1 | neighbors | children_touching | 0.7674939999999999 |
| g092 | pick_template_flat | 0 | neighbors | children_touching | 0.4860595 |
| g096 | pick_template_flat | 1 | neighbors | children_touching | 5.0000000000105516e-05 |

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
| set_algebra | 100% (12/12) | 100% (12/12) | 100% (12/12) | 0 | 100% (12/12) |
| ALL | 100% (98/98) | 100% (98/98) | 100% (98/98) | 0 | 100% (89/89) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 100% (85/85) | 5.94 s | 4.8 | 1.4 |
| 1 | 100% (13/13) | 7.71 s | 9.3 | 3.5 |

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
