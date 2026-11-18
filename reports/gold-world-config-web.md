# Gold suite `world`: provider `config`

Records: 70. Depth 0: 70. Depth 1 (two levels): 0.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 97% (68/70) | 97% (68/70) | - | 0 | 0.98 |
| pick_template | 100% (70/70) | 100% (70/70) | - | 0 | 1.00 |
| pick_template_flat | 96% (67/70) | 96% (67/70) | - | 0 | 0.93 |
| pick_split | 100% (70/70) | 100% (70/70) | - | 0 | 0.99 |
| is_subquery | 100% (59/59) | 100% (59/59) | - | 0 | 0.96 |
| select_source | 96% (22/23) | 96% (22/23) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 88% (28/32) | 88% (28/32) | - | 0 | 0.92 |
| fill_closed_slot.attr | 100% (1/1) | 100% (1/1) | - | 0 | 1.00 |
| fill_closed_slot.category | 100% (10/10) | 100% (10/10) | - | 0 | 1.00 |
| fill_closed_slot.direction | 100% (3/3) | 100% (3/3) | - | 0 | 1.00 |
| fill_closed_slot.op | 100% (1/1) | 100% (1/1) | - | 0 | 1.00 |
| fill_closed_slot.predicate | 100% (8/8) | 100% (8/8) | - | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| w002 | fill_closed_slot.admin_level | 0 | district | country | 0.999004 |
| w004 | fill_closed_slot.admin_level | 0 | district | country | 0.999004 |
| w009 | pick_template_flat | 0 | children | children_with_predicate | 0.03692800000000007 |
| w009 | fill_closed_slot.admin_level | 0 | district | country | 0.999004 |
| w012 | pick_family | 0 | modifier | lookup | 0.931656 |
| w016 | pick_family | 0 | hierarchy | features | 0.12614799999999993 |
| w016 | pick_template_flat | 0 | children | features_in | 0.0776920000000001 |
| w030 | select_source | 0 | overture | photon | 0.8 |
| w038 | fill_closed_slot.admin_level | 0 | state | none | 0.8778324999999999 |
| w064 | pick_template_flat | 0 | lookup_place | direction_part | 0.2110939999999999 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| attribute | 100% (1/1) | 100% (1/1) | 0% (0/1) | 0 | 0% (0/1) |
| features | 100% (10/10) | 100% (10/10) | 100% (10/10) | 0 | 100% (10/10) |
| hierarchy | 91% (21/23) | 78% (18/23) | 78% (18/23) | 2 | 78% (18/23) |
| lookup | 100% (16/16) | 100% (16/16) | 94% (15/16) | 0 | 94% (15/16) |
| modifier | 100% (7/7) | 100% (7/7) | 100% (7/7) | 0 | 100% (7/7) |
| predicate_filter | 88% (7/8) | 75% (6/8) | 75% (6/8) | 1 | 75% (6/8) |
| set_algebra | 100% (5/5) | 100% (5/5) | 100% (5/5) | 0 | 100% (5/5) |
| ALL | 96% (67/70) | 90% (63/70) | 87% (61/70) | 3 | 87% (61/70) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 87% (61/70) | 2.91 s | 4.5 | 1.2 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| w002 | counties of Nevada | children | level: expected 'district', got 'country' |
| w004 | coastal counties of Georgia | children_with_predicate | level: expected 'district', got 'country' |
| w009 | counties of Wales | children | level: expected 'district', got 'country' |
| w030 | Minas Gerais | lookup_place | DAG differs |
| w034 | cities in Minas Gerais with population over 1 million | children_attr | DAG differs |
| w038 | prefectures bordering Kyoto | neighbors | level: expected 'state', got 'none' |
| w040 | landlocked prefectures of Japan | None | no split of the text gives valid values for the slots of children_with_predicate |
| w052 | local government areas of Lagos | None | the text 'local government areas' names no known admin_level |
| w059 | municipalities of Yucatan | None | the text 'municipalities' names no known admin_level |
