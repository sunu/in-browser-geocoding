# Gold suite `world_heldout7`: provider `config`

Records: 73. Depth 0: 61. Depth 1 (two levels): 12.

## Decisions alone (gold inputs)

| Decision | Accuracy | Depth 0 | Depth 1 | Coverage misses | Mean confidence |
|---|---|---|---|---|---|
| pick_family | 74% (57/77) | 73% (53/73) | 100% (4/4) | 1 | 0.99 |
| pick_template | 97% (75/77) | 97% (71/73) | 100% (4/4) | 1 | 1.00 |
| pick_template_flat | 70% (54/77) | 70% (51/73) | 75% (3/4) | 1 | 0.72 |
| pick_split | 87% (67/77) | 86% (63/73) | 100% (4/4) | 9 | 1.00 |
| is_subquery | 100% (37/37) | 100% (33/33) | 100% (4/4) | 0 | 0.95 |
| select_source | 100% (8/8) | 100% (8/8) | - | 0 | 0.80 |
| fill_closed_slot.admin_level | 100% (22/22) | 100% (21/21) | 100% (1/1) | 0 | 1.00 |
| fill_closed_slot.attr | 100% (1/1) | 100% (1/1) | - | 0 | 1.00 |
| fill_closed_slot.category | 100% (3/3) | 100% (3/3) | - | 0 | 1.00 |
| fill_closed_slot.direction | 50% (1/2) | 50% (1/2) | - | 0 | 0.51 |
| fill_closed_slot.predicate | 100% (4/4) | 100% (4/4) | - | 0 | 1.00 |
| fill_closed_slot.quantifier | 100% (1/1) | 100% (1/1) | - | 0 | 1.00 |
| fill_closed_slot.rank_order | 100% (2/2) | 100% (2/2) | - | 0 | 1.00 |

### Errors in decisions alone

| Gold id | Decision | Depth | Gold | Got | Confidence |
|---|---|---|---|---|---|
| t002 | pick_family | 0 | set_algebra | modifier | 0.97438 |
| t004 | pick_family | 0 | set_algebra | modifier | 0.980756 |
| t005 | pick_family | 0 | set_algebra | hierarchy | 0.9842875 |
| t005 | pick_template_flat | 0 | union | children | 0.204703 |
| t006 | pick_family | 0 | set_algebra | hierarchy | 0.9896039999999999 |
| t006 | pick_template_flat | 0 | union | children | 0.796996 |
| t009 | pick_family | 0 | set_algebra | hierarchy | 0.9877199999999999 |
| t009 | pick_template_flat | 0 | union | children | 0.07145000000000001 |
| t010 | pick_family | 0 | set_algebra | hierarchy | 0.987606 |
| t010 | pick_template_flat | 0 | union | children | 0.2529380000000001 |
| t011 | pick_family | 0 | set_algebra | hierarchy | 0.9841439999999999 |
| t011 | pick_template_flat | 0 | union | children | 0.0537939999999999 |
| t019 | pick_template_flat | 0 | children_with_predicate | union | 0.23109550000000004 |
| t020 | pick_template_flat | 0 | children_with_predicate | neighbors_with_predicate | 0.14866000000000001 |
| t025 | pick_family | 0 | set_algebra | hierarchy | 0.9863379999999999 |
| t025 | pick_template_flat | 0 | union | children | 0.916248 |
| t026 | pick_family | 0 | set_algebra | hierarchy | 0.982796 |
| t026 | pick_template_flat | 0 | union | children | 0.3467 |
| t028 | pick_family | 0 | set_algebra | modifier | 0.9944005 |
| t028 | pick_template_flat | 0 | union | shared_border | 0.22406 |
| t035 | pick_template_flat | 1 | children | parent | 0.03373399999999993 |
| t041 | pick_split | 0 | {"category": "hospital", "region": "Springfield"} | null | coverage miss |
| t042 | pick_family | 0 | lookup | features | 0.9588085000000001 |
| t042 | pick_template_flat | 0 | lookup_place | natural_in | 0.7065684999999999 |
| t042 | pick_split | 0 | {"anchor": "Salem"} | null | coverage miss |
| t043 | pick_split | 0 | {"distance": 10000, "target": "London"} | null | coverage miss |
| t044 | pick_split | 0 | {"category": "school", "region": "Union County"} | null | coverage miss |
| t046 | pick_template_flat | 0 | lookup_place | union | 0.7808289999999999 |
| t046 | pick_split | 0 | {"anchor": "Union County"} | null | coverage miss |
| t048 | pick_template_flat | 0 | lookup_place | direction_part | 0.23010549999999996 |
| t048 | pick_split | 0 | {"anchor": "Victoria"} | null | coverage miss |
| t049 | pick_family | 0 | lookup | hierarchy | 0.9781420000000001 |
| t049 | pick_template_flat | 0 | lookup_place | children | 0.18123849999999997 |
| t049 | pick_split | 0 | {"anchor": "New York"} | {"anchor": "New York state"} | 0.9864059999999999 |
| t054 | pick_template_flat | 0 | children_with_predicate | neighbors_with_predicate | 0.0436700000000001 |
| t056 | pick_template | 0 | features_in | features_near | 0.950618 |
| t056 | pick_template_flat | 0 | features_in | features_near | 0.315968 |
| t057 | pick_family | 0 | set_algebra | hierarchy | 0.9844 |
| t057 | pick_template_flat | 0 | union | lookup_place | 0.5132304999999999 |
| t058 | pick_family | 0 | set_algebra | hierarchy | 0.9807400000000001 |
| t058 | pick_template_flat | 0 | union | lookup_place | 0.06091900000000002 |
| t059 | pick_family | 0 | set_algebra | hierarchy | 0.9802854999999998 |
| t059 | pick_template_flat | 0 | union | children | 0.3245005 |
| t061 | pick_family | 0 | lookup | null | coverage miss |
| t061 | pick_template | 0 | lookup_place | null | coverage miss |
| t061 | pick_template_flat | 0 | lookup_place | null | coverage miss |
| t061 | pick_split | 0 | {"anchor": "Kerala"} | null | coverage miss |
| t064 | pick_family | 0 | set_algebra | hierarchy | 0.9721759999999999 |
| t064 | pick_template_flat | 0 | union | children | 0.274454 |
| t065 | pick_split | 0 | {"places": "France and Spain and Italy"} | null | coverage miss |
| t066 | pick_family | 0 | modifier | hierarchy | 0.9905934999999998 |
| t066 | fill_closed_slot.direction | 0 | north | southwest | 0.016235874999999993 |
| t067 | pick_family | 0 | modifier | hierarchy | 0.9871570000000001 |
| t068 | pick_split | 0 | {"anchor": "Richmond"} | null | coverage miss |
| t072 | pick_template_flat | 0 | children | parent | 0.02190000000000003 |
| t073 | pick_family | 0 | set_algebra | hierarchy | 0.9857659999999999 |

## Full pipeline

| Family | Template | Slots | DAG | Unsupported | Executed result |
|---|---|---|---|---|---|
| attribute | 100% (2/2) | 100% (2/2) | 50% (1/2) | 0 | 100% (2/2) |
| features | 60% (3/5) | 40% (2/5) | 40% (2/5) | 1 | 40% (2/5) |
| hierarchy | 100% (14/14) | 100% (14/14) | 93% (13/14) | 0 | 93% (13/14) |
| lookup | 88% (7/8) | 75% (6/8) | 75% (6/8) | 0 | 88% (7/8) |
| modifier | 50% (2/4) | 25% (1/4) | 25% (1/4) | 1 | 25% (1/4) |
| predicate_filter | 100% (4/4) | 100% (4/4) | 100% (4/4) | 0 | 100% (4/4) |
| relational | 100% (6/6) | 83% (5/6) | 83% (5/6) | 0 | 83% (5/6) |
| set_algebra | 97% (29/30) | 87% (26/30) | 87% (26/30) | 0 | 87% (26/30) |
| ALL | 92% (67/73) | 82% (60/73) | 79% (58/73) | 2 | 82% (60/73) |

### By depth

| Depth | DAG correct | Median latency | Mean model calls | Mean requests in sequence |
|---|---|---|---|---|
| 0 | 77% (47/61) | 1.21 s | 7.1 | 1.6 |
| 1 | 92% (11/12) | 1.57 s | 10.4 | 2.7 |

### Pipeline errors

| Gold id | Query | Got template | Problem |
|---|---|---|---|
| t003 | Rome or Milan or Naples | union | DAG differs |
| t012 | Jalisco, Sonora and Chihuahua | union | places: expected list ['Jalisco', 'Sonora', 'Chihuahua'], got {'list': ['Jalisco, Sonora', 'Chihuahua'], 'conj': 'and... |
| t021 | the 3 largest states of Brazil and Argentina | children_top | DAG differs |
| t043 | 10 km around London in Ontario | buffer | target: expected 'London', got 'London in Ontario' |
| t044 | schools in Union County in New Jersey | None | the text is not one place name, and no other template matches |
| t045 | hospitals in State College | features_in | DAG differs |
| t056 | schools near me in Pune | features_near | template |
| t061 | Kerala and Kerala | union | template |
| t063 | states of the United States and Mexico | children | DAG differs |
| t064 | districts of Kerala and Coimbatore | children | template |
| t065 | Frnace, Spain and Itlay | union | places[0]: expected 'France', got 'Frnace'; places[2]: expected 'Italy', got 'Itlay' |
| t066 | nortern Spain | lookup_place | template |
| t067 | areas souht of Lyon | None | no split of the text gives valid values for the slots of children_touching |
| t068 | Richmond, Virginia | lookup_place | DAG differs |
| t071 | border between France, Belgium and Luxembourg | shared_border | places: expected list ['France', 'Belgium', 'Luxembourg'], got {'list': ['France, Belgium', 'Luxembourg'], 'conj': 'a... |

### Nested template pairs in the gold suite

| Outer | Inner | Count |
|---|---|---|
| intersection | buffer | 2 |
| difference | buffer | 1 |
| difference | children | 1 |
