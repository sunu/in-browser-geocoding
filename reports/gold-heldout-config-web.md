# Gold suite `heldout`: provider `config`

Records: 30. Depth 0: 27. Depth 1 (two levels): 3.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 94% (31/33) | 93% (28/30) | 100% (3/3) | 0 | 1.00 |
| pick_template | 100% (33/33) | 100% (30/30) | 100% (3/3) | 0 | 1.00 |
| pick_template_flat | 85% (28/33) | 87% (26/30) | 67% (2/3) | 0 | 0.87 |
| pick_split | 100% (33/33) | 100% (30/30) | 100% (3/3) | 0 | 0.98 |
| is_subquery | 100% (36/36) | 100% (33/33) | 100% (3/3) | 0 | 0.98 |
| select_source | 100% (9/9) | 100% (9/9) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 100% (14/14) | 100% (11/11) | 100% (3/3) | 0 | 1.00 |
| fill_closed_slot.attr | 100% (1/1) | 100% (1/1) | - | 0 | 1.00 |
| fill_closed_slot.category | 100% (3/3) | 100% (3/3) | - | 0 | 1.00 |
| fill_closed_slot.direction | 100% (2/2) | 100% (2/2) | - | 0 | 0.99 |
| fill_closed_slot.op | 100% (1/1) | 100% (1/1) | - | 0 | 0.98 |
| fill_closed_slot.predicate | 100% (6/6) | 100% (4/4) | 100% (2/2) | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| h013 | pick_template_flat | 0 | neighbors | children_touching | 0.7579819999999999 |
| h014 | pick_template_flat | 0 | neighbors | children_touching | 0.9035519999999999 |
| h018 | pick_family | 0 | predicate_filter | hierarchy | 0.9732620000000001 |
| h028 | pick_template_flat | 0 | children_with_predicate | neighbors_with_predicate | 0.11320200000000002 |
| h028 | pick_template_flat | 1 | neighbors | children_touching | 0.6711499999999999 |
| h030 | pick_family | 0 | set_algebra | predicate_filter | 0.979552 |
| h030 | pick_template_flat | 0 | union | children_with_predicate | 0.5307360000000001 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| attribute | 100% (1/1) | 100% (1/1) | 100% (1/1) | 0 | 100% (1/1) |
| features | 100% (3/3) | 100% (3/3) | 100% (3/3) | 0 | 100% (3/3) |
| hierarchy | 100% (5/5) | 100% (5/5) | 100% (5/5) | 0 | 100% (5/5) |
| lookup | 100% (4/4) | 100% (4/4) | 100% (4/4) | 0 | 100% (2/2) |
| modifier | 100% (5/5) | 100% (5/5) | 100% (5/5) | 0 | 100% (4/4) |
| predicate_filter | 100% (5/5) | 100% (5/5) | 100% (5/5) | 0 | 100% (5/5) |
| relational | 100% (2/2) | 100% (2/2) | 100% (2/2) | 0 | 100% (2/2) |
| set_algebra | 100% (5/5) | 100% (5/5) | 100% (5/5) | 0 | 100% (5/5) |
| ALL | 100% (30/30) | 100% (30/30) | 100% (30/30) | 0 | 100% (27/27) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 100% (27/27) | 0.41 s | 4.9 | 1.5 |
| 1 | 100% (3/3) | 1.12 s | 11.7 | 5.0 |

### Nested template pairs in the gold suite

| Outer | Inner | Count |
|---|---|---|
| children_with_predicate | neighbors | 1 |
| features_in | children_with_predicate | 1 |
| union | children_with_predicate | 1 |
