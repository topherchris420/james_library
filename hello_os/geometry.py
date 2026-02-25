# -*- coding: utf-8 -*-
"""Geometric instruction primitives — 8D→4D→3D quasicrystal projection,
diffraction scoring, and parameter-space exploration.

Standalone module — does **not** depend on hello_os.core.
"""

import time
import warnings

import numpy as np

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Optional heavy deps (Colab / interactive environments)
# ---------------------------------------------------------------------------
try:
    from scipy.fftpack import fftn, fftshift
    _SCIPY_FFT = True
except ImportError:
    _SCIPY_FFT = False

try:
    import cupy as _cp
    _GPU = True
except ImportError:
    _GPU = False

__all__ = [
    "normalize_points",
    "generate_quasicrystal",
    "diffraction_and_score",
    "find_best_angles",
    "plot3d",
    "plot_diff",
    "quick_example",
]


# ============================================================================
# Core Functions
# ============================================================================


def normalize_points(p):
    """Centre and scale a point cloud to the unit ball."""
    p = p - p.mean(axis=0)
    p = p / (np.sqrt(np.sum(p ** 2, axis=1)).max() + 1e-8)
    return p


def generate_quasicrystal(N, a1, a2, size, use_gpu=None):
    """Generate 8D→4D→3D quasicrystal projection.

    Parameters
    ----------
    N : int
        Number of lattice points.
    a1 : float
        8D→4D rotation angle (radians).
    a2 : float
        4D→3D oblique projection angle (radians).
    size : int
        Integer lattice half-extent.
    use_gpu : bool or None
        If *None*, auto-detect CuPy availability.
    """
    if use_gpu is None:
        use_gpu = _GPU
    start = time.time()
    phi = (1 + np.sqrt(5)) / 2

    if use_gpu:
        pts = _cp.random.randint(-size, size + 1, (N, 8), dtype=_cp.int32).astype(
            _cp.float32
        )
    else:
        pts = np.random.randint(-size, size + 1, (N, 8)).astype(np.float32)

    c1, s1 = np.cos(a1), np.sin(a1)
    M1 = np.array(
        [
            [c1, s1, 0, 0, 1 / phi, 0, 0, 0],
            [-s1, c1, 0, 0, 0, 1 / phi, 0, 0],
            [0, 0, c1, s1, 0, 0, 1 / phi, 0],
            [0, 0, -s1, c1, 0, 0, 0, 1 / phi],
        ],
        dtype=np.float32,
    )

    c2, s2 = np.cos(a2), np.sin(a2)
    M2 = np.array(
        [[1, 0, 0, 0], [0, c2, -s2, 0], [0, s2, c2, 0]], dtype=np.float32
    )

    if use_gpu:
        pts = pts @ _cp.asarray(M1).T @ _cp.asarray(M2).T
        pts = _cp.asnumpy(pts)
    else:
        pts = pts @ M1.T @ M2.T

    pts = normalize_points(pts)
    return pts


def diffraction_and_score(pts, grid=128):
    """Compute diffraction pattern and quasicrystal quality score.

    Returns ``(slice2d, score)`` where *slice2d* is the central slice of the
    3-D FFT magnitude and *score* is a sharpness metric.
    """
    if not _SCIPY_FFT:
        raise ImportError(
            "scipy.fftpack is required for diffraction_and_score"
        )

    h, _ = np.histogramdd(pts, bins=grid, range=[[-1.1, 1.1]] * 3)
    fft = fftshift(fftn(h))
    mag = np.abs(fft)
    mag /= mag.max() + 1e-12
    slice2d = mag[:, :, grid // 2]

    top5 = np.partition(mag.ravel(), -5)[-5:]
    score = top5.mean() / (mag.mean() + 1e-12)
    return slice2d, score


def find_best_angles(resolution=10, points=5000, size=12, use_gpu=None):
    """Scan angle parameter space to find optimal quasicrystal configuration.

    Returns ``(best_a1, best_a2, best_score)``.
    """
    if use_gpu is None:
        use_gpu = _GPU
    best_score, best_a1, best_a2 = 0, 0, 0
    angle1_range = np.linspace(0.5, 0.8, resolution)
    angle2_range = np.linspace(0.7, 0.9, resolution)
    score_map = np.zeros((resolution, resolution))

    for i, a1 in enumerate(angle1_range):
        for j, a2 in enumerate(angle2_range):
            pts = generate_quasicrystal(points, a1, a2, size, use_gpu)
            _, score = diffraction_and_score(pts, grid=64)
            score_map[i, j] = score
            if score > best_score:
                best_score, best_a1, best_a2 = score, a1, a2

    return best_a1, best_a2, best_score


# ============================================================================
# Visualisation helpers (require plotly — degrade gracefully)
# ============================================================================

def _require_plotly():
    try:
        import plotly.graph_objects as go  # noqa: F401
        return go
    except ImportError:
        raise ImportError("plotly is required for visualisation helpers")


def plot3d(pts, mode="rainbow", title="Quasicrystal"):
    """Create 3D point-cloud visualisation (requires plotly)."""
    go = _require_plotly()
    x, y, z = pts.T
    if mode == "rainbow":
        color, cs = np.arctan2(y, x), "hsv"
    elif mode == "height":
        color, cs = z, "Viridis"
    else:
        color, cs = np.linalg.norm(pts, axis=1), "Plasma"

    fig = go.Figure(
        data=[
            go.Scatter3d(
                x=x,
                y=y,
                z=z,
                mode="markers",
                marker=dict(
                    size=1.7,
                    color=color,
                    colorscale=cs,
                    opacity=0.85,
                    colorbar=dict(title=mode),
                ),
            )
        ]
    )
    fig.update_layout(
        title=title,
        scene=dict(aspectmode="cube", bgcolor="black"),
        width=820,
        height=700,
        template="plotly_dark",
    )
    fig.show()


def plot_diff(slice2d):
    """Visualise diffraction pattern (requires plotly)."""
    go = _require_plotly()
    fig = go.Figure(
        go.Heatmap(z=np.log1p(slice2d), colorscale="Inferno", showscale=False)
    )
    fig.update_layout(
        title="Diffraction Pattern (log scale)",
        width=600,
        height=600,
        template="plotly_dark",
        xaxis_visible=False,
        yaxis_visible=False,
    )
    fig.show()


def quick_example(gpu=None):
    """Generate a quick example quasicrystal and display it."""
    if gpu is None:
        gpu = _GPU
    print("Generating example quasicrystal with optimal angles...")
    pts = generate_quasicrystal(15000, 0.628, 0.785, 14, gpu)
    diff, score = diffraction_and_score(pts)
    print(f"Score: {score:.4f}")
    plot3d(pts, "rainbow", f"Example Quasicrystal (Score: {score:.4f})")
    plot_diff(diff)
