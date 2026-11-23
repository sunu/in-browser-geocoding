# Gold suite `india_ref`: provider `config`

Records: 200. Depth 0: 187. Depth 1 (two levels): 13.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 88% (170/194) | 87% (158/182) | 100% (12/12) | 1 | 0.99 |
| pick_template | 98% (190/194) | 98% (178/182) | 100% (12/12) | 2 | 1.00 |
| pick_template_flat | 89% (173/194) | 89% (162/182) | 92% (11/12) | 2 | 0.84 |
| pick_split | 98% (191/194) | 98% (179/182) | 100% (12/12) | 2 | 0.99 |
| is_subquery | 97% (183/188) | 97% (171/176) | 100% (12/12) | 0 | 0.97 |
| select_source | 100% (30/30) | 100% (30/30) | - | 0 | 0.71 |
| fill_closed_slot.admin_level | 100% (43/43) | 100% (40/40) | 100% (3/3) | 0 | 1.00 |
| fill_closed_slot.attr | 100% (9/9) | 100% (9/9) | - | 0 | 1.00 |
| fill_closed_slot.category | 100% (18/18) | 100% (18/18) | - | 0 | 1.00 |
| fill_closed_slot.direction | 100% (13/13) | 100% (13/13) | - | 0 | 1.00 |
| fill_closed_slot.op | 100% (9/9) | 100% (9/9) | - | 0 | 1.00 |
| fill_closed_slot.predicate | 100% (9/9) | 100% (7/7) | 100% (2/2) | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| r003 | is_subquery | 0 | true | false | 0.577546 |
| r009 | pick_template | 0 | parent | null | coverage miss |
| r009 | pick_template_flat | 0 | parent | null | coverage miss |
| r009 | pick_split | 0 | {"level": "district", "child": "Bodh Gaya"} | null | coverage miss |
| r014 | pick_family | 0 | set_algebra | hierarchy | 0.9897320000000001 |
| r014 | pick_template_flat | 0 | union | children | 0.0146980000000001 |
| r021 | pick_template_flat | 0 | parent | lookup_place | 0.131518 |
| r028 | is_subquery | 0 | true | false | 0.360982 |
| r029 | pick_family | 0 | hierarchy | features | 0.976596 |
| r029 | pick_template_flat | 0 | children | features_in | 0.14138800000000007 |
| r043 | pick_family | 0 | set_algebra | lookup | 0.9981564999999998 |
| r047 | pick_family | 0 | set_algebra | predicate_filter | 0.94963 |
| r049 | pick_family | 0 | hierarchy | features | 0.973614 |
| r057 | pick_family | 0 | modifier | lookup | 0.6642159999999999 |
| r059 | pick_family | 0 | set_algebra | relational | 0.9894240000000001 |
| r059 | pick_template_flat | 0 | union | between | 0.09048600000000007 |
| r067 | pick_family | 0 | set_algebra | hierarchy | 0.9794860000000001 |
| r067 | pick_template_flat | 0 | union | children | 0.29686999999999997 |
| r072 | pick_family | 0 | set_algebra | relational | 0.981052 |
| r075 | pick_family | 0 | set_algebra | hierarchy | 0.9933925 |
| r078 | pick_family | 0 | set_algebra | predicate_filter | 0.9438040000000001 |
| r081 | pick_family | 0 | set_algebra | hierarchy | 0.9905280000000001 |
| r081 | pick_template_flat | 0 | union | children | 0.52199 |
| r082 | pick_family | 0 | lookup | features | 0.972372 |
| r082 | pick_template_flat | 0 | lookup_place | natural_in | 0.1318220000000001 |
| r084 | pick_family | 0 | set_algebra | hierarchy | 0.9842139999999999 |
| r084 | pick_template_flat | 0 | union | children | 0.01774600000000004 |
| r087 | pick_template_flat | 0 | features_near | features_in | 0.33011199999999996 |
| r089 | pick_template_flat | 0 | parent | children | 0.5305759999999999 |
| r095 | is_subquery | 0 | true | false | 0.755956 |
| r096 | pick_family | 0 | lookup | features | 0.943122 |
| r101 | pick_family | 0 | set_algebra | hierarchy | 0.9904660000000001 |
| r109 | pick_family | 0 | lookup | features | 0.858382 |
| r111 | pick_template_flat | 0 | neighbors | children_touching | 0.49976599999999993 |
| r113 | pick_template_flat | 0 | union | intersection | 0.022629999999999928 |
| r114 | pick_family | 0 | set_algebra | lookup | 0.9938100000000001 |
| r114 | pick_template_flat | 0 | union | lookup_place | 0.54158 |
| r120 | pick_template_flat | 0 | lookup_place | direction_part | 0.44894999999999996 |
| r123 | pick_split | 0 | {"a": "Bangalore city", "b": "2 km around Majestic"} | {"a": "Bangalore", "b": "2 km around Majestic"} | 0.6950419999999999 |
| r123 | is_subquery | 0 | true | false | 0.769836 |
| r137 | pick_family | 0 | predicate_filter | hierarchy | 0.9810080000000001 |
| r144 | pick_family | 0 | modifier | null | coverage miss |
| r144 | pick_template | 0 | buffer | null | coverage miss |
| r144 | pick_template_flat | 0 | buffer | null | coverage miss |
| r144 | pick_split | 0 | {"distance": 15000, "target": "Jaipur airport"} | null | coverage miss |
| r157 | pick_family | 0 | modifier | lookup | 0.739512 |
| r157 | pick_template | 0 | centroid | direction_part | 0.9505284999999998 |
| r158 | pick_template_flat | 0 | parent | children | 0.34573600000000004 |
| r159 | is_subquery | 0 | true | false | 0.13202400000000003 |
| r159 | pick_template_flat | 1 | buffer | along_coast | 0.2876559999999999 |
| r166 | pick_family | 0 | relational | hierarchy | 0.9953379999999998 |
| r166 | pick_template_flat | 0 | between | union | 0.2878973333333333 |
| r176 | pick_template_flat | 0 | neighbors | children_touching | 0.78312 |
| r182 | pick_template | 0 | parent | children | 0.9729939999999999 |
| r182 | pick_template_flat | 0 | parent | children | 0.3421600000000001 |
| r188 | pick_family | 0 | predicate_filter | hierarchy | 0.9938899999999999 |
| r190 | pick_family | 0 | set_algebra | relational | 0.9855259999999999 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| attribute | 100% (9/9) | 100% (9/9) | 100% (9/9) | 0 | 100% (9/9) |
| features | 100% (18/18) | 100% (18/18) | 100% (18/18) | 0 | 100% (10/10) |
| hierarchy | 87% (20/23) | 87% (20/23) | 87% (20/23) | 0 | 88% (15/17) |
| lookup | 86% (6/7) | 86% (6/7) | 86% (6/7) | 0 | 100% (4/4) |
| modifier | 94% (34/36) | 94% (34/36) | 94% (34/36) | 0 | 96% (22/23) |
| predicate_filter | 100% (11/11) | 100% (11/11) | 100% (11/11) | 0 | 100% (11/11) |
| relational | 97% (36/37) | 97% (36/37) | 95% (35/37) | 0 | 94% (31/33) |
| set_algebra | 100% (41/41) | 98% (40/41) | 95% (39/41) | 0 | 97% (31/32) |
| unsupported | 89% (16/18) | 89% (16/18) | 89% (16/18) | 16 | 89% (16/18) |
| ALL | 96% (191/200) | 95% (190/200) | 94% (188/200) | 16 | 95% (149/157) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 94% (175/187) | 0.57 s | 4.9 | 1.4 |
| 1 | 100% (13/13) | 1.13 s | 9.2 | 2.6 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| r009 | disrtict of Bodh Gaya | children | template |
| r021 | Konark Sun Temple state | lookup_place | template |
| r073 | distrcts in Odisha with sex ratio above 950 | children_attr | DAG differs |
| r075 | pls show chennai madurai n coimbatore on map | union | places: expected list ['chennai', 'madurai', 'coimbatore'], got {'list': ['chennai madurai', 'coimbatore'], 'conj': '... |
| r104 | half a kilometre along the international border in Ferozepur | along_intl_border | DAG differs |
| r109 | banglore airport | features_in | template |
| r144 | 15 kms aroud Jaipur airport | features_near | template |
| r145 | districts of Bihar where literacy rate is below 60 | children_attr | DAG differs |
| r149 | Mumbai without Bandra | difference | DAG differs |
| r157 | i want to find the central location of Nashik district in Maharashtra | direction_part | template |
| r166 | btwn hyderabad and secunderabad | union | template |
| r182 | district of Lonavala | children | template |

### Nested template pairs in the gold suite

| Outer | Inner | Count |
|---|---|---|
| intersection | buffer | 5 |
| difference | children_with_predicate | 2 |
| intersection | along_intl_border | 1 |
| difference | children | 1 |
| difference | buffer | 1 |
| intersection | along_coast | 1 |
| intersection | along_border | 1 |
