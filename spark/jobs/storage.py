"""Bucket helpers shared by the publishing notebooks (02, 03, 06).

The emulator in docker-compose and real Cloud Storage behave the same way, so
the notebooks only need the bucket name (``MODEL_BUCKET``).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from google.api_core.exceptions import Conflict, NotFound
from google.cloud import storage


def model_bucket_name() -> str:
    """Bucket name used by the serving API (emulator or GCS)."""
    return os.environ.get('MODEL_BUCKET', 'gpu-recsys')


def get_bucket(name: str | None = None):
    """Return the bucket, creating it when the emulator starts empty."""
    client = storage.Client()
    bucket_name = name or model_bucket_name()
    try:
        return client.get_bucket(bucket_name)
    except NotFound:
        try:
            return client.create_bucket(bucket_name)
        except Conflict:
            return client.get_bucket(bucket_name)


def upload_file(bucket, blob_name: str, path: str | Path, content_type: str) -> None:
    bucket.blob(blob_name).upload_from_filename(str(path), content_type=content_type)


def upload_text(bucket, blob_name: str, text: str, content_type: str) -> None:
    bucket.blob(blob_name).upload_from_string(text, content_type=content_type)


def upload_json(bucket, blob_name: str, payload) -> None:
    upload_text(bucket, blob_name, json.dumps(payload, indent=2), 'application/json')
