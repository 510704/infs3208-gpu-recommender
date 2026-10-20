#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Tear down everything scripts/deploy_gcp.sh created in your Google Cloud
# project, so nothing keeps costing money.
#
#   PROJECT=my-project BUCKET=my-gpu-rec-bucket bash scripts/teardown_gcp.sh
#
# Deletes, in order: the Kubernetes workloads, the GKE cluster, the Artifact
# Registry repo (with its images), the Cloud Storage bucket (with the trained
# artefacts) and the two Google service accounts.
# ---------------------------------------------------------------------------
set -euo pipefail

# Always run from the repository root, so relative paths below work.
cd "$(dirname "$0")/.."

# Shared configuration and helpers (.env handling, project fallback, friendly
# errors) live in one file so deploy and teardown never drift apart.
# shellcheck disable=SC1091
. scripts/_config.sh

load_dotenv
resolve_config
resolve_project
require_project_and_bucket

gcloud config set project "$PROJECT"

# Everything is `|| true` so a partially-deleted setup still cleans up the rest.
kubectl delete -k k8s/overlays/gke --ignore-not-found 2>/dev/null || true
gcloud container clusters delete "$CLUSTER" --zone "$ZONE" --quiet || true
gcloud artifacts repositories delete "$REPO" --location "$REGION" --quiet || true
gcloud storage rm -r "gs://$BUCKET" --quiet || true
for n in serving training; do
  gcloud iam service-accounts delete "gpu-recsys-${n}@${PROJECT}.iam.gserviceaccount.com" --quiet || true
done

# Print what is left so you can confirm the teardown worked.
echo "== remaining =="
gcloud container clusters list --format="value(name)"
gcloud artifacts repositories list --location "$REGION" --format="value(name)"
gcloud storage ls "gs://$BUCKET" 2>&1 | head -1
gcloud iam service-accounts list --format="value(email)" | grep gpu-recsys || echo "no gpu-recsys service accounts"