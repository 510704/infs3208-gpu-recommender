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

Site: `http://localhost:30080` (the host publishes 30080, the same port number as
the GKE NodePort, so the URL shape matches in both environments; API on
`http://localhost:8000`).

Run the notebooks in order from `notebooks/`; figures land in `figures/` and are
published to the Insights tab. See `k8s/README.md` for the cluster deployment and
`data/README.md` for the dataset.

## Cloud stack and cost

The deployed stack is GKE (serving, frontend, Spark + training CronJob),
Cloud Storage for artefacts and Parquet, Artifact Registry for images,
Workload Identity for access and a Cloud Load Balancer (public IP) for the UI.
The monthly list-price estimate for the current shape (`e2-standard-2`, 30 GB
disk, one replica per tier, LoadBalancer access) is **≈ A$134/month**; a Spot node
brings it to ≈ A$85/month.

- [`docs/cloud-usage-and-cost.md`](docs/cloud-usage-and-cost.md) — technology
  and cost tables with assumptions
- [`docs/cloud_resources.csv`](docs/cloud_resources.csv) — merged service + cost
  table
- Code snapshot in the bucket (`gs://<BUCKET>/release/`: git bundle + zip) with the
  Cloud Shell commands — see [`k8s/README.md`](k8s/README.md)

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
  the load balancer, teardown), looked up exact Sydney SKU prices via
  the Cloud Billing Catalog API, and produced the monthly cost estimate and the
  cost-reduction analysis.

The AI also diagnosed and fixed session issues such as the `02` registry
clobbering, the pandas `n/a`-read bug, a stdlib `io` module shadowing, a Spark
`StringIndexer` null-label failure when caching, the lightbox `hidden`/`display`
conflict, and the trend's integrated-GPU share only counting one iGPU.

#### Structured AI/MT declaration

Tool: **opencode** — an AI coding assistant CLI driven by a large language model
(DeepSeek-V4.1-flash). Prompts below are quoted from this session, abridged.

| Area | Purpose of use | Prompt(s) used | Where used |
|---|---|---|---|
| Tier model | Choose the production regression model | "…like using **random forest rather than GBT**" (author's decision, recorded in this session) | `notebooks/02_models.ipynb` (model comparison, `selected_model`), `spark/jobs/` |
| Data pipeline | Build/reuse the Spark notebooks and shared code | "**plan code optimizations on large code like notebooks with reusable components**" | `notebooks/01…06`, `spark/jobs/*`, `spark/jobs/tests/test_pure.py` |
| Visualisations | Fix labels, bins, panels and colour clashes in the report figures | "**use more human readible words, not phrazes**"; "**games per required G3D x axis should use ranges like 0-5000, 5000-10000**"; "**remove availibility by form factor**"; "**remove unclassified and circles**"; "**IGPU didnot mean esport, use GMM BIC to justify the k of kmeans instead of hardcode**"; "**shortly but clearly explain top rules by lift**"; "**required tier over time should display curves for recommanded and minimal g3d**"; "**use finer interval since there is nothing above 30k**"; "**level 1 and 7, level2 and 8, their label colors are too close**"; "**order the figure in grid with importance and relevance to each other**" | `notebooks/06_visualisations.ipynb`, `figures/*.png`, `spark/jobs/viz.py`, `spark/jobs/catalog.py` |
| Recommendation quality | Distinguish legacy GPUs so old cards are not recommended | "**review how to distinguish legacy gpu since i find GTX1080 is recommended for Cyberpunk 2077**" | `notebooks/03_gpu_catalog.ipynb` (generation map), `serving/app.py` (`cheaper_alternative`, `legacy_fallback`) |
| Resolution option | Add 1080p/1440p/4K without complexity | "**where can i integrate the resolution parameters without over complexity**"; "**plan to visualize diagram from fps to required g3d**" | `spark/jobs/curves.py`, `serving/app.py` (`resolution_factor`), `frontend/app.js`, `notebooks/06` (figure 08) |
| Frontend | Embed the figures in the site; fix the blocking overlay | "**visualization should be embeded into frontend**"; "**the div lightbox make localhost not interactable**" | `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`, `serving/app.py` (`/figures`) |
| Rubric compliance | Make the storage choice explicit and name two modelling points | "**…the data-storage requirement needs an explicit, defensible statement (GCS+Parquet …), and two minor polish items: name your outlier handling, and add one sentence clarifying the FPS curve is not an MLlib model and clustering/rules are unsupervised**" | `README.md` (storage section), `notebooks/01_features.ipynb`, `notebooks/02_models.ipynb` (markdown) |
| Notebook prose | Rewrite the explanations concisely | "**rewrite markdown in notebooks with human readible and concise text**" | every `notebooks/*.ipynb` markdown cell |
| Data rerun | Refresh the trend after an author data fix | "**rerun score and game mix over time since i fix some data**" | `notebooks/01_features.ipynb`, `notebooks/05_demand_patterns.ipynb`, `figures/07_demand_trend.png`, `data/curated/analytics_trend.csv` |
| Insights text | Explain each figure inside the app | "**shortly explain graphs in insight of frontend**"; "**write the explanation in insight**" | `frontend/index.html` + `app.js` (Insights tab), `notebooks/06` gallery index |
| Cloud deployment | Stage to GCP, price it and tear it down | "**stage to GCP and estimate the cloud cost, and unstage that after finishing**" | `k8s/`, `docs/cloud-usage-and-cost.md`, `docs/cloud_resources.csv` |
| Cost reduction | Shrink the deployment while keeping Spark and a public URL | "**plan to potentially reduce the cost**"; "**reduce on node size and disk and replicas like B / keep spark and being accessed by GCP external url**"; "**switch to AUD**"; "**keep exact use like e2-standard-2 and 30GB disk**"; "**merge technology and cost into one**" | `k8s/overlays/gke/patch-scale.yaml`, `k8s/README.md`, `docs/cloud_resources.csv` |
| Packaging | Zip the essentials and publish a personal repo | "**plan to zip the whole dir with essential components and stage to personal repo**"; "**execute it**"; "**check if anyone have the zip can deploy into cloud**" | `.gitignore`, `.gitattributes`, `scripts/deploy_gcp.sh`, `scripts/teardown_gcp.sh`, the GitHub repository and the release zip |

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
