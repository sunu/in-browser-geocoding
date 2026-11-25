# Gold suite `world_heldout4`: provider `config`

Records: 21. Depth 0: 21. Depth 1 (two levels): 0.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 76% (16/21) | 76% (16/21) | - | 1 | 0.99 |
| pick_template | 95% (20/21) | 95% (20/21) | - | 1 | 1.00 |
| pick_template_flat | 86% (18/21) | 86% (18/21) | - | 1 | 0.90 |
| pick_split | 90% (19/21) | 90% (19/21) | - | 2 | 0.97 |
| is_subquery | 91% (10/11) | 91% (10/11) | - | 0 | 0.97 |
| select_source | 88% (14/16) | 88% (14/16) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 100% (4/4) | 100% (4/4) | - | 0 | 1.00 |
| fill_closed_slot.direction | 100% (1/1) | 100% (1/1) | - | 0 | 0.99 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| n001 | pick_family | 0 | lookup | null | coverage miss |
| n001 | pick_template | 0 | lookup_place | null | coverage miss |
| n001 | pick_template_flat | 0 | lookup_place | null | coverage miss |
| n001 | pick_split | 0 | {"anchor": "Ganga river"} | null | coverage miss |
| n003 | pick_family | 0 | lookup | features | 0.9439360000000001 |
| n003 | pick_template_flat | 0 | lookup_place | natural_in | 0.35400600000000004 |
| n005 | pick_family | 0 | lookup | features | 0.934696 |
| n005 | select_source | 0 | overture | photon | 0.8 |
| n006 | select_source | 0 | overture | photon | 0.8 |
| n008 | pick_family | 0 | predicate_filter | hierarchy | 0.93293 |
| n008 | pick_split | 0 | {"level": "district", "parent": "India", "other": "Yamuna"} | null | coverage miss |
| n014 | is_subquery | 0 | false | true | 0.711856 |
| n016 | pick_family | 0 | lookup | features | 0.918452 |
| n016 | pick_template_flat | 0 | lookup_place | natural_in | 0.722788 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| hierarchy | 100% (2/2) | 100% (2/2) | 100% (2/2) | 0 | 100% (2/2) |
| lookup | 100% (13/13) | 100% (13/13) | 100% (13/13) | 0 | 100% (13/13) |
| modifier | 100% (3/3) | 100% (3/3) | 100% (3/3) | 0 | 100% (3/3) |
| predicate_filter | 100% (3/3) | 67% (2/3) | 100% (3/3) | 0 | 100% (3/3) |
| ALL | 100% (21/21) | 95% (20/21) | 100% (21/21) | 0 | 100% (21/21) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 100% (21/21) | 1.51 s | 3.6 | 1.6 |
