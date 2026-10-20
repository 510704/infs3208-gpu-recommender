#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Deploy the GPU recommender to your own Google Cloud project.
#
# One command does everything: credentials, container images, Cloud Storage,
# the GKE cluster and the app itself.
#
#   PROJECT=my-project BUCKET=my-gpu-rec-bucket bash scripts/deploy_gcp.sh
#
# Instead of editing the Kubernetes files, the GKE overlay in k8s/overlays/gke
# carries placeholders (PROJECT_ID, BUCKET_NAME) that this script fills in with
# your values before applying, so the same repo works for any project.
#
# Optional switches (set before the script name):
#   PROJECT, BUCKET      - required (or provided via .env, see below)
#   REGION, ZONE, CLUSTER, REPO, MACHINE_TYPE, DISK_SIZE
#   BUILD_MODE=cloudbuild - build the images inside Google Cloud instead of
#                           pushing them from this machine
#   WITH_TRAINING=1       - also build the retraining image
#   RENDER_ONLY=1         - just print the rendered overlay and stop
# ---------------------------------------------------------------------------
set -euo pipefail

# Always run from the repository root, so relative paths below work no matter
# where the script was invoked from.
cd "$(dirname "$0")/.."

# Shared configuration and helpers (.env handling, project fallback, friendly
# errors) live in one file so deploy and teardown never drift apart.
# shellcheck disable=SC1091
. scripts/_config.sh

load_dotenv
resolve_config
resolve_project

# Settings specific to the deploy (the sizes are the cost knobs).
MACHINE_TYPE="${MACHINE_TYPE:-${GKE_MACHINE_TYPE:-e2-standard-2}}"
DISK_SIZE="${DISK_SIZE:-${GKE_DISK_SIZE:-30}}"
BUILD_MODE="${BUILD_MODE:-local}"   # "local" (docker push) or "cloudbuild"
WITH_TRAINING="${WITH_TRAINING:-0}"
NS=gpu-recsys
AR="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}"

require_project_and_bucket

# -- helpers -----------------------------------------------------------------

# Is Artifact Registry reachable from this machine? 200/401/403 all mean yes.
registry_ok() {
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://${REGION}-docker.pkg.dev/v2/" 2>/dev/null || true)"
  [[ "$code" == "200" || "$code" == "401" || "$code" == "403" ]]
}

# Push an image, retrying with a pause - a transient "connection refused" (VPN,
# campus network) often clears on the second go.
push_image() {
  local ref="$1" attempt
  for attempt in 1 2 3 4 5; do
    if docker push "$ref"; then return 0; fi
    echo "  push failed (attempt ${attempt}/5): $ref"
    sleep $((attempt * 5))
  done
  echo "ERROR: could not push $ref (registry unreachable from this host)."
  echo "Fix: run in Cloud Shell, or: BUILD_MODE=cloudbuild bash scripts/deploy_gcp.sh"
  exit 1
}

# Copy the k8s tree to a private temporary folder and swap the placeholders for
# our real values, so the committed files stay generic.
render() {
  local root="$1"
  rm -rf "$root"; mkdir -p "$root"; cp -r k8s "$root/k8s"
  local out="$root/k8s/overlays/gke"
  sed -E -i \
    -e "s#(newName: ).*/(serving|frontend|training)\$#\1${AR}/\2#" \
    -e "s#BUCKET_NAME#${BUCKET}#g" \
    -e "s#PROJECT_ID#${PROJECT}#g" \
    "$out/kustomization.yaml" "$out/patch-serviceaccounts.yaml" "$out/patch-app-config.yaml"
  echo "$out"
}

RENDERED="$(render "$(mktemp -d)")"

# Show what WOULD be applied, then stop (cheap check of the rendered YAML).
if [[ "${RENDER_ONLY:-0}" == "1" ]]; then
  echo "rendered overlay: $RENDERED"
  grep -n "newName:\|MODEL_BUCKET\|gcp-service-account" "$RENDERED/kustomization.yaml" "$RENDERED/patch-serviceaccounts.yaml"
  command -v kubectl >/dev/null 2>&1 && kubectl kustomize "$RENDERED" >/dev/null && echo "kustomize build: OK"
  exit 0
fi

# -- 1. project scaffolding --------------------------------------------------
# Turn on the APIs, and create the registry repo + bucket if missing (safe to
# re-run).
echo "== project, APIs, registry, bucket =="
gcloud config set project "$PROJECT"
gcloud services enable container.googleapis.com artifactregistry.googleapis.com \
  storage.googleapis.com iam.googleapis.com cloudresourcemanager.googleapis.com
gcloud artifacts repositories describe "$REPO" --location "$REGION" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "$REPO" --repository-format=docker --location "$REGION"
gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1 \
  || gcloud storage buckets create "gs://$BUCKET" --location "$REGION" --uniform-bucket-level-access

# -- 2. container images -----------------------------------------------------
echo "== images =="
if [[ "$BUILD_MODE" == "cloudbuild" ]]; then
  # Let Cloud Build build and push (nothing leaves this machine, so a blocked or
  # flaky link to Artifact Registry cannot break the build).
  gcloud services enable cloudbuild.googleapis.com
  # Give Cloud Build's service account permission to write to the registry.
  NUM="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:${NUM}@cloudbuild.gserviceaccount.com" \
    --role=roles/artifactregistry.writer --quiet >/dev/null || true
  for image in serving frontend; do
    gcloud builds submit --tag "$AR/$image:v1" "$image"
  done
  [[ "$WITH_TRAINING" == "1" ]] && gcloud builds submit --tag "$AR/training:v1" -f training/Dockerfile .
else
  # Local path: build with Docker and push, warning up front if the registry
  # does not answer.
  gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
  if registry_ok; then
    echo "registry ${REGION}-docker.pkg.dev reachable"
  else
    echo "WARN: ${REGION}-docker.pkg.dev is not answering from this host."
    echo "      If the push fails, use BUILD_MODE=cloudbuild (no local push)."
  fi
  for image in serving frontend; do
    docker build -t "$AR/$image:v1" "$image"
    push_image "$AR/$image:v1"
  done
  if [[ "$WITH_TRAINING" == "1" ]]; then
    docker build -f training/Dockerfile -t "$AR/training:v1" .
    push_image "$AR/training:v1"
  fi
fi

# -- 3. trained artefacts ----------------------------------------------------
# Copy the pre-built model/catalogue/figures (committed under data/curated) into
# the bucket, where the serving API reads them at boot. Raw dataset files go
# into raw/ for the training job.
echo "== artifacts =="
for f in gpus_classified.csv game_fps_model.csv fps_curve.json model_selection.json; do
  gcloud storage cp -q "data/curated/$f" "gs://$BUCKET/models/$f"
done
gcloud storage cp -q data/curated/features.parquet/part-*.parquet "gs://$BUCKET/models/features/"
for f in figures/*.png; do
  gcloud storage cp -q "$f" "gs://$BUCKET/models/figures/${f##*/}"
done
gcloud storage cp -q data/curated/figures_index.json "gs://$BUCKET/models/figures/index.json"
for f in games.csv gpus.csv _provenance.json; do
  gcloud storage cp -q "data/$f" "gs://$BUCKET/raw/$f"
done

# -- 4. cluster --------------------------------------------------------------
# Create the cluster if it does not exist, then point kubectl at it.
echo "== cluster =="
gcloud container clusters describe "$CLUSTER" --zone "$ZONE" >/dev/null 2>&1 \
  || gcloud container clusters create "$CLUSTER" --zone "$ZONE" --num-nodes 1 \
       --machine-type "$MACHINE_TYPE" --disk-size "$DISK_SIZE" --disk-type pd-standard \
       --workload-pool="${PROJECT}.svc.id.goog" --scopes=cloud-platform
gcloud container clusters get-credentials "$CLUSTER" --zone "$ZONE" --quiet

# -- 5. permissions (Workload Identity) ---------------------------------------
# Give the pods Google credentials without secret keys. Only serving (reads the
# bucket) and training (writes) need an identity; the frontend is a static proxy.
echo "== identity =="
for n in serving training; do
  gcloud iam service-accounts describe "gpu-recsys-${n}@${PROJECT}.iam.gserviceaccount.com" >/dev/null 2>&1 \
    || gcloud iam service-accounts create "gpu-recsys-$n" --display-name="gpu-recsys $n"
  gcloud iam service-accounts add-iam-policy-binding "gpu-recsys-${n}@${PROJECT}.iam.gserviceaccount.com" \
    --role=roles/iam.workloadIdentityUser \
    --member="serviceAccount:${PROJECT}.svc.id.goog[${NS}/${n}]" --quiet >/dev/null
done
for pair in serving:objectViewer training:objectAdmin; do
  sa=${pair%%:*}; role=${pair##*:}
  gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
    --member="serviceAccount:gpu-recsys-${sa}@${PROJECT}.iam.gserviceaccount.com" \
    --role="roles/storage.${role}" --quiet >/dev/null
done

# -- 6. deploy the app --------------------------------------------------------
echo "== apply =="
kubectl apply -k "$RENDERED"
kubectl -n "$NS" rollout status deploy/serving --timeout=300s
kubectl -n "$NS" rollout status deploy/frontend --timeout=300s
# The first serving pod may boot before the permissions above have propagated
# and read an empty bucket; one restart reloads the artefacts.
kubectl -n "$NS" rollout restart deploy/serving >/dev/null

# -- 7. public URL ------------------------------------------------------------
# The frontend Service is a LoadBalancer, so GKE provisions a Cloud Load
# Balancer with a public IP - this usually takes a minute or two.
IP=""
for _ in {1..60}; do
  IP="$(kubectl -n "$NS" get svc frontend -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)"
  [[ -n "$IP" ]] && break
  sleep 5
done
echo
echo "Site:  http://${IP:-<pending - check: kubectl -n $NS get svc frontend>}"
echo "Check: curl http://${IP}/api/healthz"
echo "       kubectl -n $NS port-forward svc/frontend 8080:80   # without the LB"
echo "Stop:  PROJECT=$PROJECT BUCKET=$BUCKET bash scripts/teardown_gcp.sh"