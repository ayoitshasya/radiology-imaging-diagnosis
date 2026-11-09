# syntax=docker/dockerfile:1
# FastAPI backend image. Educational use only; not a medical device.
# Build from the repository root:  docker build -f backend/Dockerfile .
# The root .dockerignore whitelists the few paths copied below, so data, model weights,
# .env and .git never enter the build context.

# Python 3.11.18 on Debian 13 slim, pinned by digest so rebuilds use the same base.
FROM python@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# requirements.txt pins torch==2.15.0+cpu and torchvision==0.29.2+cpu and adds
# --extra-index-url https://download.pytorch.org/whl/cpu. On Linux the default PyPI torch
# is the CUDA build, which pulls several GB of NVIDIA libraries this CPU-only service
# never uses; the CPU index serves builds without them.
# Known limitation: requirements.txt is the project's single pinned environment, so the
# image also carries tools the API does not run (dvc, kaggle, pytest, ruff).
COPY requirements.txt .
RUN pip install -r requirements.txt

# Non-root user with a home directory (matplotlib and torch write small caches there).
RUN useradd --create-home --uid 10001 app

# Console scripts such as `alembic` put their own folder first on sys.path, not the working
# directory, so the project packages (backend, ml) must be on PYTHONPATH explicitly. Set
# after the pip layer so changing it does not reinstall the dependencies.
ENV PYTHONPATH=/app

COPY backend/ backend/
COPY ml/ ml/
COPY config.yaml .
# The decision threshold chosen on validation; the backend refuses to start without it.
COPY reports/classification_metrics.json reports/

# models/ is NOT copied: compose mounts ./models read-only at /app/models.
USER app
EXPOSE 8000

# /health is 200 only when Orthanc, the database and the model are all usable.
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
