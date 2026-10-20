# Model-serving image.
#
# Deliberately minimal: no pandas, no PySpark. The trained model is exported to
# a small JSON artefact by the Spark/MLlib job and loaded at startup, so this
# image stays tens of megabytes instead of hundreds. That keeps the minikube
# and GKE image pulls fast.
#
# Build once, deploy anywhere:
#   docker compose build serving                    # local
#   docker compose up -d --build                    # local, emulator storage
#   docker push <region>-docker.pkg.dev/<project>/<repo>/serving:v1   # GKE

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy requirements first so the dependency layer caches across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./

# No data is baked in or mounted: the catalogue and the per-game curve are read
# from the bucket named by MODEL_BUCKET - the emulator in docker-compose, real
# Cloud Storage (Workload Identity) on GKE.

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/healthz').read()"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
