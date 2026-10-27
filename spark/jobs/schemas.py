"""Explicit schemas for the raw Zenodo CSVs (dataset version 2026-10-03).

Declaring the schema avoids ``inferSchema=True``: that samples with
``samplingRatio=1.0`` (the whole file) on the driver and then re-scans, so each
CSV read costs an extra full pass. Notebooks 01 and 02 do four such reads per
run between them.

Types mirror what Spark's inference produced for this dataset (name/url text,
counts and FPS as integers, empties -> null in PERMISSIVE mode).
"""
from __future__ import annotations

from pyspark.sql import types as T

REFERENCE_GPUS = {
    'iris_xe': 'Intel Iris Xe',
    'radeon_780m': 'Radeon 780M',
    'gtx_1650': 'GeForce GTX 1650',
    'gtx_1660_super': 'GeForce GTX 1660 SUPER',
    'rtx_3060': 'GeForce RTX 3060',
    'rx_7600': 'Radeon RX 7600',
    'rtx_4060': 'GeForce RTX 4060',
    'rtx_5060': 'GeForce RTX 5060',
    'rtx_4070': 'GeForce RTX 4070',
    'rx_7800_xt': 'Radeon RX 7800 XT',
    'rtx_5070': 'GeForce RTX 5070',
    'rtx_4090': 'GeForce RTX 4090',
}

FPS_COLS = [f'fps_1080p_high_{key}' for key in REFERENCE_GPUS]

GAMES_SCHEMA = T.StructType([
    T.StructField('name', T.StringType()),
    T.StructField('release_year', T.IntegerType()),
    T.StructField('steam_appid', T.IntegerType()),
    T.StructField('min_gpu', T.StringType()),
    T.StructField('min_cpu', T.StringType()),
    T.StructField('min_ram_gb', T.IntegerType()),
    T.StructField('rec_gpu', T.StringType()),
    T.StructField('rec_cpu', T.StringType()),
    T.StructField('rec_ram_gb', T.IntegerType()),
    T.StructField('min_gpu_g3d', T.IntegerType()),
    T.StructField('rec_gpu_g3d', T.IntegerType()),
    T.StructField('engine_fps_cap', T.IntegerType()),
    *[T.StructField(col, T.IntegerType()) for col in FPS_COLS],
    T.StructField('page_url', T.StringType()),
])

GPUS_SCHEMA = T.StructType([
    T.StructField('name', T.StringType()),
    T.StructField('type', T.StringType()),
    T.StructField('g3d_mark', T.IntegerType()),
    T.StructField('page_url', T.StringType()),
])