# Cloud technologies and monthly cost estimate

The project runs on **Google Cloud Platform** in the author's project in
`australia-southeast1` (Sydney); the project id, bucket and cluster name live in
the gitignored `.env` (documented in `.env.example`).
Prices are Google Cloud on-demand list prices converted to **AUD** at
**1 USD = 1.437 AUD** (ECB reference rate, 2026-10-16), checked 2026-10-19, and
assume 730 usage hours per month.

## Cloud computing technologies

| Layer | Technology | Cloud service | Role in the project |
|---|---|---|---|
| Frontend | HTML/CSS/JavaScript + nginx reverse proxy | GKE Deployment + NodePort on the node external IP | Static UI (Find a GPU / Estimate FPS / Insights) on `http://<node-ip>:30080`; `/api` proxied to serving |
| Backend API | FastAPI + Uvicorn (Python 3.11) | GKE Deployment + ClusterIP Service | Lowest-spec GPU for a game/target FPS, and FPS for a game/GPU pair; reads artefacts from the bucket |
| ML training | PySpark + MLlib (RandomForest, GBT, Ridge, MLP; KMeans/GMM; FPGrowth) | GKE CronJob (suspended) + in-cluster Spark master/worker | Required-G3D model, per-game FPS curves, demand clustering, association rules |
| Object storage | Cloud Storage bucket | Cloud Storage | Catalogue, curves, metrics, Parquet features, figures and gallery index; single source of truth |
| Data format | Apache Parquet (Snappy) | Cloud Storage + node disk | Columnar, splittable curated feature table |
| Orchestration | Kubernetes + kustomize | GKE | Deployments, Services, HPA, PDB, CronJob, PVC; local-kind and GKE overlays |
| Container registry | Docker images | Artifact Registry | Versioned serving/frontend/training images |
| Identity | Workload Identity + IAM service accounts | GKE + IAM | Keyless pod access to the bucket (objectViewer / objectAdmin) |
| Networking | NodePort 30080 + firewall rule | Compute Engine node external IPv4 | Public HTTP entry on the node IP; no Cloud Load Balancer |
| Persistent storage | ReadWriteOnce PVC | Compute Engine persistent disk | Scratch volume shared by the training driver and executors |
| Local parity | Docker Compose + fake-gcs-server | Local GCS emulator | Same images and bucket API for development |
| Ingestion | Python ingest job (Zenodo) | Local job + provenance record | Downloads `games.csv` / `gpus.csv` with checksums |
| Observability | Liveness/readiness probes + GKE logs | Cloud Logging / Cloud Monitoring | Rollout safety and cluster logs/metrics |
| Automation | gcloud, kubectl, Docker | Cloud SDK | Staging, image push, verification, teardown |

## Monthly cost estimate

| Resource | Specification | Unit price | AUD/month |
|---|---|---|---:|
| GKE control plane | zonal cluster | A$0 (first free zonal) | 0.00 |
| Compute node | `e2-standard-2` (2 vCPU / 8 GiB) | A$0.1366/h | 99.74 |
| Boot disk | 30 GB `pd-standard` | A$0.0776/GiB-month | 2.33 |
| Training scratch volume | 1 GiB `pd-balanced` | A$0.1940/GiB-month | 0.20 |
| Node external IPv4 | ephemeral, attached to the running node | A$0 | 0.00 |
| Artifact Registry | 0.25 GiB images | A$0.1437/GiB-month | 0.04 |
| Cloud Storage | 6 MB Standard (Sydney) | A$0.0331/GiB-month | 0.01 |
| Network egress | ~1 GB/month | A$0.1724/GB | 0.17 |
| Cloud Logging / Monitoring | default GKE integration | free tier | 0.00 |
| IAM / Workload Identity | service accounts | free | 0.00 |
| **Total** | | | **102.49** |

The merged machine-readable table is in [`cloud_resources.csv`](cloud_resources.csv).

## Assumptions and alternatives

- The node is the dominant cost. **Spot** pricing cuts it by ~49%, bringing the
  total to **≈ A$84.78/month** (eviction risk, acceptable for a demo).
- The frontend is served by a **NodePort on the node's external IP**
  (`http://<node-ip>:30080`), not a Cloud Load Balancer — that is the deployed
  shape and it saves ≈ A$31/month.
- For demos the environment can instead be created and deleted per session: a
  measured ~45-minute stage + verify + teardown cycle cost **≈ A$0.22** and left
  nothing running.
- `e2-medium` was tried first and cannot host the stack: shared-core sizing plus
  the GKE reservation leaves only 940m CPU allocatable, so the Spark worker never
  schedules. `e2-standard-2` is the smallest workable node.
- If the GKE free-tier credit has already been used, add **≈ A$104.90/month** for
  the zonal control plane.
- Sustained-use discounts on Compute Engine can reduce the node line further.
- On-demand `e2-standard-4` with two replicas and autoscaling to two nodes (the
  earlier shape) was ≈ A$250.04/month, so the current profile is roughly half.
