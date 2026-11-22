# Gold suite `world_heldout5`: provider `config`

Records: 24. Depth 0: 24. Depth 1 (two levels): 0.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 83% (20/24) | 83% (20/24) | - | 1 | 0.99 |
| pick_template | 96% (23/24) | 96% (23/24) | - | 1 | 1.00 |
| pick_template_flat | 83% (20/24) | 83% (20/24) | - | 1 | 0.90 |
| pick_split | 79% (19/24) | 79% (19/24) | - | 4 | 0.99 |
| is_subquery | 100% (21/21) | 100% (21/21) | - | 0 | 1.00 |
| select_source | 100% (3/3) | 100% (3/3) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 100% (14/14) | 100% (14/14) | - | 0 | 1.00 |
| fill_closed_slot.natural_kind | 100% (3/3) | 100% (3/3) | - | 0 | 1.00 |
| fill_closed_slot.predicate | 100% (5/5) | 100% (5/5) | - | 0 | 1.00 |
| fill_closed_slot.quantifier | 100% (2/2) | 100% (2/2) | - | 0 | 1.00 |
| fill_closed_slot.rank_order | 100% (3/3) | 100% (3/3) | - | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| v006 | pick_split | 0 | {"level": "district", "parent": "India", "distance": 30000, "other"... | null | coverage miss |
| v015 | pick_family | 0 | lookup | null | coverage miss |
| v015 | pick_template | 0 | lookup_place | null | coverage miss |
| v015 | pick_template_flat | 0 | lookup_place | null | coverage miss |
| v015 | pick_split | 0 | {"anchor": "Godavari river"} | null | coverage miss |
| v016 | pick_family | 0 | lookup | features | 0.9835314999999999 |
| v016 | pick_template_flat | 0 | lookup_place | children | 0.2288065 |
| v017 | pick_family | 0 | predicate_filter | hierarchy | 0.9903 |
| v017 | pick_split | 0 | {"level": "district", "parent": "India", "other": "Godavari"} | null | coverage miss |
| v018 | pick_split | 0 | {"level": "districts", "parent": "Aravalli range"} | {"level": "districts", "parent": "Aravalli"} | 0.9654280000000001 |
| v019 | pick_template_flat | 0 | neighbors | children_touching | 0.40611200000000003 |
| v022 | pick_family | 0 | lookup | hierarchy | 0.9561850000000001 |
| v022 | pick_template_flat | 0 | lookup_place | children | 0.576037 |
| v022 | pick_split | 0 | {"anchor": "Portland"} | null | coverage miss |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| attribute | 100% (3/3) | 100% (3/3) | 100% (3/3) | 0 | 100% (3/3) |
| features | 100% (3/3) | 100% (3/3) | 100% (3/3) | 0 | 100% (3/3) |
| hierarchy | 100% (4/4) | 75% (3/4) | 75% (3/4) | 0 | 75% (3/4) |
| lookup | 100% (3/3) | 100% (3/3) | 100% (3/3) | 0 | 100% (3/3) |
| predicate_filter | 100% (9/9) | 78% (7/9) | 100% (9/9) | 0 | 100% (9/9) |
| relational | 100% (2/2) | 100% (2/2) | 100% (2/2) | 0 | 100% (2/2) |
| ALL | 100% (24/24) | 88% (21/24) | 96% (23/24) | 0 | 96% (23/24) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 96% (23/24) | 0.93 s | 5.1 | 1.5 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| v018 | districts in the Aravalli range | children | parent: expected 'Aravalli range', got 'Aravalli' |
