# -*- coding: utf-8 -*-
"""Shared utility helpers for hello_os.

Dependencies: hello_os.symbols (leaf)
"""

from hello_os.symbols import GPU_AVAILABLE, cp, xp

__all__ = ["normalize", "to_numpy", "to_gpu"]


def normalize(x, epsilon=1e-12):
    """Stable vector normalization."""
    norm = xp.linalg.norm(x)
    return x / xp.maximum(norm, epsilon)


def to_numpy(x):
    """Convert GPU array to numpy if needed."""
    if GPU_AVAILABLE and isinstance(x, cp.ndarray):
        return cp.asnumpy(x)
    return x


def to_gpu(x):
    """Convert numpy to GPU if available."""
    if GPU_AVAILABLE:
        return cp.asarray(x)
    return x
