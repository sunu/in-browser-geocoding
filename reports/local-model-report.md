# Report: local decision model replaces Jev (plan-006)

Date: 2026-10-22.

## 1. Summary

A local cross-encoder (MiniLM-L12, 33 M parameters, 129 MB fp32) now makes the language decisions. Rules (code and data) make `select_source`, `disambiguate`, and `bind_anchor`. No decision needs the network. Each decision can still use Jev: set it in `decisions.providers` in the config.

| Set | Jev | Local (default now) |
|---|---|---|
| LLM test, 294 queries: accuracy | 89.1 % | 91.2 % |
| LLM test: silent wrong answers | 6.8 % | 4.4 % |
| LLM dev, 279 queries: accuracy | 92.8 % | 92.1 % |
| LLM dev: silent wrong answers | 3.9 % | 4.7 % |
| Gold, 98 queries: correct DAG | 99 % | 99 % |
| Held-out, 30 queries: correct DAG | 100 % | 100 % |

In both columns, `select_source`, `disambiguate`, and `bind_anchor` use rules. The target was "within 2 points of Jev on the LLM test set, with no rise in silent wrong answers". The local model meets it.

Median parse time with the local model (no network): 0.5 s at depth 0, 1.2 s at depth 1, on the Mac CPU. With live Jev it was approximately 1.2 s at depth 0.

## 2. Scoring change

The LLM sets contain 14 (dev) and 22 (test) queries for levels or attributes that are not in the data (tehsils, wards, mandals, blocks, literacy rate). The correct outcome is `Unsupported`. The earlier metric compared only the template and the slot texts. It counted Jev's answers as correct when Jev mapped "tehsils" to "district", which gives a wrong result. The new metric expects `Unsupported` for these queries. The numbers in section 1 use the new metric. The earlier T5 report (87.8 % on the test set) used the old metric.

## 3. Training

- Data: `training/build_decisions.py`. 102,745 questions: synthetic and paraphrase queries with exact labels from the generator (option keys, sub-query slots, gold frames), T5 beams (8) for the frame-choice questions, and 1,130 Jev decisions from the logs. Questions from evaluation queries are excluded.
- Training: `training/remote/train_xenc.py` on the RTX 3090: 4 epochs, 12 minutes. A softmax over the options of each question; the target is the label or the Jev probabilities.
- Calibration: one temperature for each decision, fit on the validation split.

| Decision | Validation accuracy | ECE |
|---|---|---|
| fill_closed_slot (all types) | 96 to 100 % | under 0.02 |
| is_subquery | 97.4 % | 0.007 |
| pick_family | 97.8 % | 0.005 |
| pick_template | 98.0 % | 0.011 |
| pick_split | 97.0 % | 0.008 |
| All | 97.9 % | 0.004 |

The validation questions come from the same generator as the training data. The pipeline results in section 1 are the better measure.

## 4. Changes that mattered

1. **Rank order of options.** The frame options now go in the order of the T5 beam score, and the local model sees the rank. Before this change, local frame choice was worse than the T5 beam order (86.7 % against 90.3 % on dev). After: 91.4 %.
2. **Label fix.** "villages" had the label "none" (an unsupported level) from before the `village` level existed.
3. **Typo copies** of closed-slot words in the training data ("disctricts").
4. **More frame-choice examples:** 8 beams instead of 4.

## 5. Ablation on the LLM dev set (one decision local, Jev for the others, before the fixes in section 4)

| Local decision | Accuracy | Jev baseline |
|---|---|---|
| frame choice | 86.7 % (after fixes: 91.4 %) | 93.5 % |
| fill_closed_slot | 90.0 % (after fixes: 91.0 %) | 93.5 % |
| is_subquery | 92.8 % | 93.5 % |

## 6. Open items

1. The local model has few examples for `select_source`, `disambiguate`, and `bind_anchor`. They use rules now.
2. ONNX export (browser) is not done. The model is 129 MB fp32; int8 is expected at approximately 35 MB.
3. Thresholds were set for Jev. A threshold search on the dev set for the local model can reduce the low-confidence refusals (example: g053, `is_subquery` 0.02).
4. Latency: approximately half of the parse time is outside the models (gazetteer searches, threads). Not profiled yet.
