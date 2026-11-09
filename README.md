# Radiology imaging diagnosis (educational)

[![CI](https://github.com/ayoitshasya/radiology-imaging-diagnosis/actions/workflows/ci.yml/badge.svg)](https://github.com/ayoitshasya/radiology-imaging-diagnosis/actions/workflows/ci.yml)

A teaching system for AI-assisted chest X-ray review. A DenseNet121 classifier trained on
the RSNA Pneumonia Detection Challenge data scores each study for pneumonia opacity, and
Grad-CAM shows which regions influenced the score. Studies live in an Orthanc DICOM
server; a FastAPI backend runs the model, stores predictions, reviewer decisions and an
append-only audit log in Postgres; and a React viewer lets a reviewer see the scan, the
score next to its validation-chosen threshold, the Grad-CAM overlay, and approve or
reject the result. Final-year B.Tech IT internship project.

> **Educational use only. Not for clinical use.** This is not a medical device. Its
> output is not a diagnosis, and nothing here has been clinically validated or approved.
> Use only the public, anonymised demo data; never load real patient data.

## Quick start

What you need: Git, Docker Desktop (with Compose v2), Python 3.11, and about 8 GB of
free disk for the images and build cache. Everything else runs in containers.

1. **Clone and install the Python tools** (used for `dvc pull` and the upload script):

   ```
   git clone https://github.com/ayoitshasya/radiology-imaging-diagnosis.git
   cd radiology-imaging-diagnosis
   python -m venv .venv
   .venv\Scripts\activate            (macOS or Linux: source .venv/bin/activate)
   python -m pip install -r requirements.txt
   ```

2. **Restore the model weights and the demo data with DVC** (about 120 MB: the
   checkpoint, the demo DICOMs and their manifests):

   ```
   python -m dvc pull
   ```

   The DVC remote is a folder on the author's machine (`C:\dev\dvc-store`, set in
   `.dvc/config`). On any other machine, get a copy of that store first and point DVC
   at it without changing the committed config:

   ```
   python -m dvc remote modify --local localstore url <path to your copy>
   ```

3. **Create `.env`** from the template and fill in the empty values:

   ```
   copy .env.example .env             (macOS or Linux: cp .env.example .env)
   ```

   Set `POSTGRES_PASSWORD`, `ORTHANC_USERNAME` and `ORTHANC_PASSWORD`, and put the same
   Postgres password into `DATABASE_URL`. Use a URL-safe password (letters, digits,
   `-` or `_`): compose places it in a database URL. `KAGGLE_API_TOKEN` is only needed
   to download the dataset again. `.env` is git-ignored; never commit it.

4. **Start the stack** (Orthanc, Postgres, backend, viewer):

   ```
   docker compose up -d --build
   docker compose ps                  (wait until all four services are "healthy")
   ```

   The backend applies the database migrations on start.

5. **Upload the demo studies** to Orthanc (anonymised in memory, safe to re-run):

   ```
   python scripts/upload_demo_to_orthanc.py
   ```

6. **Open the viewer** at http://localhost:5173 (use exactly this address) and press
   **Sync from Orthanc**. The API is at http://127.0.0.1:8000 (`/health`, `/docs`).

7. Optional: check the whole stack end to end. This writes one prediction, one review
   signed "smoke test" and their audit events:

   ```
   python scripts/smoke_stack.py
   ```

All ports are bound to 127.0.0.1 only. Stop with `docker compose down`; the data stays
in Docker volumes. `docker compose down -v` also deletes the volumes (predictions,
reviews, audit log and the studies in Orthanc), which cannot be undone.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine` (or "Cannot connect to the Docker daemon") | Docker is not running. Start Docker Desktop, wait until it says the engine is running, and retry. |
| `Bind for 127.0.0.1:5433 failed: port is already allocated` (or 8000, 5173, 8042, 4242) | Another program uses the port. Postgres is on host port 5433 because a natively installed Postgres often holds 5432; change `POSTGRES_PORT` (and `DATABASE_URL`) in `.env` if 5433 is taken too. Port 8000 or 5173 is usually a host-run `uvicorn` or `npm run dev` from development: stop it, the containers use the same ports. Keep the viewer on 5173: the API's CORS setting allows only http://localhost:5173. |
| `required variable ... is missing a value: set in .env` | `.env` is missing or a value is empty. Copy `.env.example` and fill it in (step 3). |
| Backend stays "unhealthy"; `/health` shows `"model": {"ok": false, "error": "RuntimeError: Checkpoint models/densenet121_best.pt is missing ..."}` | The weights were not restored. Run `python -m dvc pull` on the host, then `docker compose restart backend`. Weights are never baked into the image; `./models` is mounted read-only. |
| `dvc pull` fails with a missing-cache or path error | The DVC remote path does not exist on this machine. See step 2. |
| Upload script reports `dicom_missing` above 0 | The demo DICOMs under `data/raw` were not restored. Run `python -m dvc pull`. |
| Backend or Postgres fails with `password authentication failed` | `POSTGRES_PASSWORD` was changed after the Postgres volume was first created; Postgres keeps the original. Restore the old value, or start over with `docker compose down -v` (deletes all stored data). |
| Viewer says "Cannot reach the API server" | The backend is not running or not yet healthy, or the page was opened from an address other than http://localhost:5173. |
| Viewer shows "Service unavailable" (503) | Orthanc is unreachable or the model failed to load; open http://127.0.0.1:8000/health to see which. |

More for the viewer: [frontend/README.md](frontend/README.md#troubleshooting).

## Results

Copied from the evaluation reports written by the scripts; see
[docs/test_results.md](docs/test_results.md) for the baselines and context. Values in
brackets are 95% bootstrap confidence intervals (1000 resamples). These are measurements
on a held-out split of a public dataset, not evidence of clinical performance.

**Classification** (`reports/classification_metrics.json`): test split, 4003 studies,
902 positive; decision threshold 0.480127 chosen on the validation split (Youden J).

| Metric | Value |
| --- | --- |
| AUROC | 0.8847 [0.8725, 0.8963] |
| Sensitivity at the threshold | 0.8293 [0.8038, 0.8534] |
| Specificity at the threshold | 0.773 [0.7583, 0.7884] |
| Precision at the threshold | 0.5152 [0.4882, 0.5412] |
| AUROC, AP-view studies only (1833) | 0.8276 [0.8079, 0.8465] |
| AUROC, PA-view studies only (2170) | 0.8675 [0.8412, 0.8933] |

**Grad-CAM localisation** (`reports/gradcam_localisation.json`): 748 true-positive test
studies with ground-truth boxes. Higher is better; a uniform heatmap scores the box's
share of the image.

| Heatmap | Share of heatmap mass inside the box | Pointing game (peak inside a box) |
| --- | --- | --- |
| Trained model | 0.2632 [0.2518, 0.2745] | 0.377 [0.3422, 0.4118] |
| Uniform (chance) | 0.14 [0.1328, 0.1474] | 0.14 [0.1328, 0.1474] |
| Random-init model | 0.1185 [0.1112, 0.1253] | 0.0749 [0.0561, 0.0936] |

## Testing

| Suite | Tests | Command |
| --- | --- | --- |
| Python (backend, ML pipeline, scripts) | 161 | `python -m pytest` (needs the compose Postgres for the database tests) |
| Frontend (Vitest, React Testing Library) | 78 | `cd frontend && npm test` |

GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs ruff, 159 of
the 161 Python tests against a Postgres service container, the frontend type check,
tests and build, and builds both Docker images without pushing them.

The other 2 tests carry the `needs_dvc` marker and run locally only, because they read
data that only `dvc pull` restores and the DVC storage is not reachable from CI:

- `test_demo_studies.py::test_no_demo_study_is_in_full_train_or_val_split`: the
  leakage check that every demo study comes from the test split, never from training or
  validation.
- `test_classification.py::test_smoke_training_runs_end_to_end_on_sample`: one training
  epoch end to end on the RSNA sample.

No test needs the real model weights. Locally the `needs_dvc` tests always run and fail
loudly if the data is missing. In CI a database that cannot be reached fails the
database tests instead of skipping them.

Test and coverage record: [docs/test_results.md](docs/test_results.md), recorded
2026-11-09: 161 Python tests passed with 74% statement coverage, and 78 frontend tests
passed.

## Documentation

- [docs/architecture.md](docs/architecture.md): system and sequence diagrams,
  components and design decisions.
- [docs/model_card.md](docs/model_card.md): intended use, data, training, results,
  Grad-CAM validation and limitations of the model.
- [frontend/README.md](frontend/README.md): running and developing the React viewer.
- [docs/api.md](docs/api.md): every API endpoint with real request and response
  examples; [docs/openapi.json](docs/openapi.json) is the exported schema.
- [docs/test_results.md](docs/test_results.md): test results, coverage and model metrics
  with their source reports.
- [docs/setup_verification.md](docs/setup_verification.md): how the environment was set
  up and verified, including a fresh-clone run.

## Known limitations

- **pandas and scikit-learn are installed in the backend image although inference never
  calls them.** The backend imports `preprocess_dicom` from
  `ml/preprocessing/build_dataset.py`, which imports both at module level for its
  dataset-building code. Moving that function to its own module would remove them.
- The backend image is 2.46 GB, mostly CPU-only PyTorch (814 MB).
- The DVC remote is a local folder, so a new machine needs a copy of it (Quick start,
  step 2), and CI cannot run the two `needs_dvc` tests.
- View position (AP or PA) is a confound: prevalence differs sharply between the two
  views, so part of the score can follow the view rather than the lungs. It is measured
  (a view-only baseline and per-view results are reported), not removed. See
  [docs/test_results.md](docs/test_results.md).
- Grad-CAM uses the last DenseNet block, a 7 by 7 feature map, so the heatmaps are
  coarse. They can also react to markers, borders and positioning.

## Repository layout

```
backend/     FastAPI app, Alembic migrations, Dockerfile, runtime requirements
frontend/    React + Vite + TypeScript viewer, Dockerfile, nginx config
ml/          preprocessing, training, evaluation and Grad-CAM code
scripts/     data download, demo selection, Orthanc upload, demo reset, smoke test
tests/       pytest suite
reports/     metrics and figures written by the scripts
docs/        API, test results and setup verification
deploy/      Orthanc configuration
```
