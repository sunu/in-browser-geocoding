# Accuracy outside India (plan-008, phase 7)

Date: 2026-11-17. Overture release `2026-10-21.0`.

## 1. Summary

The parse is correct for 61 of 70 world queries (87%). For the India sets, the parse is correct for 127 of 128 queries (99%). Of the 9 world errors:

- 6 are words for admin levels: "counties", "prefectures", "local government areas" and "municipalities".
- 2 are a wrong gazetteer match ("Minas Gerais").
- 1 is a Kyoto query where the gazetteer has no candidate for Kyoto Prefecture.

The templates, the splits, the categories and the predicates are correct for all world queries. Recommendation: do not retrain T5. Fix the admin level words and the gazetteer problems first (section 5). Then measure again.

## 2. Gold set

`gold/world_src.yaml` has 70 queries: 7 for each of 10 countries (US, GB, FR, DE, BR, JP, AU, NG, MX, ZA). It has place names, admin levels in local words, neighbors, predicates, hospitals and schools, set operations, buffers and directions. All queries have one level (depth 0).

Each record has the map view of its country. The build and the runs give this view to the gazetteer and to the executor. The gold anchor is the top gazetteer candidate with this view. One record has a fixed Overture id (`ids`), because the top candidate is not the correct place ("prefectures bordering Kyoto": Kyoto Prefecture, not Kyoto city). The expected results come from the gold DAG on the world data. They agree with the real geography (for example: 16 German states, 6 countries that border South Africa, 15 landlocked Mexican states).

Build: `GEOPARSE_SCOPE=world uv run python gold/build_gold.py --set world`.

## 3. Setup

The runs use the settings of the browser version (`--setup web`): T5 frames, no split patterns, no NER spans, the providers of the configuration (local cross-encoder and rules), no geocoder. The JS parse gives the same DAG as this Python parse (696 of 696 queries, fp32 models; 685 of 696 with the int8 models of the page).

```sh
GEOPARSE_SCOPE=world uv run python -m gold.run_gold --provider config --setup web --set world --execute
uv run python -m gold.run_gold --provider config --setup web --set gold --execute
uv run python -m gold.run_gold --provider config --setup web --set heldout --execute
```

Reports: `reports/gold-world-config-web.md`, `reports/gold-config-web.md`, `reports/gold-heldout-config-web.md`.

## 4. Results

### 4.1 Full pipeline

| Set | Queries | Template | DAG | Executed result | Median parse time |
|---|---|---|---|---|---|
| India gold | 98 | 99% | 99% (97) | 99% (88 of 89) | 0.61 s (depth 0) |
| India held-out | 30 | 100% | 100% (30) | 100% (27 of 27) | 0.47 s (depth 0) |
| World | 70 | 96% | 87% (61) | 87% (61 of 70) | 2.91 s |

The world parse time is longer, because the world database (6.9 GB) makes the gazetteer lookups slower in Python. The browser loads only the name shards and the countries that a query needs (see `world-data-report.md`).

Note: the parity check script (`gold_cmp.py`, used in phases 2 to 6) gave 115 of 128 for the India sets. That script compares JSON text, so a value of `1000000` is different from `1000000.0`. The gold runner compares canonical DAGs and gives 127 of 128. The regression checks of phases 2 to 6 compare the same script before and after each change, so their results stay valid.

### 4.2 Decisions alone (gold inputs)

| Decision | India gold | India held-out | World |
|---|---|---|---|
| pick_family | 99% | 97% | 97% (68/70) |
| pick_template | 100% | 100% | 100% (70/70) |
| pick_split | 100% | 100% | 100% (70/70) |
| is_subquery | 100% | 100% | 100% (59/59) |
| select_source | 100% | 100% | 96% (22/23) |
| fill_closed_slot.admin_level | 100% | 100% | 88% (28/32) |
| fill_closed_slot.category | 100% | 100% | 100% (10/10) |
| fill_closed_slot.predicate | 100% | 100% | 100% (8/8) |

### 4.3 World errors

| Id | Query | Problem | Cause |
|---|---|---|---|
| w002 | counties of Nevada | level `country`, not `district` | "counties" is a keyword of `district`, but the local model gives `country` (confidence 0.999) |
| w004 | coastal counties of Georgia | level `country` | same |
| w009 | counties of Wales | level `country` | same |
| w038 | prefectures bordering Kyoto | level `none`, and Kyoto city | "prefectures" is not a level word. The gazetteer has no candidate for Kyoto Prefecture ("Kyoto" finds the city and a county) |
| w040 | landlocked prefectures of Japan | unsupported | "prefectures" is not a level word |
| w052 | local government areas of Lagos | unsupported | "local government areas" is not a level word |
| w059 | municipalities of Yucatan | unsupported | in Mexico, municipalities are Overture counties; "municipalities" is a keyword of `city` |
| w030 | Minas Gerais | Photon, not the gazetteer | fuzzy match: "minas" is one edit from the street word "minar" |
| w034 | cities in Minas Gerais with population over 1 million | anchor from Photon, empty result | same |

"departments of Bretagne" (FR) and "provinces of South Africa" (ZA) are correct.

## 5. Recommendation

Do not retrain T5. The template and the split decisions are correct for all world queries. The errors are in the admin level vocabulary and in the gazetteer. Fix these first, in this order:

1. **Admin level words.** Add "prefecture", "local government area", "LGA" and "municipality" to the policy. A level word can mean a different Overture subtype in each country, for example "municipality" is `county` in MX and BR. Put these words in `policy.countries.<CC>`. When the text is an exact keyword of one level, use that level and do not ask the model. This fixes w002, w004, w009, w038, w040, w052 and w059 (7 of 9).
2. **Name suffixes.** "Kyoto" does not find Kyoto Prefecture (`京都府`). "Hokkaido", "Kano" and "Lagos" find their prefecture or state, so the names of these divisions have the short form. Find the prefectures and states with no short name, and add name keys without "Prefecture" (and other level words) at build time.
3. **Street words in the fuzzy match.** Do not give a fuzzy match to a street word ("minar") when the exact name is in the gazetteer ("Minas Gerais" is an exact region name). This fixes w030 and w034.
4. Then build the world gold set again and measure. Retrain the decision model (cross-encoder, on the GPU desktop) only if `fill_closed_slot.admin_level` stays below 95% after item 1.

Other findings from the world data (not in the gold errors):

- "Kyoto" ranks the city above the prefecture, also with the type hint `state`.
- With the NG view, "Lagos" ranks Laos (country) second.
- The gold set has 70 queries, so one error changes the accuracy by 1.4 points. Add more queries before the decision about retraining.
