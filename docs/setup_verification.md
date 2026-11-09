# Environment setup verification

Initial setup recorded 2026-11-03 on the development machine (Windows 11, 10.0.26300).
Updated 2026-11-09 for the container stack, and verified from a fresh clone (below).

## System tools

| Tool | Version / result |
|---|---|
| Node.js | v22.13.1 (the pinned frontend packages need ^22.12, ^24 or >=26) |
| Python | 3.11.18, conda env `medimg` |
| Docker | 29.6.2 (Docker Desktop), Docker Compose v5.3.1 |
| Git | 2.43.0.windows.1 |
| NVIDIA GPU | None. `nvidia-smi` not found, so CPU-only PyTorch builds are used |
| Free disk on C: | 65.0 GB of 475.3 GB (before image pulls, 2026-11-03) |

## Python packages

Installed into the existing `medimg` env. torch and torchvision were
installed first, on their own, from `https://download.pytorch.org/whl/cpu`.
The rest were installed with `--upgrade-strategy only-if-needed` so the CPU
torch build was not replaced.

`python scripts/verify_env.py` result: **26/26 OK**, `torch.cuda.is_available() == False`.

| Package | Version | Package | Version |
|---|---|---|---|
| torch | 2.15.0+cpu | fastapi | 0.162.0 |
| torchvision | 0.29.2+cpu | uvicorn[standard] | 0.54.0 |
| monai | 1.6.1 | sqlalchemy | 2.1.6 |
| nibabel | 5.4.2 | psycopg2-binary | 2.9.13 |
| SimpleITK | 2.5.7 | python-multipart | 0.0.33 |
| pydicom | 3.0.2 | alembic | 1.20.1 |
| pylibjpeg | 2.1.0 | dvc | 3.67.1 |
| pylibjpeg-libjpeg | 2.5.0 | kaggle | 2.2.5 |
| python-gdcm | 3.2.6 | pytest | 9.2.0 |
| numpy | 2.4.6 | pytest-cov | 7.1.0 |
| pandas | 3.1.0 | ruff | 0.17.3 |
| scikit-learn | 1.9.1 | six | 1.17.0 |
| matplotlib | 3.11.2 | pyyaml | 6.0.3 |
| opencv-python-headless | 5.0.0.93 | grad-cam | 1.5.7 |

The root `requirements.txt` pins these direct dependencies (later additions:
httpx 0.28.1 and pydantic-settings 2.16.2); transitive packages are resolved by
pip. It is the full development environment. The backend image installs only
`backend/requirements.txt`, the runtime subset with the same pins, and
`tests/test_requirements.py` checks that the two cannot drift. A full pre-install
snapshot of the env was saved locally to `system_packages_backup.txt` (gitignored).

## Docker images

Base images are pinned by digest in `docker-compose.yml` and the Dockerfiles.

| Image | Pinned version | Size |
|---|---|---|
| orthancteam/orthanc@sha256:d2705f2c... | Orthanc 1.13.0 | 2.63 GB |
| postgres@sha256:5db6dac2... | Postgres 16.15 | 642 MB |
| python@sha256:07d48240... (backend base) | Python 3.11.18, Debian 13 slim | 189 MB |
| node@sha256:5ec23b7c... (frontend build stage) | Node 22.23.4 | 329 MB |
| nginxinc/nginx-unprivileged@sha256:f5116ed4... (frontend serve stage) | nginx 1.30.6 | 90.1 MB |
| radiology-backend:local (built) | backend/Dockerfile | 2.46 GB |
| radiology-frontend:local (built) | frontend/Dockerfile | 90.5 MB |

Postgres is published on host port 5433, because a natively installed
PostgreSQL 16 service holds 5432 on this machine. All ports are bound to
127.0.0.1.

## DVC

- Default remote `localstore` -> `C:\dev\dvc-store`, a folder on this machine.
  Another machine needs a copy of it and
  `dvc remote modify --local localstore url <path>`; CI has no access to it.
- Usage analytics disabled in the repository config (`core.analytics = false`).
- Tracked: the model checkpoint `models/densenet121_best.pt`, the RSNA sample and
  demo-negative DICOMs under `data/raw`, the demo study list
  `data/demo/test_studies.csv`, the processed demo negatives and the full-split
  manifest (about 120 MB in total). `python -m dvc pull` restores all of them.

## Issues encountered and how they were resolved

1. **kaggle import failed** with `ModuleNotFoundError: No module named 'six'`.
   kaggle 2.2.5 imports `six` but does not declare it. Fixed by installing
   `six==1.17.0` and pinning it in `requirements.txt`.
2. **Docker engine not running** at first pull
   (`failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`).
   Resolved by starting Docker Desktop manually, after which both pulls succeeded.
3. **Local tooling ignore rules** were moved from `.gitignore` to
   `.git/info/exclude`, which is not versioned. They cover only local tooling
   files that nothing in the project needs; the fresh-clone run below
   (where they do not exist) confirmed that the build, tests and stack work without
   them, and that `.gitignore` alone keeps data, weights, archives and `.env` out of
   git.
4. **A bare `dvc pull` (and `dvc push`) skipped the model weights.** Found in the
   fresh-clone run: `dvc pull` restored the data but not `models/densenet121_best.pt`,
   so the backend stayed unhealthy. Cause: the rule `/models/*` lets `*` match the
   empty name in DVC's ignore matcher (dulwich), so DVC treated the `models/` folder
   itself as ignored and never read its pointer file, while git did not. Changed to
   `/models/?*`, which git reads the same way; verified that DVC's index now
   includes the pointer, a bare `dvc pull` restores the weights, and git still
   ignores everything in `models/` except `*.dvc` files.
5. **Backend container could not import its own code** at the first
   `alembic upgrade head` (`ModuleNotFoundError: No module named 'backend'`): the
   `alembic` console script puts its own folder first on `sys.path`. Fixed with
   `PYTHONPATH=/app` in `backend/Dockerfile`.

## Fresh-clone verification (2026-11-09)

Cloned `main` from GitHub into a temporary folder outside the project and
followed only the root README Quick start. The development stack was stopped
(volumes kept) and the clone ran as a separate compose project with its own new
volumes and its own generated `.env` values, removed afterwards.

| Step | Result |
|---|---|
| Clone | No local tooling files present; `.git/info/exclude` empty |
| `python -m venv .venv` and `pip install -r requirements.txt` | Succeeded on Windows; torch 2.15.0+cpu |
| `.env` from `.env.example` | Left empty, `docker compose up` stopped with "required variable POSTGRES_PASSWORD is missing a value: set in .env" (the documented message) |
| `docker compose up -d --build` before `dvc pull` | Orthanc, Postgres and frontend healthy; backend unhealthy with the documented missing-checkpoint error in `/health` |
| `python -m dvc pull` | Restored data and, after issue 4 was fixed, the weights |
| `docker compose restart backend` | Healthy; migrations applied to the blank database |
| `python scripts/upload_demo_to_orthanc.py` | 80 found, 80 uploaded, 0 failed |
| http://localhost:5173 and http://127.0.0.1:8000/docs | Both 200 |
| `python scripts/smoke_stack.py` | 8 of 8 steps passed |
| `.gitignore` alone | Ignores `.env`, a zip, a DICOM under `data/raw`, a PNG under `data/processed`, a `.pt` and any other file in `models/`, and `frontend/.env.local` |

## Needs attention

- **`.env`:** copy `.env.example` to `.env` and fill in the Postgres and Orthanc
  credentials before running the backend or containers. `POSTGRES_PASSWORD` must be
  URL-safe because compose places it in a database URL; `VITE_API_BASE_URL` must
  use the same port as `API_PORT`.
- **Kaggle credentials:** set the `KAGGLE_API_TOKEN` environment variable only to
  download the dataset again.
- **DVC remote path** is machine-specific (see DVC above).
- **Line endings:** global `core.autocrlf=true` converts LF to CRLF on checkout;
  harmless, but a `.gitattributes` may be worth adding later.
