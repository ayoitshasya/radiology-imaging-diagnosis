# Test results

**Educational use only. Not for clinical use.** The model metrics below describe a
classifier on one public dataset (RSNA Pneumonia Detection Challenge) and say nothing about
clinical performance.

## Summary

| Suite | Tests | Where it runs |
|---|---|---|
| Python (pytest) | 161 passed | locally, all 161 |
| Python in CI | 159 of 161 | GitHub Actions; 2 `needs_dvc` tests deselected |
| Frontend (Vitest) | 78 passed of 78 | locally and in CI |

## Python tests

| Item | Value |
|---|---|
| Date | 2026-11-09 23:08 (local time) |
| Command | `python -m pytest --cov=backend --cov=ml --cov=scripts --cov-report=term -p no:warnings` |
| Environment | Windows 11, Python 3.11.18 (conda env `medimg`), CPU only; Orthanc and Postgres running via `docker compose` |
| Result | 161 passed in 577.19s (0:09:37) |
| Coverage (statements) | 74% (1990 statements, 518 not run) |

No test was skipped. The database tests create and drop their own throwaway databases
(`radiology_test`, `radiology_test_api`) on the compose Postgres; without Postgres they
are skipped locally but fail in CI, so a CI run cannot pass without them. Orthanc is
replaced by an in-process fake in all API tests.

### What CI runs

CI collection (`python -m pytest -m "not needs_dvc" --collect-only -q`): 159/161 tests collected (2 deselected) in 13.47s.
The two deselected tests read data that only `dvc pull` restores, and the DVC storage is
not reachable from CI, so they run locally only (they ran in the result above):

- `tests/test_demo_studies.py::test_no_demo_study_is_in_full_train_or_val_split`: the
  leakage check that every demo study comes from the test split.
- `tests/test_classification.py::test_smoke_training_runs_end_to_end_on_sample`: one
  training epoch on the RSNA sample.

No test needs the real model weights.

### Coverage by file

```
Name                                                 Stmts   Miss  Cover
------------------------------------------------------------------------
backend\__init__.py                                      0      0   100%
backend\app\__init__.py                                  0      0   100%
backend\app\audit.py                                    10      0   100%
backend\app\db.py                                       15      1    93%
backend\app\deps.py                                     29      0   100%
backend\app\inference.py                                55      2    96%
backend\app\main.py                                     78      3    96%
backend\app\model_service.py                            47     22    53%
backend\app\models.py                                   43      0   100%
backend\app\orthanc.py                                  41      8    80%
backend\app\queries.py                                  27      0   100%
backend\app\routers\__init__.py                          0      0   100%
backend\app\routers\audit_log.py                        33      0   100%
backend\app\routers\reviews.py                          29      0   100%
backend\app\routers\studies.py                          91      0   100%
backend\app\schemas.py                                  90      0   100%
backend\app\settings.py                                 30      0   100%
backend\app\text.py                                     28      2    93%
backend\migrations\env.py                               20      1    95%
backend\migrations\versions\0001_initial_schema.py      25      4    84%
backend\migrations\versions\0002_studies.py             11      1    91%
backend\migrations\versions\0003_review_comment.py      15      3    80%
ml\__init__.py                                           0      0   100%
ml\classification\__init__.py                            0      0   100%
ml\classification\baselines.py                          51     30    41%
ml\classification\common.py                             65     14    78%
ml\classification\evaluate.py                          139     76    45%
ml\classification\train.py                             131     18    86%
ml\explainability\__init__.py                            0      0   100%
ml\explainability\gradcam.py                            67     18    73%
ml\explainability\validate_gradcam.py                  138     31    78%
ml\preprocessing\__init__.py                             0      0   100%
ml\preprocessing\build_dataset.py                      112     20    82%
ml\preprocessing\dataset.py                             35      2    94%
scripts\download_rsna_sample.py                         95     60    37%
scripts\export_openapi.py                               29     16    45%
scripts\reset_demo_state.py                             57     11    81%
scripts\select_demo_negatives.py                        84     59    30%
scripts\select_test_studies.py                          57     34    40%
scripts\smoke_stack.py                                  94      3    97%
scripts\upload_demo_to_orthanc.py                       93     53    43%
scripts\verify_env.py                                   26     26     0%
------------------------------------------------------------------------
TOTAL                                                 1990    518    74%
```

Lower-coverage files are mostly command-line entry points and code that needs external
resources not available in unit tests: the Kaggle download (`download_rsna_sample.py`,
`select_demo_negatives.py`), the Orthanc upload (`upload_demo_to_orthanc.py`), the CLI
parts of `evaluate.py`, `baselines.py`, `select_test_studies.py` and `export_openapi.py`,
and `verify_env.py`. Their core functions (sampling, split reproduction, anonymisation,
threshold choice, bootstrap, baselines, schema rendering and its staleness check) are
tested directly. `model_service.py` is partly covered because the tests inject a model
instead of loading the checkpoint; the real load was verified by `/health` on the running
stack and by the stack smoke test (`scripts/smoke_stack.py`, itself covered by its own
tests).

## Frontend tests

| Item | Value |
|---|---|
| Date | 2026-11-09 23:08 (local time) |
| Commands | `npm run typecheck` (clean), `npm test` (Vitest 78 tests in 8 files, jsdom, `fetch` mocked) |
| Result | 78 passed, 0 failed |

| File | Tests passed |
|---|---|
| `src/api/client.test.ts` | 7 |
| `src/api/types.test.ts` | 17 |
| `src/components/Banner.test.tsx` | 5 |
| `src/components/ReviewForm.test.tsx` | 10 |
| `src/pages/AuditPage.test.tsx` | 7 |
| `src/pages/StudyDetailPage.test.tsx` | 10 |
| `src/pages/StudyListPage.test.tsx` | 13 |
| `src/review/validation.test.ts` | 9 |

## Model results (from report files)

All values are copied exactly from the named files. They come from the Kaggle run on the
full RSNA training data (checkpoint metadata: git commit
`8ad146cf96708c33532278ba0f84838e2fcadef3-dirty`; the `-dirty` flag comes from the runner rewriting a
tracked report, not from code changes).

### Data and training

Source: `reports/preprocessing_summary_full.json`, `reports/training_log.json`

| Item | Value |
|---|---|
| Images (train / val / test) | 18678 / 4003 / 4003 |
| Split | by patient, stratified on label, seed 42 |
| Best epoch | 3 of 8 (early stopping: True) |
| Best validation AUROC | 0.87808 |
| pos_weight | 3.43869 |

### Classification on the test split

Source: `reports/classification_metrics.json`. Threshold 0.480127
chosen on the validation split by youden_j_on_validation (validation sensitivity
0.8104, specificity 0.7852)
and applied unchanged to test. 95% CIs from 1000 bootstrap
resamples, seed 42.

| Group | n | Positives | AUROC [95% CI] | Sensitivity | Specificity | Precision |
|---|---|---|---|---|---|---|
| overall | 4003 | 902 | 0.8847 [0.8725, 0.8963] | 0.8293 [0.8038, 0.8534] | 0.773 [0.7583, 0.7884] | 0.5152 [0.4882, 0.5412] |
| AP | 1833 | 710 | 0.8276 [0.8079, 0.8465] | 0.8972 [0.874, 0.9181] | 0.5111 [0.4824, 0.5388] | 0.5371 [0.5104, 0.5649] |
| PA | 2170 | 192 | 0.8675 [0.8412, 0.8933] | 0.5781 [0.5071, 0.6492] | 0.9216 [0.9099, 0.9339] | 0.4173 [0.3611, 0.4768] |

### Baselines on the same test split

Source: `reports/baselines.json` (test n = 4003, prevalence 0.2253)

| Baseline | Result |
|---|---|
| View only (score = train positive rate of the view: AP 0.3822, PA 0.0933) | AUROC 0.7125 [0.6959, 0.7273] |
| Majority class (predicts 0) | AUROC 0.5, accuracy 0.7747, sensitivity 0.0, specificity 1.0 |

The majority-class accuracy is shown only to illustrate why accuracy misleads on
imbalanced data.

### Grad-CAM localisation on the full test split

Source: `reports/gradcam_localisation.json`. Target layer `features.denseblock4`;
threshold 0.480127 (validation split (Youden J), from classification_metrics.json); 748
true positives scored out of 902 positives; mean box area fraction
0.14.

| Method | Mass in box [95% CI] | Pointing game [95% CI] |
|---|---|---|
| Trained model | 0.2632 [0.2518, 0.2745] | 0.377 [0.3422, 0.4118] |
| Random-init DenseNet121 | 0.1185 [0.1112, 0.1253] | 0.0749 [0.0561, 0.0936] |
| Uniform heatmap | 0.14 [0.1328, 0.1474] | 0.14 [0.1328, 0.1474] (expected value) |

Paired differences in mass in box:

| Comparison | Mean [95% CI] | Share of images where trained is higher |
|---|---|---|
| Trained minus uniform | 0.1232 [0.1179, 0.1282] | 0.9505 |
| Trained minus random-init | 0.1448 [0.1378, 0.1518] | 0.9559 |

## Known limitations

- View position is confounded with the label (see the per-view rows and the view-only
  baseline); it is measured here, not removed.
- Grad-CAM uses a 7x7 feature map, so heatmaps indicate regions, not lesion outlines.
- All results are from one public dataset and one train/validation/test split.
