# Dataset ingest image.
#
# One-shot: fetches the versioned dataset from Zenodo, verifies each file's
# published MD5, writes a provenance manifest, and optionally uploads to GCS.
# Runs on every `docker compose up`, but re-downloading is skipped when the
# local checksums already match, so it is cheap after the first run.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY fetch_zenodo.py ./

# Defaults match docker-compose: write into the mounted data dir and upload
# to the emulator bucket. Override with `docker compose run --rm ingest ...`.
ENTRYPOINT ["python", "fetch_zenodo.py"]
CMD ["--out", "/data", "--bucket", "gpu-recsys"]
