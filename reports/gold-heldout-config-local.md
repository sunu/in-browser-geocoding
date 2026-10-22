# Gold suite `heldout`: provider `config`

Records: 30. Depth 0: 27. Depth 1 (two levels): 3.

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
| 0 | 100% (27/27) | 0.45 s | 4.7 | 1.3 |
| 1 | 100% (3/3) | 1.24 s | 9.7 | 3.0 |

### Nested template pairs in the gold suite

| Outer | Inner | Count |
|---|---|---|
| children_with_predicate | neighbors | 1 |
| features_in | children_with_predicate | 1 |
| union | children_with_predicate | 1 |
