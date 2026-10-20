"""Presentation constants for notebook 06 (matplotlib only)."""

from pathlib import Path

import matplotlib.pyplot as plt

PALETTE = ['#4f8cff', '#7c5cff', '#3ecf8e', '#f6c445', '#ff6b6b', '#9aa7c0']

# distinct colours for the demand levels (8+), no repeats
LEVEL_COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#17becf']


def setup_style() -> None:
    """Apply the report figure style once per notebook."""
    plt.rcParams.update({
        'figure.dpi': 110,
        'savefig.dpi': 150,
        'font.size': 9,
        'axes.grid': True,
        'grid.alpha': 0.25,
        'axes.spines.top': False,
        'axes.spines.right': False,
    })


def save(fig, path) -> None:
    """Save a figure tightly and report its size."""
    fig.tight_layout()
    path = Path(path)
    fig.savefig(path, bbox_inches='tight')
    print(f'saved {path} ({path.stat().st_size // 1024} KB)')
