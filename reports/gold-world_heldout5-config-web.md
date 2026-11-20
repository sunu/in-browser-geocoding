# Gold suite `world_heldout5`: provider `config`

Records: 24. Depth 0: 24. Depth 1 (two levels): 0.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 83% (20/24) | 83% (20/24) | - | 1 | 0.99 |
| pick_template | 96% (23/24) | 96% (23/24) | - | 1 | 1.00 |
| pick_template_flat | 92% (22/24) | 92% (22/24) | - | 1 | 0.86 |
| pick_split | 88% (21/24) | 88% (21/24) | - | 3 | 0.98 |
| is_subquery | 100% (29/29) | 100% (29/29) | - | 0 | 0.99 |
| select_source | 100% (3/3) | 100% (3/3) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 100% (14/14) | 100% (14/14) | - | 0 | 1.00 |
| fill_closed_slot.natural_kind | 100% (3/3) | 100% (3/3) | - | 0 | 1.00 |
| fill_closed_slot.predicate | 100% (5/5) | 100% (5/5) | - | 0 | 1.00 |
| fill_closed_slot.rank_order | 100% (3/3) | 100% (3/3) | - | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| v006 | pick_split | 0 | {"level": "district", "parent": "India", "distance": 30000, "other"... | null | coverage miss |
| v015 | pick_family | 0 | lookup | features | 0.8366180000000001 |
| v016 | pick_family | 0 | lookup | hierarchy | 0.9949859999999999 |
| v016 | pick_template_flat | 0 | lookup_place | children | 0.2839640000000001 |
| v017 | pick_family | 0 | predicate_filter | hierarchy | 0.9754879999999999 |
| v017 | pick_split | 0 | {"level": "district", "parent": "India", "other": "Godavari"} | null | coverage miss |
| v022 | pick_family | 0 | lookup | null | coverage miss |
| v022 | pick_template | 0 | lookup_place | null | coverage miss |
| v022 | pick_template_flat | 0 | lookup_place | null | coverage miss |
| v022 | pick_split | 0 | {"anchor": "Portland"} | null | coverage miss |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| attribute | 100% (3/3) | 100% (3/3) | 100% (3/3) | 0 | 100% (3/3) |
| features | 100% (3/3) | 100% (3/3) | 100% (3/3) | 0 | 100% (3/3) |
| hierarchy | 100% (4/4) | 100% (4/4) | 100% (4/4) | 0 | 100% (4/4) |
| lookup | 100% (3/3) | 100% (3/3) | 100% (3/3) | 0 | 100% (3/3) |
| predicate_filter | 89% (8/9) | 78% (7/9) | 89% (8/9) | 0 | 100% (9/9) |
| relational | 100% (2/2) | 50% (1/2) | 100% (2/2) | 0 | 100% (2/2) |
| ALL | 96% (23/24) | 88% (21/24) | 96% (23/24) | 0 | 100% (24/24) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 96% (23/24) | 1.23 s | 5.0 | 1.5 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| v017 | districts along the Godavari | neighbors | template |
