"""Model-serving API for the GPU/game hardware recommender.

Build once, run anywhere. This exact image runs in two places and only the
environment differs:

    docker-compose -> STORAGE_EMULATOR_HOST=http://gcs:4443 (fake-gcs-server)
    GKE            -> emulator unset; real Cloud Storage via Workload Identity

There is no local-file code path and no volume is mounted anywhere: the GPU
catalogue, the per-game FPS curve and the pooled prior are all read from the
bucket at startup.

Endpoints
    GET  /healthz    liveness + what was loaded
    GET  /games      game titles (suggestion list for the web UI)
    GET  /gpus       GPU names    (suggestion list for the web UI)
    GET  /figures    published analytics figures (index)
    GET  /figures/{name}  one figure as PNG
    GET  /curve      fitted FPS -> required-score curve for one game
    POST /recommend  {game, target_fps, ...} -> required g3d score + GPU to buy
    POST /fps        {game, gpu} -> predicted FPS

Both directions come from the same per-game curve, so a GPU the recommender
picks always clears the requested FPS - they cannot disagree. When the curve or
the catalogue is missing the endpoints fail loudly (503) instead of guessing.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("serving")

# ---------------------------------------------------------------- configuration

MODEL_BUCKET = os.getenv("MODEL_BUCKET", "gpu-recsys")
CATALOG_BLOB = os.getenv("CATALOG_BLOB", "models/gpus_classified.csv")
RAW_GPUS_BLOB = os.getenv("RAW_GPUS_BLOB", "raw/gpus.csv")
GAME_MODEL_BLOB = os.getenv("GAME_MODEL_BLOB", "models/game_fps_model.csv")
CURVE_BLOB = os.getenv("CURVE_BLOB", "models/fps_curve.json")
FIGURE_PREFIX = os.getenv("FIGURE_PREFIX", "models/figures")
FIGURE_NAME = re.compile(r"^[0-9]{2}_[a-z_]+\.png$")
EMULATOR = os.getenv("STORAGE_EMULATOR_HOST")

# The Google Cloud client requires a scheme. "gcs:4443" produces the opaque
# "No connection adapters were found for 'gcs:4443/storage/v1/...'" error, so
# normalise once here instead of trusting every deployment to get it right.
if EMULATOR and "://" not in EMULATOR:
    EMULATOR = f"http://{EMULATOR}"
    os.environ["STORAGE_EMULATOR_HOST"] = EMULATOR

# The dataset never reports above 360 FPS (its own reporting ceiling).
CLIP_FPS = 360.0

# Every measurement is 1080p High; higher resolutions scale the GPU load.
# Kept in sync with spark/jobs/curves.py (tested there; the serving image is
# deliberately not built from the notebook/jobs tree).
RESOLUTIONS = {"1080p": (1920, 1080), "1440p": (2560, 1440), "4k": (3840, 2160)}
RESOLUTION_EXPONENT = 0.75


def _resolution_factor(resolution: str) -> float:
    width, height = RESOLUTIONS[resolution]
    return ((width * height) / (1920 * 1080)) ** RESOLUTION_EXPONENT


# ------------------------------------------------------------------------- state


@dataclass(frozen=True)
class Gpu:
    """One row of the classified GPU catalogue."""

    name: str
    g3d_mark: int
    form_factor: str = "unknown"
    market: str = "consumer"
    availability: str = "unknown"
    generation: str | None = None
    gen_year: int | None = None


@dataclass(frozen=True)
class Curve:
    """Per-game log-log fit: ln(fps) = a + b * ln(g3d)."""

    a: float
    b: float
    r2: float | None = None
    g3d_min: int | None = None
    g3d_max: int | None = None


@dataclass
class _State:
    gpus: list[Gpu] = field(default_factory=list)
    classified: bool = False
    curves: dict[str, Curve] = field(default_factory=dict)
    game_names: list[str] = field(default_factory=list)
    gpu_names: list[str] = field(default_factory=list)
    prior: Curve | None = None
    curve_loaded: bool = False
    figure_index: list[dict[str, Any]] = field(default_factory=list)
    figures: dict[str, bytes] = field(default_factory=dict)


state = _State()


def _fetch_blob(name: str) -> str | None:
    """Download a text object from the bucket (emulator or real GCS)."""
    try:
        from google.cloud import storage  # imported lazily: keeps /healthz fast

        client = storage.Client()
        return client.bucket(MODEL_BUCKET).blob(name).download_as_bytes().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        log.warning("could not load gs://%s/%s (%s)", MODEL_BUCKET, name, exc)
        return None


def _fetch_bytes(name: str) -> bytes | None:
    """Download a binary object from the bucket (a published PNG figure)."""
    try:
        from google.cloud import storage

        client = storage.Client()
        return client.bucket(MODEL_BUCKET).blob(name).download_as_bytes()
    except Exception as exc:  # noqa: BLE001
        log.warning("could not load gs://%s/%s (%s)", MODEL_BUCKET, name, exc)
        return None


def load_figures() -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    """Load the analytics figure index and its PNGs from the bucket.

    Notebook 06 publishes `models/figures/index.json` plus the images; caching
    them at boot keeps the endpoints fast and avoids a bucket read per <img>.
    """
    meta = _fetch_blob(f"{FIGURE_PREFIX}/index.json")
    if not meta:
        log.warning("no figure index at gs://%s/%s - the Insights tab will be empty", MODEL_BUCKET, FIGURE_PREFIX)
        return [], {}
    try:
        index = json.loads(meta)
    except ValueError as exc:
        log.warning("could not parse the figure index (%s)", exc)
        return [], {}

    ordered: list[dict[str, Any]] = []
    figures: dict[str, bytes] = {}
    for entry in index:
        name = str(entry.get("name", ""))
        if not FIGURE_NAME.match(name):
            continue
        data = _fetch_bytes(f"{FIGURE_PREFIX}/{name}")
        if data:
            figures[name] = data
            try:
                span = max(1, min(2, int(entry.get("span", 1))))
            except (TypeError, ValueError):
                span = 1
            ordered.append({
                "name": name,
                "title": entry.get("title") or name,
                "caption": entry.get("caption") or "",
                "span": span,
                "explanation": entry.get("explanation") or "",
            })

    log.info("loaded %d figures", len(ordered))
    return ordered, figures


def _int_or_none(value: Any) -> int | None:
    try:
        return int(float(str(value).strip())) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None


def _parse_gpus(text: str) -> list[Gpu]:
    rows: list[Gpu] = []
    for record in csv.DictReader(io.StringIO(text)):
        raw = (record.get("g3d_mark") or "").strip()
        if not raw:
            continue
        try:
            score = int(float(raw))
        except ValueError:
            continue
        rows.append(
            Gpu(
                name=(record.get("name") or "").strip(),
                g3d_mark=score,
                form_factor=(record.get("form_factor") or "unknown").strip(),
                market=(record.get("market") or "consumer").strip(),
                availability=(record.get("availability") or "unknown").strip(),
                generation=(record.get("generation") or "").strip() or None,
                gen_year=_int_or_none(record.get("gen_year")),
            )
        )
    rows.sort(key=lambda gpu: gpu.g3d_mark)
    return rows


def load_gpus() -> tuple[list[Gpu], bool]:
    """Load the GPU catalogue from the bucket.

    Prefers the classified catalogue from the catalog notebook and falls back to
    the raw Zenodo table (one undifferentiated pool) so a fresh bucket still
    serves something.
    """
    for blob_name, classified in ((CATALOG_BLOB, True), (RAW_GPUS_BLOB, False)):
        text = _fetch_blob(blob_name)
        if not text:
            continue
        rows = _parse_gpus(text)
        if rows:
            log.info("loaded %d GPUs from gs://%s/%s", len(rows), MODEL_BUCKET, blob_name)
            return rows, classified

    log.warning("no GPU catalogue in gs://%s - /recommend will fail", MODEL_BUCKET)
    return [], False


def _parse_curve(text: str) -> tuple[dict[str, Curve], list[str]]:
    curves: dict[str, Curve] = {}
    display: dict[str, str] = {}
    for record in csv.DictReader(io.StringIO(text)):
        if (record.get("source") or "").strip() != "game":
            continue
        name = (record.get("name") or "").strip()
        try:
            curve = Curve(
                a=float(record["a"]),
                b=float(record["b"]),
                r2=float(record["r2"]) if record.get("r2") else None,
                g3d_min=int(record["g3d_min"]) if record.get("g3d_min") else None,
                g3d_max=int(record["g3d_max"]) if record.get("g3d_max") else None,
            )
        except (KeyError, TypeError, ValueError):
            continue
        key = name.lower()
        curves[key] = curve
        display.setdefault(key, name)
    return curves, sorted(display.values())


def load_curve() -> tuple[dict[str, Curve], list[str], Curve | None, bool]:
    """Load the per-game curves and the pooled prior from the bucket."""
    text = _fetch_blob(GAME_MODEL_BLOB)
    curves, names = _parse_curve(text) if text else ({}, [])
    if not curves:
        log.warning("no FPS curve in gs://%s/%s - /fps and /recommend will fail", MODEL_BUCKET, GAME_MODEL_BLOB)
        return {}, [], None, False

    prior = None
    meta = _fetch_blob(CURVE_BLOB)
    if meta:
        try:
            payload = json.loads(meta)
            prior = Curve(a=float(payload["prior_a"]), b=float(payload["prior_b"]))
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("could not read the curve prior (%s)", exc)

    log.info("loaded %d game curves (prior=%s)", len(curves), prior is not None)
    return curves, names, prior, True


# ------------------------------------------------------------------- lifecycle

app = FastAPI(
    title="GPU Recommender API",
    version="0.2.0",
    description="Recommends the lowest-spec current GPU that hits a target frame rate for a given game.",
)


@app.on_event("startup")
def _startup() -> None:
    state.gpus, state.classified = load_gpus()
    state.curves, state.game_names, state.prior, state.curve_loaded = load_curve()
    state.gpu_names = sorted(gpu.name for gpu in state.gpus)
    state.figure_index, state.figures = load_figures()


# ----------------------------------------------------------------------- models


class RecommendRequest(BaseModel):
    """Input: a game plus the frame rate the user wants to hit."""

    game: str = Field(..., min_length=1, description="Title as it appears in games.csv")
    target_fps: int = Field(60, ge=30, le=360, description="Desired 1080p High FPS")
    resolution: Literal["1080p", "1440p", "4k"] = Field(
        "1080p", description="Target resolution (load-scaled from the 1080p measurements)"
    )
    segment: Literal["desktop", "laptop"] = Field("desktop", description="Which pool to recommend from")
    include_workstation: bool = Field(False, description="Allow workstation/pro cards")
    new_only: bool = Field(
        True,
        description="Prefer current-generation cards (2020+); older cards are only "
        "returned as a cheaper alternative, or when nothing current meets the target",
    )


class AlternativeGpu(BaseModel):
    """An older card that also meets the target, shown for context."""

    gpu: str
    g3d: int
    generation: str | None = None
    year: int | None = None
    availability: str | None = None


class RecommendResponse(BaseModel):
    game: str
    target_fps: int
    resolution: str
    required_g3d: float
    required_g3d_1080p: float
    resolution_factor: float
    recommended_gpu: str | None
    recommended_g3d: int | None
    gpu_form_factor: str | None = None
    gpu_market: str | None = None
    gpu_availability: str | None = None
    recommended_generation: str | None = None
    recommended_year: int | None = None
    legacy_fallback: bool = False
    cheaper_alternative: AlternativeGpu | None = None
    curve_source: str


class CurvePoint(BaseModel):
    fps: float
    required: float


class CurveResponse(BaseModel):
    game: str
    source: Literal["game", "prior"]
    resolution: str
    resolution_factor: float
    a: float
    b: float
    r2: float | None = None
    g3d_min: int | None = None
    g3d_max: int | None = None
    points: list[CurvePoint]


class FpsRequest(BaseModel):
    """Input for the second service: which game, on which GPU."""

    game: str = Field(..., min_length=1, description="Title as it appears in games.csv")
    gpu: str = Field(..., min_length=1, description="Exact GPU name from the catalogue")
    resolution: Literal["1080p", "1440p", "4k"] = Field(
        "1080p", description="Target resolution (load-scaled from the 1080p measurements)"
    )


class FpsResponse(BaseModel):
    game: str
    gpu: str
    gpu_g3d: int
    resolution: str
    resolution_factor: float
    predicted_fps: float
    predicted_fps_1080p: float
    curve_source: str
    fit_r2: float | None = None
    extrapolated: bool = False
    gpu_form_factor: str | None = None
    gpu_market: str | None = None
    gpu_availability: str | None = None


# ---------------------------------------------------------------------- routes


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    """Liveness probe. Kubernetes uses this for readiness and liveness checks."""
    return {
        "status": "ok",
        "gpus_loaded": len(state.gpus),
        "catalog": "classified" if state.classified else "raw",
        "curve": "loaded" if state.curve_loaded else "missing",
        "figures": len(state.figure_index),
        "emulator": EMULATOR or None,
    }


@app.get("/games")
def games() -> dict[str, Any]:
    """Game titles, for the UI's suggestion list."""
    return {"games": state.game_names}


@app.get("/gpus")
def gpus() -> dict[str, Any]:
    """GPU names, for the UI's suggestion list."""
    return {"gpus": state.gpu_names}


@app.get("/curve")
def curve(game: str, resolution: Literal["1080p", "1440p", "4k"] = "1080p") -> CurveResponse:
    """Fitted FPS -> required-score curve for one game (pooled prior when unknown)."""
    key = game.strip().lower()
    fit = state.curves.get(key)
    source: Literal["game", "prior"] = "game"
    if fit is None:
        fit, source = state.prior, "prior"
    if fit is None:
        raise HTTPException(status_code=503, detail="FPS curve unavailable - run the model notebook")

    factor = _resolution_factor(resolution)
    points = []
    for index in range(67):
        fps = 30.0 + 5.0 * index
        points.append(
            CurvePoint(
                fps=round(fps, 1),
                required=round(math.exp((math.log(fps) - fit.a) / fit.b) * factor, 1),
            )
        )
    return CurveResponse(
        game=game.strip(),
        source=source,
        resolution=resolution,
        resolution_factor=round(factor, 4),
        a=fit.a,
        b=fit.b,
        r2=fit.r2,
        g3d_min=fit.g3d_min,
        g3d_max=fit.g3d_max,
        points=points,
    )


@app.get("/figures")
def figures() -> dict[str, Any]:
    """Published analytics figures, in display order (from notebook 06)."""
    return {"figures": state.figure_index}


@app.get("/figures/{name}")
def figure(name: str) -> Response:
    """Serve one published figure as a PNG."""
    if not FIGURE_NAME.match(name) or name not in state.figures:
        raise HTTPException(status_code=404, detail=f"unknown figure: {name}")
    return Response(
        content=state.figures[name],
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


def _eligible(gpu: Gpu, request: RecommendRequest) -> bool:
    """Segment and market filters for a candidate GPU.

    Older generations are not filtered here: the recommend path prefers current
    cards and only reaches older ones as a cheaper alternative or a fallback.
    """
    if gpu.market == "workstation":
        if not request.include_workstation:
            return False
    elif gpu.market != "consumer":
        return False  # mining cards, engineering samples, ...
    if request.segment == "desktop":
        return gpu.form_factor == "desktop"
    return gpu.form_factor in ("laptop", "integrated")


def _curve_for(game: str) -> Curve | None:
    return state.curves.get(game.strip().lower())


def _required_g3d(request: RecommendRequest) -> tuple[float, float, float, str]:
    """Invert the curve -> (required, 1080p required, resolution factor, source)."""
    curve = _curve_for(request.game)
    source = "game"
    if curve is None:
        curve, source = state.prior, "prior"
    if curve is None:
        raise HTTPException(status_code=503, detail="FPS curve unavailable - run the model notebook")
    unscaled = math.exp((math.log(request.target_fps) - curve.a) / curve.b)
    factor = _resolution_factor(request.resolution)
    return unscaled * factor, unscaled, factor, source


def _is_current(gpu: Gpu) -> bool:
    """Current generation = released 2020 or later (the map's approximate year)."""
    return gpu.gen_year is not None and gpu.gen_year >= 2020


@app.post("/recommend", response_model=RecommendResponse)
def recommend(request: RecommendRequest) -> RecommendResponse:
    """Game + target FPS -> lowest-spec current GPU (older cards as an alternative)."""
    if not state.gpus:
        raise HTTPException(status_code=503, detail="GPU catalogue unavailable in the bucket")

    required, required_1080p, factor, curve_source = _required_g3d(request)

    pool = [gpu for gpu in state.gpus if _eligible(gpu, request)] if state.classified else state.gpus
    eligible = [gpu for gpu in pool if gpu.g3d_mark >= required]

    match: Gpu | None = None
    alternative: Gpu | None = None
    fallback = False
    if eligible:
        if request.new_only:
            current = [gpu for gpu in eligible if _is_current(gpu)]
            if current:
                match = current[0]
                older = [gpu for gpu in eligible if not _is_current(gpu)]
                if older and older[0].g3d_mark < match.g3d_mark:
                    alternative = older[0]
            else:
                # nothing current meets the target: fall back, but say so
                match = eligible[0]
                fallback = True
        else:
            match = eligible[0]

    return RecommendResponse(
        game=request.game,
        target_fps=request.target_fps,
        resolution=request.resolution,
        required_g3d=round(required, 1),
        required_g3d_1080p=round(required_1080p, 1),
        resolution_factor=round(factor, 4),
        recommended_gpu=match.name if match else None,
        recommended_g3d=match.g3d_mark if match else None,
        gpu_form_factor=match.form_factor if match else None,
        gpu_market=match.market if match else None,
        gpu_availability=match.availability if match else None,
        recommended_generation=match.generation if match else None,
        recommended_year=match.gen_year if match else None,
        legacy_fallback=fallback,
        cheaper_alternative=(
            AlternativeGpu(
                gpu=alternative.name,
                g3d=alternative.g3d_mark,
                generation=alternative.generation,
                year=alternative.gen_year,
                availability=alternative.availability,
            )
            if alternative
            else None
        ),
        curve_source=curve_source,
    )


@app.post("/fps", response_model=FpsResponse)
def fps(request: FpsRequest) -> FpsResponse:
    """Game + GPU -> predicted FPS (the inverse view of the same curve)."""
    if not state.curve_loaded:
        raise HTTPException(status_code=503, detail="FPS curve unavailable - run the model notebook")

    wanted = request.gpu.strip().lower()
    card = next((gpu for gpu in state.gpus if gpu.name.lower() == wanted), None)
    if card is None:
        raise HTTPException(status_code=404, detail=f"unknown GPU: {request.gpu}")

    curve = _curve_for(request.game)
    source = "game"
    if curve is None:
        curve, source = state.prior, "prior"
    if curve is None:
        raise HTTPException(status_code=503, detail="no per-game curve or prior available")

    predicted_1080p = min(math.exp(curve.a + curve.b * math.log(card.g3d_mark)), CLIP_FPS)
    factor = _resolution_factor(request.resolution)
    predicted = min(math.exp(curve.a + curve.b * math.log(card.g3d_mark / factor)), CLIP_FPS)
    extrapolated = bool(
        curve.g3d_min is not None
        and curve.g3d_max is not None
        and not (curve.g3d_min <= card.g3d_mark <= curve.g3d_max)
    )

    return FpsResponse(
        game=request.game,
        gpu=card.name,
        gpu_g3d=card.g3d_mark,
        resolution=request.resolution,
        resolution_factor=round(factor, 4),
        predicted_fps=round(predicted, 1),
        predicted_fps_1080p=round(predicted_1080p, 1),
        curve_source=source,
        fit_r2=curve.r2,
        extrapolated=extrapolated,
        gpu_form_factor=card.form_factor,
        gpu_market=card.market,
        gpu_availability=card.availability,
    )
