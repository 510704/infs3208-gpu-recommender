#!/usr/bin/env bash
# Remove everything scripts/deploy_gcp.sh created in your project.
#
#   PROJECT=my-project BUCKET=my-gpu-rec-bucket bash scripts/teardown_gcp.sh
set -euo pipefail

cd "$(dirname "$0")/.."

# Personal settings live in the gitignored .env; explicit env vars still win.
# tr -d '\r' so a .env edited on Windows (CRLF) still sources cleanly.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  . <(tr -d '\r' < .env)
  set +a
fi

PROJECT="${PROJECT:-${GCP_PROJECT:-}}"
BUCKET="${BUCKET:-${GCP_BUCKET:-}}"
REGION="${REGION:-${GCP_REGION:-australia-southeast1}}"
ZONE="${ZONE:-${GCP_ZONE:-${REGION}-a}}"
CLUSTER="${CLUSTER:-${GKE_CLUSTER:-gpu-recsys}}"
REPO="${REPO:-${GCP_AR_REPO:-gpu-recsys}}"

# No .env (a fresh clone has none - it is gitignored): fall back to the active
# gcloud project, and help find the bucket instead of just failing.
if [[ -z "$PROJECT" ]]; then
  PROJECT="$(gcloud config get-value project 2>/dev/null | tr -d '\r')"
  [[ -n "$PROJECT" && "$PROJECT" != "(unset)" ]] && echo "using the active gcloud project: $PROJECT"
fi
if [[ -z "$PROJECT" ]]; then
  echo "set GCP_PROJECT in .env, or run: PROJECT=<id> BUCKET=<bucket> bash scripts/teardown_gcp.sh"
  exit 1
fi
if [[ -z "$BUCKET" ]]; then
  echo "BUCKET is not set. Buckets in ${PROJECT}:"
  gcloud storage buckets list --project "$PROJECT" --format="value(name)" 2>/dev/null | sed 's/^/  /'
  echo
  echo "then run: PROJECT=${PROJECT} BUCKET=<bucket> bash scripts/teardown_gcp.sh"
  exit 1
fi

gcloud config set project "$PROJECT"

kubectl delete -k k8s/overlays/gke --ignore-not-found 2>/dev/null || true
gcloud container clusters delete "$CLUSTER" --zone "$ZONE" --quiet || true
gcloud artifacts repositories delete "$REPO" --location "$REGION" --quiet || true
gcloud storage rm -r "gs://$BUCKET" --quiet || true
for n in serving training; do
  gcloud iam service-accounts delete "gpu-recsys-${n}@${PROJECT}.iam.gserviceaccount.com" --quiet || true
done

echo "== remaining =="
gcloud container clusters list --format="value(name)"
gcloud artifacts repositories list --location "$REGION" --format="value(name)"
gcloud storage ls "gs://$BUCKET" 2>&1 | head -1
gcloud iam service-accounts list --format="value(email)" | grep gpu-recsys || echo "no gpu-recsys service accounts"