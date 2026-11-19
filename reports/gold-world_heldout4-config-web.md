# Gold suite `world_heldout4`: provider `config`

Records: 21. Depth 0: 21. Depth 1 (two levels): 0.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 52% (11/21) | 52% (11/21) | - | 0 | 0.97 |
| pick_template | 100% (21/21) | 100% (21/21) | - | 0 | 1.00 |
| pick_template_flat | 62% (13/21) | 62% (13/21) | - | 0 | 0.70 |
| pick_split | 95% (20/21) | 95% (20/21) | - | 1 | 0.97 |
| is_subquery | 91% (10/11) | 91% (10/11) | - | 0 | 0.98 |
| select_source | 88% (14/16) | 88% (14/16) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 100% (4/4) | 100% (4/4) | - | 0 | 1.00 |
| fill_closed_slot.direction | 100% (1/1) | 100% (1/1) | - | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| n001 | pick_family | 0 | lookup | features | 0.9134574999999999 |
| n001 | pick_template_flat | 0 | lookup_place | natural_in | 0.2738665 |
| n002 | pick_family | 0 | lookup | hierarchy | 0.9765699999999999 |
| n002 | pick_template_flat | 0 | lookup_place | children | 0.25119800000000003 |
| n003 | pick_family | 0 | lookup | features | 0.9167000000000001 |
| n003 | pick_template_flat | 0 | lookup_place | natural_in | 0.49911799999999995 |
| n005 | pick_family | 0 | lookup | features | 0.90717 |
| n005 | select_source | 0 | overture | photon | 0.8 |
| n006 | select_source | 0 | overture | photon | 0.8 |
| n008 | pick_family | 0 | predicate_filter | hierarchy | 0.9754320000000001 |
| n008 | pick_split | 0 | {"level": "district", "parent": "India", "other": "Yamuna"} | null | coverage miss |
| n011 | pick_family | 0 | lookup | features | 0.913254 |
| n011 | pick_template_flat | 0 | lookup_place | natural_in | 0.3914679999999999 |
| n012 | pick_family | 0 | lookup | features | 0.8915420000000001 |
| n012 | pick_template_flat | 0 | lookup_place | natural_in | 0.0826579999999999 |
| n013 | pick_family | 0 | lookup | features | 0.948366 |
| n013 | pick_template_flat | 0 | lookup_place | natural_in | 0.5719700000000001 |
| n014 | is_subquery | 0 | false | true | 0.8810739999999999 |
| n016 | pick_family | 0 | lookup | features | 0.8904080000000001 |
| n016 | pick_template_flat | 0 | lookup_place | natural_in | 0.5591459999999999 |
| n018 | pick_family | 0 | lookup | features | 0.9501114999999998 |
| n018 | pick_template_flat | 0 | lookup_place | natural_in | 0.5676399999999999 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| hierarchy | 100% (2/2) | 100% (2/2) | 100% (2/2) | 0 | 100% (2/2) |
| lookup | 100% (13/13) | 100% (13/13) | 100% (13/13) | 0 | 100% (13/13) |
| modifier | 100% (3/3) | 100% (3/3) | 100% (3/3) | 0 | 100% (3/3) |
| predicate_filter | 67% (2/3) | 67% (2/3) | 67% (2/3) | 0 | 100% (3/3) |
| ALL | 95% (20/21) | 95% (20/21) | 95% (20/21) | 0 | 100% (21/21) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 95% (20/21) | 1.49 s | 3.9 | 1.7 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| n008 | districts along the Yamuna | neighbors | template |
