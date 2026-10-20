# Kubernetes deployment (local cluster → GKE, no application-code edits)

The cluster runs the **serving half** of the project: object storage, the training
workers + pipeline, the API and the static site. Notebooks are still the training
code — they are baked into the training image and executed by a CronJob.

```
k8s/
  base/                     shared by every environment
    serviceaccounts.yaml    serving / training / frontend
    serving.yaml            Deployment + Service + PDB + HPA (no volumes)
    frontend.yaml           ConfigMap(nginx) + Deployment + LoadBalancer Service
    spark.yaml              spark-master (headless Service) + spark-worker
    training-data.yaml      PVC shared by driver and executors
    training.yaml           CronJob: notebooks 01 -> 03 -> 02
  overlays/
    local-kind/             + fake-gcs-server StatefulSet(PVC) + ingest Job
    gke/                    real GCS, Workload Identity, Artifact Registry images
```

Everything environment-specific is a **kustomize overlay**: image registry, replica
counts, storage class, emulator vs real bucket, service-account annotations. The
application itself is untouched — `serving/app.py`, `frontend/` and the notebooks
are byte-identical between docker-compose, the local cluster and GKE.

## Deploy from this repository (any project)

The files under `overlays/gke` use the placeholders `PROJECT_ID` and
`BUCKET_NAME`. Put your own values in the gitignored `.env` (see `.env.example`)
and run the script, which re-renders that overlay with them first:

```bash
cp .env.example .env      # then set GCP_PROJECT / GCP_BUCKET / GKE_CLUSTER ...
bash scripts/deploy_gcp.sh
# or inline, without .env:
PROJECT=<your-project> BUCKET=<your-bucket> bash scripts/deploy_gcp.sh
```

Prerequisites: a Linux host (or WSL) with `gcloud`, `docker` and `kubectl`, a
project with billing enabled and the Owner/Editor role. The script is idempotent:
it enables the APIs, creates the Artifact Registry repo and the bucket, builds
and pushes the images, uploads the pre-built artefacts from `data/curated/`,
creates the cluster (`e2-standard-2`, 30 GB disk, Workload Identity), binds the
service accounts and applies the overlay.

Useful variables: `REGION` (default `australia-southeast1`), `ZONE`, `CLUSTER`,
`REPO`, `MACHINE_TYPE`, `DISK_SIZE`, `WITH_TRAINING=1` (also build the training
image) and `RENDER_ONLY=1` (print the rendered overlay without touching the
cloud). Tear down with:

```bash
PROJECT=<your-project> BUCKET=<your-bucket> bash scripts/teardown_gcp.sh
```

### Troubleshooting: cannot push to the registry

A failure such as
`Head "https://<region>-docker.pkg.dev/v2/.../blobs/sha256:..." ... connection refused`
means this host cannot reach Artifact Registry (blocked egress, VPN or a flaky
link). The script already retries the push five times and prints the fix; two
reliable options:

1. **Build inside Google Cloud** (nothing is pushed from your machine):
   ```bash
   BUILD_MODE=cloudbuild bash scripts/deploy_gcp.sh
   ```
   `gcloud builds submit` uploads the build context, builds in Cloud Build and
   pushes to Artifact Registry from inside GCP. The script grants the Cloud Build
   service account `roles/artifactregistry.writer` first.
2. **Run from Cloud Shell**, which has unrestricted access to the registry:
   clone the repo (or restore it from `gs://…/release/`) and run the normal
   `bash scripts/deploy_gcp.sh`.

Expected cost for the default shape is ≈ A$134/month
(`docs/cloud-usage-and-cost.md`); tear it down when finished.

The serving artefacts are committed under `data/curated/` (catalogue, FPS curves,
metrics, Parquet parts, gallery index), so the API works as soon as the bucket is
seeded. To regenerate them instead, run the notebooks (see the training CronJob).

## Where the environment switch happens

| knob | local (kind/minikube) | GKE |
|---|---|---|
| `STORAGE_EMULATOR_HOST` (app-config ConfigMap) | `http://gcs:4443` | **unset** → real GCS |
| bucket | emulator bucket on a PVC | `gs://…` created with `gcloud storage buckets create` |
| credentials | none | Workload Identity: k8s SA → Google SA → bucket role |
| images | local build, `IfNotPresent` | Artifact Registry (`overlays/gke` `images:` transformer) |
| spark workers | 2 | 1 (test cluster) — `patch-scale.yaml` |

`patch-scale.yaml` also pins serving and frontend to **one replica each** and the
HPA to min=max=1, so a busy demo cannot add a second node.

### Cost profile (Sydney list prices)

| item | monthly |
|---|---|
| `e2-standard-2` node (2 vCPU / 8 GiB) | $69.41 |
| 30 GB `pd-standard` boot disk | $1.62 |
| Frontend `LoadBalancer` (rule + IP) | $21.90 |
| GKE zonal control plane | $0 (first free zonal cluster) |
| Artifact Registry + GCS + PVC | ≈ $0.2 |
| **Total** | **≈ $93/mo** (~$0.13/h) |

`e2-medium` was tried first and is not usable here: shared-core sizing plus the
GKE reservation leaves only **940m CPU** allocatable, so the Spark worker never
schedules. `e2-standard-2` is the smallest node that runs Spark, serving and the
frontend together. Spot nodes cut the node line by ~49% (≈ $59/mo total) at the
cost of eviction risk. Dropping the `LoadBalancer` for `NodePort` +
`kubectl port-forward` saves another ~$22/mo. The previous shape
(e2-standard-4, 2 replicas, autoscaling to 2 nodes) was ≈ $174/mo.

Serving has **no volumes at all**: the catalogue (`models/gpus_classified.csv`) and
the per-game FPS curve (`models/game_fps_model.csv`, `models/fps_curve.json`) are
read from the bucket — it is the only fps→g3d mechanism, so the two endpoints can
never disagree. The UI's suggestion lists come from `GET /games` and `GET /gpus`,
which is why the frontend needs neither a volume nor an init container.

## Local cluster (kind)

```bash
docker compose build serving frontend ingest
kind create cluster --name gpu-recsys
for i in gpu-recsys-serving gpu-recsys-frontend gpu-recsys-ingest; do
  kind load docker-image $i:latest --name gpu-recsys
done
kubectl apply -k k8s/overlays/local-kind
```

`frontend` is a `LoadBalancer`; with MetalLB it gets a real EXTERNAL-IP, otherwise
fall back to `kubectl port-forward svc/frontend`. Seed the emulator bucket (the
ingest Job fetches Zenodo, or upload from the host with **POST** — `PUT` on
`/upload/...` returns 404):

```bash
PF=14443; kubectl -n gpu-recsys port-forward svc/gcs $PF:4443 &
curl -s -X POST "http://localhost:$PF/storage/v1/b?project=test" \
  -H 'Content-Type: application/json' -d '{"name":"gpu-recsys"}'
curl -s -X POST --data-binary @data/curated/gpus_classified.csv \
  "http://localhost:$PF/upload/storage/v1/b/gpu-recsys/o?uploadType=media&name=models%2Fgpus_classified.csv"
```

Use a port that is free: docker-compose already owns 4443, and a failed
port-forward makes you test the *compose* emulator by mistake.

## GKE runbook (verified end to end)

```bash
gcloud artifacts repositories create gpu-recsys --repository-format=docker \
  --location=australia-southeast1
gcloud storage buckets create gs://<BUCKET> --location=australia-southeast1 \
  --uniform-bucket-level-access

gcloud container clusters create gpu-recsys-test --zone australia-southeast1-a \
  --num-nodes 1 --machine-type e2-standard-2 --disk-size 30 --disk-type pd-standard \
  --workload-pool=<PROJECT>.svc.id.goog --scopes=cloud-platform

# identity: one Google SA per Kubernetes SA
for n in serving training frontend; do
  gcloud iam service-accounts create gpu-recsys-$n
  gcloud iam service-accounts add-iam-policy-binding \
    gpu-recsys-$n@<PROJECT>.iam.gserviceaccount.com \
    --role=roles/iam.workloadIdentityUser \
    --member="serviceAccount:<PROJECT>.svc.id.goog[gpu-recsys/$n]"
done
gcloud storage buckets add-iam-policy-binding gs://<BUCKET> \
  --member=serviceAccount:gpu-recsys-serving@<PROJECT>.iam.gserviceaccount.com \
  --role=roles/storage.objectViewer        # …training: objectAdmin, frontend: objectViewer

docker build -f training/Dockerfile -t <AR>/training:v1 .   # + serving, frontend
docker push <AR>/{serving,frontend,training}:v1
kubectl apply -k k8s/overlays/gke
kubectl -n gpu-recsys get svc frontend      # wait for EXTERNAL-IP
```

Retrain on demand (the CronJob is `suspend: true` so it never fires unattended):

```bash
kubectl -n gpu-recsys create job --from=cronjob/retrain retrain-manual
kubectl -n gpu-recsys rollout restart deploy/serving   # reload the new artifacts
```

### Verified in a real GKE cluster

- `frontend` LoadBalancer → a Google Cloud LB IP; site, `/api/healthz`,
  `/api/recommend`, `/api/fps` all served **through the LB**.
- serving with **no volumes**: `gpus_loaded: 1381, catalog: classified,
  curve: loaded, emulator: null` — real Cloud Storage via
  Workload Identity, identical image to docker-compose.
- Spark master + worker in-cluster; the training Job's Spark applications
  registered with the master and ran on the workers.

### Findings that only appear in a real cluster

1. **`SPARK_MASTER_PORT=tcp://<ip>:7077`** — Kubernetes injects Service env vars
   into every pod, and Spark parses that value as an int
   (`NumberFormatException`). Set `SPARK_MASTER_HOST/_PORT/_WEBUI_PORT`
   explicitly (done in `spark.yaml`).
2. **The master must not bind to a ClusterIP.** With a normal Service the name
   resolves to the VIP, which is not a local address
   (`BindException: cannot assign requested address`). Use a **headless**
   Service (`clusterIP: None`) so the name resolves to the pod IP. Note
   `clusterIP` is immutable — changing it requires deleting the Service.
3. **`import pyspark` fails in the spark image** — the bindings live under
   `/opt/spark/python` and are not on `PYTHONPATH`. Set
   `PYTHONPATH=/opt/spark/python:/opt/spark/python/lib/py4j-0.10.9.7-src.zip`.
4. **Executors cannot see the driver's `emptyDir`.** A `file:/data/games.csv`
   read fails on the executor (`SparkFileNotFoundException`). The driver and the
   workers need the *same* volume at the *same* path — hence `training-data`
   (RWO: fine on one node; use RWX or the GCS connector if the pool spans nodes).
   This is the case that justifies a PVC in a dataset that is otherwise
   bucket-first.
5. **Workload Identity bindings need a moment.** Pods that boot immediately after
   the IAM binding get `iam.serviceAccounts.getAccessToken denied`; a rollout
   restart (or a retry loop in the loader) clears it.
6. **Training image Python is 3.8** (apache/spark base): pin
   `numpy<1.25` / `pandas<2.0` so a cp38 wheel resolves; `vector_to_array` in
   notebook 03 needs pandas installed.

## Code in GCP (copy of record)

The repository lives on GitHub (`510704/infs3208-gpu-recommender`, private). A
snapshot is also published to the project bucket, so the code is available inside
GCP without GitHub credentials:

```
gs://<BUCKET>/release/infs3208-gpu-recommender.bundle   # full history (git bundle, cloneable)
gs://<BUCKET>/release/infs3208-gpu-recommender.zip      # working tree
```

### Cloud Shell commands

Cloud Shell has `gcloud`, `git`, `docker` and `kubectl`, so `scripts/deploy_gcp.sh`
runs there end to end.

```bash
gcloud config set project <PROJECT>

# 1. restore the code from the bucket (full history)
gcloud storage cp gs://<BUCKET>/release/infs3208-gpu-recommender.bundle .
git clone infs3208-gpu-recommender.bundle infs3208-gpu-recommender
cd infs3208-gpu-recommender
git log --oneline -3

#    or just unpack the working tree
gcloud storage cp gs://<BUCKET>/release/infs3208-gpu-recommender.zip .
unzip -q infs3208-gpu-recommender.zip -d infs3208-gpu-recommender

# 2. or clone straight from GitHub (private: username = your account,
#    password = a fine-grained PAT with "Contents: read")
git clone https://github.com/510704/infs3208-gpu-recommender.git
#    with the GitHub CLI instead:
gh auth login && gh repo clone 510704/infs3208-gpu-recommender

# 3. deploy from Cloud Shell
PROJECT=<PROJECT> BUCKET=<BUCKET> bash scripts/deploy_gcp.sh
```

Publish a new snapshot of the code after pushing:

```bash
git bundle create infs3208-gpu-recommender.bundle --all
git archive --format=zip -o infs3208-gpu-recommender.zip HEAD
gcloud storage cp infs3208-gpu-recommender.bundle infs3208-gpu-recommender.zip \
  gs://<BUCKET>/release/
```

## Teardown

```bash
kubectl delete -k k8s/overlays/gke     # or delete the cluster (below)
gcloud container clusters delete gpu-recsys-test --zone australia-southeast1-a
gcloud artifacts repositories delete gpu-recsys --location=australia-southeast1
gcloud storage rm -r gs://<BUCKET>
for n in serving training frontend; do
  gcloud iam service-accounts delete gpu-recsys-$n@<PROJECT>.iam.gserviceaccount.com
done
```

The dataset and model artifacts are reproducible: ingest + a training run
rebuild everything from Zenodo and the notebooks.
