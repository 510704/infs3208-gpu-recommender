#!/usr/bin/env python3
"""Download the PC Game System Requirements dataset from Zenodo.

Why a script instead of a one-off download
------------------------------------------
The dataset is *versioned* on Zenodo, and every file's MD5 is published by the
archive. That buys two things a hand-downloaded CSV cannot:

  1. **Verifiability** -- each file is checksummed against the published digest,
     so "which version produced this result?" has a definitive answer.
  2. **Freshness** -- pointing at the concept DOI instead of a frozen record ID
     means new versions are picked up automatically. This is precisely the
     "velocity" justification the architecture rests on.

By default the script skips any file whose local MD5 already matches, so it is
cheap and offline-tolerant after the first run.

Usage
-----
    python fetch_zenodo.py                        # pinned version, skip matching files
    python fetch_zenodo.py --latest               # newest version of the concept record
    python fetch_zenodo.py --force                # re-download everything
    python fetch_zenodo.py --bucket gpu-recsys    # also upload into GCS / emulator

Endpoints used
--------------
    GET https://zenodo.org/api/records/{id}                       record metadata
    GET https://zenodo.org/api/records/{id}/versions/latest       newest version
    GET https://zenodo.org/api/records/{id}/files/{key}/content   file bytes
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("ingest")

API = "https://zenodo.org/api"

# Version record. The concept record (all versions) is 23162308 and the concept
# DOI is 10.5281/zenodo.23162308 -- use --latest to follow it.
DEFAULT_RECORD_ID = os.getenv("ZENODO_RECORD_ID", "23162309")

# The two files the pipeline actually needs. The record also ships README.md,
# CITATION.cff and a PNG chart; fetch everything unless --files is given.
DEFAULT_FILES = ["games.csv", "gpus.csv"]

# The Google Cloud client requires a scheme in STORAGE_EMULATOR_HOST. Setting it
# to "gcs:4443" makes the client request "gcs:4443/storage/v1/..." and fail with
# the opaque "No connection adapters were found" error, so normalise it once
# here rather than relying on every caller getting the format right.
_emulator = os.getenv("STORAGE_EMULATOR_HOST")
if _emulator and "://" not in _emulator:
    os.environ["STORAGE_EMULATOR_HOST"] = f"http://{_emulator}"
    log.info("normalised STORAGE_EMULATOR_HOST -> http://%s", _emulator)


# --------------------------------------------------------------------- helpers


def md5_of(path: Path, chunk_size: int = 1 << 20) -> str:
    """MD5 of a file, computed in chunks so large files do not exhaust memory.

    MD5 is used here purely to match the digest Zenodo publishes -- it is an
    integrity check against corruption, not a security control.
    """
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_record(session: requests.Session, record_id: str, latest: bool) -> dict[str, Any]:
    """Fetch the record metadata, optionally resolving to the newest version."""
    url = f"{API}/records/{record_id}/versions/latest" if latest else f"{API}/records/{record_id}"
    log.info("resolving %s", url)
    response = session.get(url, timeout=60)
    response.raise_for_status()
    return response.json()


def download_file(
    session: requests.Session,
    url: str,
    dest: Path,
    expected_md5: str,
    force: bool,
) -> str:
    """Download one file, verifying its checksum. Returns 'skipped' or 'downloaded'."""
    if dest.is_file() and not force:
        actual = md5_of(dest)
        if actual == expected_md5:
            log.info("  %-28s already present and verified", dest.name)
            return "skipped"
        log.warning("  %-28s checksum mismatch, re-downloading", dest.name)

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    with session.get(url, stream=True, timeout=300) as response:
        response.raise_for_status()
        with tmp.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 20):
                handle.write(chunk)

    actual = md5_of(tmp)
    if actual != expected_md5:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"checksum mismatch for {dest.name}: expected {expected_md5}, got {actual}"
        )

    tmp.replace(dest)
    log.info("  %-28s downloaded and verified (%s)", dest.name, expected_md5[:12])
    return "downloaded"


def ensure_bucket(client: Any, name: str) -> None:
    """Create the bucket if it does not exist. No-op against real GCS if it does."""
    from google.api_core.exceptions import Conflict, NotFound

    try:
        client.get_bucket(name)
    except NotFound:
        try:
            client.create_bucket(name)
            log.info("created bucket gs://%s", name)
        except Conflict:
            pass


# ------------------------------------------------------------------------ main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--record", default=DEFAULT_RECORD_ID, help="Zenodo version record ID")
    parser.add_argument("--latest", action="store_true", help="resolve the concept record to the newest version")
    parser.add_argument("--out", default="data", help="destination directory for the CSV files")
    parser.add_argument("--files", nargs="*", default=DEFAULT_FILES, help="file keys to fetch")
    parser.add_argument("--force", action="store_true", help="re-download even when the checksum already matches")
    parser.add_argument("--bucket", help="also upload files to this GCS bucket (honours STORAGE_EMULATOR_HOST)")
    args = parser.parse_args(argv)

    out_dir = Path(args.out).resolve()

    with requests.Session() as session:
        session.headers["User-Agent"] = "infs3208-project/1.0 (+dataset ingest)"

        try:
            record = resolve_record(session, args.record, args.latest)
        except requests.RequestException as exc:
            log.error("could not reach Zenodo: %s", exc)
            return 2

        metadata = record.get("metadata", {})
        log.info(
            "record %s  version=%s  published=%s  license=%s",
            record.get("id"),
            metadata.get("version"),
            metadata.get("publication_date"),
            metadata.get("license", {}).get("id"),
        )

        available = {entry["key"]: entry for entry in record.get("files", [])}
        missing = [key for key in args.files if key not in available]
        if missing:
            log.error("record does not contain: %s (available: %s)", missing, sorted(available))
            return 2

        # ------------------------------------------------------------- download
        manifest_files: list[dict[str, Any]] = []
        for key in args.files:
            entry = available[key]
            expected = entry["checksum"].removeprefix("md5:")
            dest = out_dir / entry["key"]
            url = entry["links"]["self"]

            status = download_file(session, url, dest, expected, args.force)
            manifest_files.append(
                {
                    "key": entry["key"],
                    "size": entry["size"],
                    "checksum": entry["checksum"],
                    "status": status,
                }
            )

    # ---------------------------------------------------------------- provenance
    manifest = {
        "source": "zenodo",
        "record_id": record.get("id"),
        "concept_recid": record.get("conceptrecid"),
        "doi": record.get("doi"),
        "concept_doi": record.get("conceptdoi"),
        "version": metadata.get("version"),
        "publication_date": metadata.get("publication_date"),
        "license": metadata.get("license", {}).get("id"),
        # The API leaves publisher unset on this record; it is published by Zenodo.
        "publisher": metadata.get("publisher") or "Zenodo",
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": manifest_files,
    }

    manifest_path = out_dir / "_provenance.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    log.info("wrote %s", manifest_path)

    # ------------------------------------------------------------------- upload
    if args.bucket:
        from google.cloud import storage

        client = storage.Client()
        ensure_bucket(client, args.bucket)
        for entry in manifest_files:
            path = out_dir / entry["key"]
            client.bucket(args.bucket).blob(f"raw/{entry['key']}").upload_from_filename(str(path))
            log.info("uploaded gs://%s/raw/%s", args.bucket, entry["key"])

        client.bucket(args.bucket).blob("raw/_provenance.json").upload_from_string(
            json.dumps(manifest, indent=2), content_type="application/json"
        )

    # ------------------------------------------------------------------ summary
    print()
    print(f"  version    {manifest['version']}")
    print(f"  doi        {manifest['doi']}")
    print(f"  license    {manifest['license']}")
    for entry in manifest_files:
        print(f"  {entry['status']:<11} {entry['key']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
