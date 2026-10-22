# Gold suite `heldout`: provider `local`

Records: 30. Depth 0: 27. Depth 1 (two levels): 3.

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| attribute | 100% (1/1) | 100% (1/1) | 100% (1/1) | 0 | 100% (1/1) |
| features | 100% (3/3) | 100% (3/3) | 67% (2/3) | 0 | 67% (2/3) |
| hierarchy | 100% (5/5) | 100% (5/5) | 100% (5/5) | 0 | 100% (5/5) |
| lookup | 75% (3/4) | 75% (3/4) | 50% (2/4) | 1 | 50% (1/2) |
| modifier | 80% (4/5) | 80% (4/5) | 60% (3/5) | 1 | 50% (2/4) |
| predicate_filter | 100% (5/5) | 100% (5/5) | 100% (5/5) | 0 | 100% (5/5) |
| relational | 100% (2/2) | 100% (2/2) | 100% (2/2) | 0 | 100% (2/2) |
| set_algebra | 100% (5/5) | 100% (5/5) | 100% (5/5) | 0 | 100% (5/5) |
| ALL | 93% (28/30) | 93% (28/30) | 83% (25/30) | 2 | 85% (23/27) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 81% (22/27) | 0.50 s | 4.7 | 1.3 |
| 1 | 100% (3/3) | 1.31 s | 9.7 | 3.0 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| h002 | Hyderabad | None | low confidence for disambiguate (0.02) |
| h003 | Qutub Minar | lookup_place | DAG differs |
| h005 | 3 km around Jayanagar | buffer | DAG differs |
| h008 | south of Hyderabad | None | low confidence for disambiguate (0.00) |
| h026 | pharmacies near Jayanagar | features_near | DAG differs |

### Nested template pairs in the gold suite

| Outer | Inner | Count |
|---|---|---|
| children_with_predicate | neighbors | 1 |
| features_in | children_with_predicate | 1 |
| union | children_with_predicate | 1 |
