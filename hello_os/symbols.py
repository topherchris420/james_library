# -*- coding: utf-8 -*-
"""Symbolic constants, imports, and environment detection for hello_os.

This is the leaf module — no internal dependencies.
"""

# MIT License — Copyright (c) 2025 Christopher Woodyard
# See hello_os.py (root) for full license text.

import logging
import re
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Optional heavy dependencies — gracefully degrade when absent
# ---------------------------------------------------------------------------

# Matplotlib (may be missing in headless CI)
try:
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch
    import matplotlib.animation as animation
    MPL_AVAILABLE = True
except ImportError:  # pragma: no cover
    plt = None  # type: ignore[assignment]
    FancyArrowPatch = None  # type: ignore[assignment,misc]
    animation = None  # type: ignore[assignment]
    MPL_AVAILABLE = False

# IPython (only in notebooks / Colab)
try:
    from IPython.display import HTML
except ImportError:  # pragma: no cover
    HTML = None  # type: ignore[assignment,misc]

# GPU acceleration via CuPy
try:
    import cupy as cp

    GPU_AVAILABLE = True
    xp = cp
except ImportError:
    GPU_AVAILABLE = False
    xp = np
    cp = None  # type: ignore[assignment]

# Fast convolution via SciPy
try:
    from scipy.signal import fftconvolve

    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    fftconvolve = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("CSL")

# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------
__all__ = [
    # numpy / array backend
    "np",
    "xp",
    "cp",
    "GPU_AVAILABLE",
    # scipy
    "SCIPY_AVAILABLE",
    "fftconvolve",
    # matplotlib
    "plt",
    "FancyArrowPatch",
    "animation",
    "MPL_AVAILABLE",
    # IPython
    "HTML",
    # stdlib re-exports used across modules
    "dataclass",
    "Optional",
    "Dict",
    "List",
    "deque",
    "re",
    "logger",
]
