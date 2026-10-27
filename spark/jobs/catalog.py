"""Catalogue rules shared by notebooks 03 and 05.

``GENERATIONS`` is the curated age map (the dataset has no release dates); the
order is significant - the first matching pattern wins. ``TIER_BOUNDS`` are the
demand-tier boundaries used when discretising ``required_g3d`` for rule mining.
"""
from __future__ import annotations

TIER_BOUNDS = (2610, 6866, 17008, 26918)

GENERATIONS = [
    (r'(?i)\bradeon ai pro\b', 'Radeon AI Pro', 2025),
    (r'(?i)\brtx pro\b', 'RTX Pro', 2024),
    (r'(?i)\brtx \d{3,4}[a-z]? (?:ada|generation)\b|\brtx a\d{3,4}[a-z]*\b', 'RTX Ada workstation', 2023),
    (r'(?i)\brtx 50\d{2}[a-z]*\b', 'RTX 50 (Blackwell)', 2025),
    (r'(?i)\brtx 40\d{2}[a-z]*\b', 'RTX 40 (Ada)', 2022),
    (r'(?i)\brtx 30\d{2}[a-z]*\b', 'RTX 30 (Ampere)', 2020),
    (r'(?i)\brtx 20\d{2}[a-z]*\b', 'RTX 20 (Turing)', 2018),
    (r'(?i)\bgtx 16\d{2}[a-z]*\b', 'GTX 16 (Turing)', 2019),
    (r'(?i)\bgtx 10\d{2}[a-z]*\b', 'GTX 10 (Pascal)', 2016),
    (r'(?i)\bquadro rtx\b', 'Quadro RTX', 2018),
    (r'(?i)\bquadro (?:k|m|p)\d', 'Quadro (Kepler-Pascal)', 2015),
    (r'(?i)\btesla\b', 'Tesla', 2014),
    (r'(?i)\btitan\b', 'Titan', 2017),
    (r'(?i)\brx 9\d{3}[a-z]*\b', 'RX 9000 (RDNA 4)', 2025),
    (r'(?i)\brx 7\d{3}[a-z]*\b', 'RX 7000 (RDNA 3)', 2022),
    (r'(?i)\brx 6\d{3}[a-z]*\b', 'RX 6000 (RDNA 2)', 2020),
    (r'(?i)\brx 5\d{3}[a-z]*\b', 'RX 5000 (RDNA)', 2019),
    (r'(?i)\bradeon pro w\d{3,4}[a-z]*\b', 'Radeon Pro (RDNA)', 2023),
    (r'(?i)\bradeon pro\b', 'Radeon Pro (GCN)', 2016),
    (r'(?i)\bradeon vii\b', 'Radeon VII', 2019),
    (r'(?i)\bvega\b', 'Vega', 2017),
    (r'(?i)\binstinct\b|\bmi\d{2,3}\b', 'Instinct', 2018),
    (r'(?i)\bfirepro\b', 'FirePro', 2013),
    (r'(?i)\brx (?:4|5)\d{2}[a-z]*\b|\br[257] \d{3}[a-z]*\b|\br9 \d{3}[a-z]*\b|fury', 'Radeon GCN', 2016),
    (r'(?i)\barc pro\b', 'Arc Pro', 2024),
    (r'(?i)\barc [ab]\d{3}[a-z]*\b', 'Intel Arc', 2022),
    (r'(?i)\biris xe\b', 'Iris Xe', 2020),
    (r'(?i)\biris plus\b', 'Iris Plus', 2019),
    (r'(?i)\bradeon (?:6|7|8)\d{3}[ms]?\b', 'Radeon iGPU', 2023),
    (r'(?i)\bradeon graphics\b', 'Radeon iGPU', 2020),
    (r'(?i)\buhd graphics\b', 'Intel UHD', 2017),
    (r'(?i)\bhd graphics\b|\bhd \d{3,4}\b', 'Intel HD / Radeon HD', 2012),
    (r'(?i)\bnvs\b', 'NVS', 2010),
    (r'(?i)\bt(?:400|600|1000|1200|2000)\b', 'T-series workstation', 2020),
    (r'(?i)\ba10g?\b|\ba100\b|\bh100\b|\bl40\b', 'Data-center', 2021),
    (r'(?i)\bgeforce mx\d*\b', 'GeForce MX', 2019),
    (r'(?i)\busb display|display-\d+', 'Display adapter', 2015),
    (r'(?i)\bgeforce (?:2|3|4|7|8|9)\d{2}\b|\bgtx \d{3}\b|\bgts? \d{3}\b', 'Legacy GeForce', 2014),
]


def match_generation(name: str) -> tuple[str | None, int | None]:
    """Return ``(family, year)`` for a GPU name (pure Python, for tests)."""
    import re

    for pattern, family, year in GENERATIONS:
        if re.search(pattern, name):
            return family, year
    return None, None


def add_generation(frame):
    """Add ``generation``, ``gen_year``, ``is_legacy`` and ``availability``.

    Expects the catalogue frame to already have ``name`` and ``form_factor``.
    """
    from pyspark.sql import functions as F

    gen_expr = year_expr = None
    for pattern, family, year in GENERATIONS:
        cond = F.col('name').rlike(pattern)
        gen_expr = F.when(cond, F.lit(family)) if gen_expr is None else gen_expr.when(cond, F.lit(family))
        year_expr = F.when(cond, F.lit(year)) if year_expr is None else year_expr.when(cond, F.lit(year))

    return (
        frame
        .withColumn('generation', gen_expr)
        .withColumn('gen_year', year_expr)
        .withColumn('is_legacy', (F.col('gen_year') <= 2019).cast('int'))
        .withColumn('availability',
            F.when(F.col('form_factor') == 'integrated', 'n/a')
             .when(F.col('gen_year').isNull(), 'unknown')
             .when(F.col('gen_year') >= 2020, 'current')
             .when(F.col('gen_year') >= 2016, 'aging')
             .otherwise('legacy_secondhand'))
    )


def band(column: str, spec):
    """CASE WHEN chain from ``[(condition, label), ...]`` (notebook 05)."""
    from pyspark.sql import functions as F

    expr = None
    for condition, label in spec:
        expr = F.when(condition, F.lit(label)) if expr is None else expr.when(condition, F.lit(label))
    return expr
