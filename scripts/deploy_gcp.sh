#!/usr/bin/env bash
# Deploy this repository to your own Google Cloud project.
#
#   PROJECT=my-project BUCKET=my-gpu-rec-bucket bash scripts/deploy_gcp.sh
#
# Everything is parameterised: the GKE overlay in k8s/overlays/gke is a copy of
# the author's environment and is re-rendered here with your project, bucket and
# Artifact Registry path before it is applied.
#
# Optional: REGION (default australia-southeast1), ZONE, CLUSTER, REPO,
# MACHINE_TYPE, DISK_SIZE, WITH_TRAINING=1 (also build the training image),
# RENDER_ONLY=1 (no cloud calls - print the rendered overlay and exit).
set -euo pipefail

cd "$(dirname "$0")/.."

# Personal settings live in the gitignored .env; explicit env vars still win.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

PROJECT="${PROJECT:-${GCP_PROJECT:-}}"
BUCKET="${BUCKET:-${GCP_BUCKET:-}}"
REGION="${REGION:-${GCP_REGION:-australia-southeast1}}"
ZONE="${ZONE:-${GCP_ZONE:-${REGION}-a}}"
CLUSTER="${CLUSTER:-${GKE_CLUSTER:-gpu-recsys}}"
REPO="${REPO:-${GCP_AR_REPO:-gpu-recsys}}"
MACHINE_TYPE="${MACHINE_TYPE:-${GKE_MACHINE_TYPE:-e2-standard-2}}"
DISK_SIZE="${DISK_SIZE:-${GKE_DISK_SIZE:-30}}"
NS=gpu-recsys
AR="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}"

[[ -n "$PROJECT" ]] || { echo "set GCP_PROJECT in .env (or PROJECT=...)"; exit 1; }
[[ -n "$BUCKET" ]] || { echo "set GCP_BUCKET in .env (or BUCKET=...)"; exit 1; }

render() {
  local root="$1"
  rm -rf "$root"
  mkdir -p "$root"
  cp -r k8s "$root/k8s"
  local out="$root/k8s/overlays/gke"
  # image registry -> $AR, BUCKET_NAME -> $BUCKET, PROJECT_ID -> $PROJECT
  sed -E -i \
    -e "s#(newName: ).*/(serving|frontend|training)\$#\1${AR}/\2#" \
    -e "s#BUCKET_NAME#${BUCKET}#g" \
    -e "s#PROJECT_ID#${PROJECT}#g" \
    "$out/kustomization.yaml" "$out/patch-serviceaccounts.yaml"
  echo "$out"
}

RENDERED="$(render "$(mktemp -d)")"

if [[ "${RENDER_ONLY:-0}" == "1" ]]; then
  echo "rendered overlay: $RENDERED"
  grep -n "newName:\|MODEL_BUCKET\|gcp-service-account" "$RENDERED/kustomization.yaml" "$RENDERED/patch-serviceaccounts.yaml"
  if command -v kubectl >/dev/null 2>&1; then kubectl kustomize "$RENDERED" >/dev/null && echo "kustomize build: OK"; fi
  exit 0
fi

echo "== project, APIs, registry, bucket =="
gcloud config set project "$PROJECT"
gcloud services enable container.googleapis.com artifactregistry.googleapis.com \
  storage.googleapis.com iam.googleapis.com cloudresourcemanager.googleapis.com
gcloud artifacts repositories describe "$REPO" --location "$REGION" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "$REPO" --repository-format=docker --location "$REGION"
gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1 \
  || gcloud storage buckets create "gs://$BUCKET" --location "$REGION" --uniform-bucket-level-access

echo "== images =="
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
docker build -t "$AR/serving:v1" serving
docker build -t "$AR/frontend:v1" frontend
docker push "$AR/serving:v1"
docker push "$AR/frontend:v1"
if [[ "${WITH_TRAINING:-0}" == "1" ]]; then
  docker build -f training/Dockerfile -t "$AR/training:v1" .
  docker push "$AR/training:v1"
fi

echo "== artifacts =="
gcloud storage cp -q data/curated/gpus_classified.csv "gs://$BUCKET/models/gpus_classified.csv"
gcloud storage cp -q data/curated/game_fps_model.csv "gs://$BUCKET/models/game_fps_model.csv"
gcloud storage cp -q data/curated/fps_curve.json "gs://$BUCKET/models/fps_curve.json"
gcloud storage cp -q data/curated/model_selection.json "gs://$BUCKET/models/model_selection.json"
gcloud storage cp -q data/curated/features.parquet/part-*.parquet "gs://$BUCKET/models/features/"
gcloud storage cp -q figures/*.png "gs://$BUCKET/models/figures/"
gcloud storage cp -q data/curated/figures_index.json "gs://$BUCKET/models/figures/index.json"
gcloud storage cp -q data/games.csv "gs://$BUCKET/raw/games.csv"
gcloud storage cp -q data/gpus.csv "gs://$BUCKET/raw/gpus.csv"
gcloud storage cp -q data/_provenance.json "gs://$BUCKET/raw/_provenance.json"

echo "== cluster =="
gcloud container clusters describe "$CLUSTER" --zone "$ZONE" >/dev/null 2>&1 \
  || gcloud container clusters create "$CLUSTER" --zone "$ZONE" --num-nodes 1 \
       --machine-type "$MACHINE_TYPE" --disk-size "$DISK_SIZE" --disk-type pd-standard \
       --workload-pool="${PROJECT}.svc.id.goog" --scopes=cloud-platform
gcloud container clusters get-credentials "$CLUSTER" --zone "$ZONE" --quiet

echo "== identity =="
for n in serving frontend training; do
  gcloud iam service-accounts describe "gpu-recsys-${n}@${PROJECT}.iam.gserviceaccount.com" >/dev/null 2>&1 \
    || gcloud iam service-accounts create "gpu-recsys-$n" --display-name="gpu-recsys $n"
  gcloud iam service-accounts add-iam-policy-binding "gpu-recsys-${n}@${PROJECT}.iam.gserviceaccount.com" \
    --role=roles/iam.workloadIdentityUser \
    --member="serviceAccount:${PROJECT}.svc.id.goog[${NS}/${n}]" --quiet >/dev/null
done
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:gpu-recsys-serving@${PROJECT}.iam.gserviceaccount.com" --role=roles/storage.objectViewer --quiet >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:gpu-recsys-frontend@${PROJECT}.iam.gserviceaccount.com" --role=roles/storage.objectViewer --quiet >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:gpu-recsys-training@${PROJECT}.iam.gserviceaccount.com" --role=roles/storage.objectAdmin --quiet >/dev/null

echo "== apply =="
kubectl apply -k "$RENDERED"
kubectl -n "$NS" rollout status deploy/serving --timeout=300s
kubectl -n "$NS" rollout status deploy/frontend --timeout=300s
kubectl -n "$NS" rollout restart deploy/serving >/dev/null   # reload after IAM propagation

IP=""
for _ in $(seq 1 60); do
  IP="$(kubectl -n "$NS" get svc frontend -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)"
  [[ -n "$IP" ]] && break
  sleep 5
done
echo
echo "Site:  http://${IP:-<pending>}"
echo "Check: curl http://${IP}/api/healthz"
echo "Stop:  PROJECT=$PROJECT BUCKET=$BUCKET bash scripts/teardown_gcp.sh"