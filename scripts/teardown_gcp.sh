#!/usr/bin/env bash
# Remove everything scripts/deploy_gcp.sh created in your project.
#
#   PROJECT=my-project BUCKET=my-gpu-rec-bucket bash scripts/teardown_gcp.sh
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT}"
BUCKET="${BUCKET:?set BUCKET}"
REGION="${REGION:-australia-southeast1}"
ZONE="${ZONE:-${REGION}-a}"
CLUSTER="${CLUSTER:-gpu-recsys}"
REPO="${REPO:-gpu-recsys}"

cd "$(dirname "$0")/.."
gcloud config set project "$PROJECT"

kubectl delete -k k8s/overlays/gke --ignore-not-found 2>/dev/null || true
gcloud container clusters delete "$CLUSTER" --zone "$ZONE" --quiet || true
gcloud artifacts repositories delete "$REPO" --location "$REGION" --quiet || true
gcloud storage rm -r "gs://$BUCKET" --quiet || true
for n in serving frontend training; do
  gcloud iam service-accounts delete "gpu-recsys-${n}@${PROJECT}.iam.gserviceaccount.com" --quiet || true
done

echo "== remaining =="
gcloud container clusters list --format="value(name)"
gcloud artifacts repositories list --location "$REGION" --format="value(name)"
gcloud storage ls "gs://$BUCKET" 2>&1 | head -1
gcloud iam service-accounts list --format="value(email)" | grep gpu-recsys || echo "no gpu-recsys service accounts"