"""Render the project's end-to-end workflow figure.

Run from anywhere:
    python docs/render_workflow.py

Outputs (overwritten):
    figures/00_workflow.png   (300 dpi, for the report)
    figures/00_workflow.svg   (vector, for slides / print)
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "figures"
OUT.mkdir(exist_ok=True)

# ------------------------------------------------------------------ palette
INK = "#0f172a"
MUTED = "#475569"
EDGE = "#334155"
BAND_EDGE = "#94a3b8"
BAND_FILL = "#f8fafc"
C_SRC = "#e0f2fe"   # sky    - external data
C_ING = "#ccfbf1"   # teal   - ingest
C_STO = "#fef9c3"   # amber  - storage
C_PRO = "#dcfce7"   # green  - processing
C_SRV = "#ede9fe"   # violet - serving
C_UI = "#ffedd5"    # orange - interface
C_DEP = "#e2e8f0"   # slate  - deployment

W, H = 190, 120
fig, ax = plt.subplots(figsize=(19, 12))
ax.set_xlim(0, W)
ax.set_ylim(0, H)
ax.set_aspect("equal")
ax.axis("off")


def text(x, y, s, size=9, weight="normal", color=INK, ha="center", va="center",
         style="normal", bbox=None):
    ax.text(x, y, s, fontsize=size, fontweight=weight, color=color,
            ha=ha, va=va, style=style, linespacing=1.3, zorder=4, bbox=bbox)


def box(x, y, w, h, title, body=None, face=C_PRO, tsize=10.5, bsize=7.8):
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                                boxstyle="round,pad=0.35,rounding_size=1.0",
                                linewidth=1.1, edgecolor=EDGE, facecolor=face, zorder=2))
    cx = x + w / 2
    if body:
        text(cx, y + h - 3.4, title, size=tsize, weight="bold")
        text(cx, y + h / 2 - 2.8, body, size=bsize, color=MUTED)
    else:
        text(cx, y + h / 2, title, size=tsize, weight="bold")


def band(x, y, w, h, title):
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                                boxstyle="round,pad=0.5,rounding_size=1.6",
                                linewidth=1.0, edgecolor=BAND_EDGE, facecolor=BAND_FILL,
                                linestyle=(0, (5, 4)), zorder=1))
    text(x + 4, y + h - 3.0, title, size=9.5, weight="bold", color="#1e293b", ha="left")


def arrow(x1, y1, x2, y2, color=EDGE, lw=1.6, ms=14, dashed=False):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=ms,
                                 linewidth=lw, color=color, zorder=5,
                                 linestyle="--" if dashed else "-"))


# ------------------------------------------------------------------- title
text(4, 118.2, "GPU recommender — end-to-end workflow", size=17, weight="bold", ha="left")
text(4, 115.8, "Spark/MLlib analytics  →  a served model  →  a web UI, on one shared object store",
     size=9.5, color=MUTED, ha="left")

# ============================================================ 1. ACQUIRE & STORE
band(3, 93.5, 184, 20, "① ACQUIRE & STORE   ·   Google Cloud Storage (distributed object store) + Parquet")

box(7, 97, 36, 11, "Zenodo dataset",
    "PC Game System Requirements\n& Estimated FPS by GPU\nv2026-10-03 · CC BY 4.0", C_SRC, 9.5, 6.8)
box(48, 97, 34, 11, "ingest service",
    "download · verify MD5\nwrite _provenance.json", C_ING, 9.5, 6.8)
box(87, 97, 25, 11, "raw/",
    "games.csv  17,412\ngpus.csv  1,381", C_STO, 9.5, 6.8)
box(117, 97, 28, 11, "curated/",
    "features.parquet\nclusters · catalog", C_STO, 9.5, 6.8)
box(150, 97, 31, 11, "models/",
    "FPS curves · metrics\nfigures · feature copy", C_STO, 9.5, 6.8)

arrow(43.5, 102.5, 47.5, 102.5)
arrow(82.5, 102.5, 86.5, 102.5)
arrow(112.5, 102.5, 116.5, 102.5)
arrow(145.5, 102.5, 149.5, 102.5)

# ============================================================ 2. PROCESS
band(3, 63, 184, 28,
     "② PROCESS   ·   Apache Spark 3.5 + MLlib   (Dataproc Serverless · Spark master + worker on GKE)")

text(95, 86.4, "pipeline order:  01 → 03 → 02 → 04 → 05 → 06",
     size=8, color=MUTED, style="italic")

NB = [
    ("01 · Features",   "parse prose specs\ncleanse · impute\nfeature engineering", "preprocessing"),
    ("03 · GPU catalog", "rules + TF-IDF\nLogisticRegression", "classification"),
    ("02 · Models",      "RandomForestRegressor\nper-game FPS curve", "regression"),
    ("04 · Clusters",    "KMeans + GaussianMixture\nBIC · silhouette · ARI", "clustering"),
    ("05 · Demand",      "FPGrowth rules\ndemand trend", "association rules"),
    ("06 · Figures",     "8 report figures\nfrom curated artifacts", "visualisation"),
]
xs = [5, 34, 63, 92, 121, 150]
for x, (title, body, tag) in zip(xs, NB):
    box(x, 69, 26, 13, title, body, C_PRO, 10, 7.0)
    text(x + 13, 65.4, tag, size=7.2, color="#166534", style="italic")

for i in range(5):
    arrow(xs[i] + 26.4, 75.5, xs[i + 1] - 0.4, 75.5, ms=10, lw=1.3)

# storage read / write loop (kept to two short arrows to avoid spaghetti)
arrow(131, 96.6, 131, 91.4, dashed=True, lw=1.3, ms=11)
text(132.5, 92.4, "read features.parquet", size=6.4, ha="left", color=MUTED,
     bbox=dict(facecolor="white", edgecolor="none", pad=0.6))
arrow(165, 91.4, 165, 96.6, dashed=True, lw=1.3, ms=11)
text(166.5, 92.4, "write artifacts", size=6.4, ha="left", color=MUTED,
     bbox=dict(facecolor="white", edgecolor="none", pad=0.6))

# ============================================================ 3. SERVE
band(3, 30, 184, 26, "③ SERVE   ·   FastAPI loads models/ from the bucket at startup (read-only, stateless)")
box(8, 36, 80, 12, "FastAPI serving",
    "POST /recommend · POST /fps\nGET /healthz · /games · /gpus · /figures", C_SRV, 10.5, 7.4)
box(100, 36, 78, 12, "Static frontend (nginx)",
    "recommendation UI\nInsights tab: report gallery", C_UI, 10.5, 7.4)
arrow(88.5, 42.0, 99.5, 42.0)
arrow(95, 62.6, 95, 56.4, dashed=True, lw=1.3, ms=11)
text(96.5, 59.2, "loads models/", size=6.6, ha="left", color=MUTED,
     bbox=dict(facecolor="white", edgecolor="none", pad=0.6))

# ============================================================ 4. DEPLOY
band(3, 3, 184, 22,
     "④ DEPLOY & OPERATE   ·   identical images; only the kustomize overlay changes")
box(8, 7, 52, 12, "Local", "Docker Compose\nfake-gcs-server · Spark · serving", C_DEP, 10, 7.2)
box(66, 7, 58, 12, "Cloud (GKE)", "Workload Identity · HPA\nretrain CronJob · LoadBalancer", C_DEP, 10, 7.2)
box(130, 7, 50, 12, "Cost (list price)", "≈ A$134 / month\ne2-standard-2 · 30 GB disk", C_DEP, 10, 7.2)
arrow(95, 29.6, 95, 25.4, dashed=True, lw=1.3, ms=11)

# ------------------------------------------------------------------- footer
text(4, 1.4,
     "Sources: Zenodo dataset (CC BY 4.0)  ·  Figures generated by notebooks 01–06  ·  "
     "Every FPS value is 1080p High",
     size=7.2, color=MUTED, ha="left", style="italic")

fig.savefig(OUT / "00_workflow.png", dpi=300, bbox_inches="tight", facecolor="white")
fig.savefig(OUT / "00_workflow.svg", bbox_inches="tight", facecolor="white")
plt.close(fig)
print("wrote", OUT / "00_workflow.png")
print("wrote", OUT / "00_workflow.svg")
