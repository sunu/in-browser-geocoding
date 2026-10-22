# Gold suite `gold`: provider `config`

Records: 98. Depth 0: 85. Depth 1 (two levels): 13.

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
| set_algebra | 92% (11/12) | 92% (11/12) | 92% (11/12) | 1 | 92% (11/12) |
| ALL | 99% (97/98) | 99% (97/98) | 99% (97/98) | 1 | 99% (88/89) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 100% (85/85) | 0.52 s | 4.6 | 1.3 |
| 1 | 92% (12/13) | 1.21 s | 8.4 | 2.7 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| g053 | overlap of Bengaluru Urban and 10 km around Whitefield | None | low confidence for is_subquery (0.02) |

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
