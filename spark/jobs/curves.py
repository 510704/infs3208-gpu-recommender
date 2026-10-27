"""FPS <-> required-score conversion (shared by notebook 06 and tests).

The model is ``ln(fps) = a + b * ln(g3d)``; the recommender inverts it, and the
figures re-use the same formula so the chart and the API can never drift.
"""
from __future__ import annotations

import math

# Every measurement in the dataset is 1080p High, so resolution is a documented
# GPU-load multiplier rather than a learned feature (see README/notebook 06).
RESOLUTIONS = {
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "4k": (3840, 2160),
}
RESOLUTION_EXPONENT = 0.75  # fragment-load scaling; 1440p ~1.54x, 4k ~2.83x


def resolution_factor(resolution: str, exponent: float = RESOLUTION_EXPONENT) -> float:
    """Relative GPU load of a resolution versus 1080p (1080p -> 1.0)."""
    width, height = RESOLUTIONS[resolution]
    return ((width * height) / (1920 * 1080)) ** exponent



def required_score(fps: float, a: float, b: float) -> float:
    """Score needed to hit ``fps`` on a curve with coefficients ``a`` and ``b``."""
    return math.exp((math.log(fps) - a) / b)


def predicted_fps(g3d: float, a: float, b: float) -> float:
    """FPS predicted for ``g3d`` on a curve with coefficients ``a`` and ``b``."""
    return math.exp(a + b * math.log(g3d))


def curve_points(a: float, b: float, start: float = 30.0, stop: float = 360.0, step: float = 5.0):
    """Sampled ``{fps, required}`` points for charting (default 67 points)."""
    points = []
    fps = start
    while fps <= stop + 1e-9:
        points.append({'fps': round(fps, 1), 'required': round(required_score(fps, a, b), 1)})
        fps += step
    return points


def required_array(fps, a: float, b: float):
    """Vectorised :func:`required_score` for numpy arrays (used by figure 08)."""
    import numpy as np

    values = np.asarray(fps, dtype=float)
    return np.exp((np.log(values) - a) / b)
