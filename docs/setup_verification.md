# Environment setup verification

Recorded 2026-11-03 on the development machine (Windows 11, 10.0.26300).

## System tools

| Tool | Version / result |
|---|---|
| Node.js | v22.13.1 (already installed; no winget install needed) |
| Python | 3.11.18, conda env `medimg` |
| Docker | 29.6.2 (Docker Desktop) |
| NVIDIA GPU | None. `nvidia-smi` not found, so CPU-only PyTorch builds are used |
| Free disk on C: | 65.0 GB of 475.3 GB (before image pulls) |

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

`requirements.txt` pins these direct dependencies; transitive packages are
resolved by pip. A full pre-install snapshot of the env was saved locally
to `system_packages_backup.txt` (gitignored).

## Docker images

| Image | ID | Size |
|---|---|---|
| orthancteam/orthanc:latest | d2705f2c5654 | 2.63 GB |
| postgres:16 | 5db6dac2ef5d | 642 MB |

## DVC

- `dvc init` done; default remote `localstore` -> `C:\dev\dvc-store`.
- No data tracked yet.

## Issues encountered and how they were resolved

1. **kaggle import failed** with `ModuleNotFoundError: No module named 'six'`.
   kaggle 2.2.5 imports `six` but does not declare it. Fixed by installing
   `six==1.17.0` and pinning it in `requirements.txt`.
2. **Docker engine not running** at first pull
   (`failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`).
   Resolved by starting Docker Desktop manually, after which both pulls succeeded.
3. **Local tooling ignore rules** were moved from `.gitignore` to
   `.git/info/exclude`, which is not versioned. A fresh clone that uses
   those local files needs the rules re-added by hand.

## Needs attention

- **Kaggle credentials:** set the `KAGGLE_API_TOKEN` environment variable
  before downloading datasets. Not checked or configured during setup.
- **`.env`:** copy `.env.example` to `.env` and fill in the Postgres and
  Orthanc credentials before running the backend or containers.
- **DVC analytics:** DVC enabled anonymous usage analytics by default.
  Opt out with `dvc config core.analytics false` if preferred.
- **DVC remote path** is machine-specific. On another machine, override it
  with `dvc remote modify --local localstore url <path>`.
- **Line endings:** global `core.autocrlf=true` converts LF to CRLF on
  checkout; harmless, but a `.gitattributes` may be worth adding later.
