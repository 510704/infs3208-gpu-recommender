# GPU recommender (INFS3208)

Recommends the lowest-spec GPU that hits a target frame rate for a game, and
estimates the FPS a given GPU will reach. Spark/MLlib trains the models, a
FastAPI service serves them, and a static frontend uses that API.

## Pipeline

`ingest` -> `01_features` -> `03_gpu_catalog` -> `02_models` -> `04_game_clusters`
-> `05_demand_patterns` -> `06_visualisations` -> serving + frontend.

## Storage: Cloud Storage + Parquet

The storage layer is **Cloud Storage (GCS) + Apache Parquet**.

- The curated feature table is written as Snappy-compressed, splittable
  **Parquet** (`curated/features.parquet`): columnar, typed and several times
  smaller than the source CSVs. Its parts are also persisted in the bucket under
  `models/features/`.
- The modelling artefacts - the classified catalogue, per-game FPS curves,
  metrics and report figures - are published to the same bucket.
- GCS is the project's distributed object store: Spark/Hadoop address it as
  `gs://bucket/key` and read objects in parallel like HDFS blocks, while
  durability and replication are managed by GCS, so there is no HDFS cluster to
  operate.
- Serving reads only from the bucket, so training and serving share one source
  of truth. Locally the API is emulated by fake-gcs-server; on GKE it is real
  GCS reached through Workload Identity.

| object | purpose |
|---|---|
| `models/features/part-*.parquet` | curated feature table (durable copy) |
| `models/gpus_classified.csv` | catalogue: form factor, generation, availability |
| `models/game_fps_model.csv` | per-game log-log FPS curves |
| `models/fps_curve.json` | pooled prior and 360 FPS clip |
| `models/model_selection.json` | metrics, importances, catalogue/curve metadata |
| `models/figures/*` | report figures and the gallery index |

## Run

```bash
docker compose up -d --build              # gcs + ingest + serving + frontend
docker compose --profile training up -d  # Spark + Jupyter for the notebooks
```

Run the notebooks in order from `notebooks/`; figures land in `figures/` and are
published to the Insights tab. See `k8s/README.md` for the cluster deployment and
`data/README.md` for the dataset.

## Cloud stack and cost

The deployed stack is GKE (serving, frontend, Spark + training CronJob),
Cloud Storage for artefacts and Parquet, Artifact Registry for images,
Workload Identity for access and an external Cloud Load Balancer for the UI.
The monthly list-price estimate for the current shape (`e2-standard-2`, 30 GB
disk, one replica per tier) is **≈ A$134/month**; Spot / no-LB variants bring it
to ≈ A$85 / ≈ A$102.

- [`docs/cloud-usage-and-cost.md`](docs/cloud-usage-and-cost.md) — technology
  and cost tables with assumptions
- [`docs/cloud_resources.csv`](docs/cloud_resources.csv) — merged service + cost
  table

## Notes

- Every FPS measurement is 1080p High. The API's 1440p/4K options apply a
  documented GPU-load multiplier (1.54x / 2.83x), not measured data.
- Outlier handling and model types are stated in `notebooks/02_models.ipynb`.

## AI use acknowledgement

This project was developed with substantial assistance from an AI coding
assistant (opencode / a large language model). Every change in this repository
was produced from the author's prompts and responses in this session, then
reviewed and accepted before being kept.

Areas the AI contributed to include:

- **Data pipeline** - the six Spark notebooks end to end:
  - `01_features` - parses the free-text hardware fields with native Spark SQL
    (no Python UDFs), normalises units (MB->GB, MHz->GHz, RAM >= 128 as MB),
    excludes engine-capped rows, and derives the regression target
    `required_g3d` = the cheapest of the 12 reference GPUs that clears 60 FPS;
    it writes `features.parquet` (2 partitions, Snappy) and publishes the parts
    to Cloud Storage.
  - `02_models` - trains the tier models (Random Forest selected: RMSE 1372 /
    MAE 605.5 / R2 0.895 vs GBT, Ridge, MLP) and fits each game's closed-form
    `ln fps = a + b * ln g3d` curve by log-log least squares over five Spark
    aggregates, validated leave-one-GPU-out (curve 13.3 vs RF 49.0 FPS holdout
    MAE).
  - `03_gpu_catalog` - classifies the 1,381-GPU catalogue with a hand-curated
    38-pattern generation map (name -> family -> approximate release year ->
    current/aging/legacy_secondhand/unknown) and a TF-IDF + logistic-regression
    model (accepted at p >= 0.7) for the rows the rules cannot classify.
  - `04_game_clusters` - groups games into demand levels with KMeans + GMM,
    choosing k by the lowest GMM BIC over k=3..10 with three seeds (k=8,
    ARI 0.583), with VRAM reported in three states rather than imputed.
  - `05_demand_patterns` - mines association rules with FPGrowth
    (support >= 1%, confidence >= 0.6, 3,904 rules) and computes the demand
    trend: median minimum/recommended GPU score per 5-year bucket joined to the
    catalogue.
  - `06_visualisations` - renders the eight report figures (coverage, models,
    curve validation, catalogue, clusters, rules, trend, FPS->score fan with the
    catalogue ceiling) and publishes them to the Insights tab.
  - The shared `spark/jobs/` package (`spark_session`, `storage`, `curves`,
    `catalog`, `artifacts`, `viz`) extracted from the duplicated notebook code,
    with `tests/test_pure.py` covering the curve inversion, the resolution
    multiplier, and the generation-map matching.

- **API and UI** - the FastAPI serving service (`/healthz`, `/games`, `/gpus`,
  `/recommend`, `/fps`, `/curve`, `/figures`), including: the inverse curve
  lookup with a documented 1080p->1440p/4K load multiplier (pixel-ratio^0.75 ->
  1.54x / 2.83x); the prefer-current-generation selection that returns an older
  card only as a `cheaper_alternative` (or a flagged fallback) so a 2016 GTX 1080
  is no longer "recommended"; and the static frontend with its Suggest inline
  SVG FPS-to-score chart (click-to-set target), and the Insights gallery with
  titles, captions and per-figure explanations.

- **Infrastructure** - the Docker Compose stack (GCS emulator, ingest, serving,
  frontend, Spark, Jupyter), the Kubernetes/kustomize base and overlays
  (`local-kind`, `gke` with Workload Identity and bucket IAM), the training
  CronJob image, and the cost-driven tuning: one `e2-standard-2` node with a
  30 GB `pd-standard` disk, single replicas, HPA pinned 1->1 and trimmed Spark
  CPU requests.

- **Reports and documentation** - the storage statement (Cloud Storage + Parquet
  as the distributed file system), the outlier-handling and model-type notes, the
  eight figure explanations, and the cloud technology/cost tables in `docs/`
  (converted to AUD).

- **Cloud operations** - staged the stack on GKE twice (deploy, verify through
  the external load balancer, teardown), looked up exact Sydney SKU prices via
  the Cloud Billing Catalog API, and produced the monthly cost estimate and the
  cost-reduction analysis.

The AI also diagnosed and fixed session issues such as the `02` registry
clobbering, the pandas `n/a`-read bug, a stdlib `io` module shadowing, a Spark
`StringIndexer` null-label failure when caching, the lightbox `hidden`/`display`
conflict, and the trend's integrated-GPU share only counting one iGPU.

#### Requirements and findings the author prompted

The direction of the work came from the author's requirements, observations and
decisions, which the AI then implemented. In particular:

- **Model selection** - choosing the **Random Forest** as the production tier
  model rather than gradient-boosted trees, and keeping GBT/Ridge/MLP only for
  comparison.
- **Data interpretation** - pointing out that low minimum-VRAM clusters are really
  **CPU/GPU shared memory**, which led to VRAM being reported in three states
  (parsed / shared / missing) instead of an imputed number.
- **Clustering choices** - asking the cluster count to be justified by the
  **GMM BIC** rather than a hand-picked k, and not equating an integrated-GPU
  minimum with "esports" when naming the demand levels.
- **Presentation** - embedding the figures into the frontend Insights tab, using
  plain-English labels and score ranges, and adding a one-line reading guide for
  the association rules.
- **Recommendation quality** - flagging that a 2016 GTX 1080 was being recommended
  for Cyberpunk 2077, which produced the GPU generation map and the
  prefer-current-generation selection with a `cheaper_alternative`.
- **Resolution** - requesting an explicit 1080p/1440p/4K option, delivered as a
  documented load multiplier (not data the model measures).
- **Cost** - asking to shrink the node, disk and replicas while keeping Spark and
  a public URL, and to present the technology and cost together in AUD.

Model and data decisions (the reference-GPU curve approach, resolution
scaling, catalogue generation map, cluster count), data fixes, rubric
requirements and the retention or rejection of any change were made, verified or
approved by the author. The AI's output was treated as a draft to review, not as
a source of truth.
