# Gold suite: provider `rules`

Records: 98. Depth 0: 85. Depth 1 (two levels): 13.

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| attribute | 100% (11/11) | 100% (11/11) | 100% (11/11) | 0 | 100% (11/11) |
| features | 100% (12/12) | 100% (12/12) | 100% (12/12) | 0 | - |
| hierarchy | 93% (14/15) | 93% (14/15) | 93% (14/15) | 1 | 93% (14/15) |
| lookup | 91% (10/11) | 91% (10/11) | 91% (10/11) | 1 | 100% (8/8) |
| modifier | 93% (13/14) | 93% (13/14) | 93% (13/14) | 1 | 100% (11/11) |
| predicate_filter | 100% (12/12) | 100% (12/12) | 100% (12/12) | 0 | 100% (12/12) |
| relational | 100% (11/11) | 100% (11/11) | 100% (11/11) | 0 | 100% (11/11) |
| set_algebra | 100% (12/12) | 100% (12/12) | 100% (12/12) | 0 | 100% (12/12) |
| ALL | 97% (95/98) | 97% (95/98) | 97% (95/98) | 3 | 99% (79/80) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 98% (83/85) | 0.09 s | 3.8 | 2.2 |
| 1 | 92% (12/13) | 0.11 s | 7.8 | 5.2 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| g004 | MG Road, Bangalore | None | cannot resolve 'MG Road' in the local extract |
| g015 | 500m around Indiranagar metro station | None | cannot resolve 'Indiranagar metro' in the local extract |
| g090 | districts of states that border Goa | None | cannot resolve 'states' in the local extract |

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
