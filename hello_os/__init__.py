# -*- coding: utf-8 -*-
"""hello_os — Cognispheric Symbolic Language (CSL) package.

Re-exports the same public surface as the original flat ``hello_os.py``
(lines 1-594) so that ``from hello_os import CognitiveScroll`` works
identically to the old ``from hello_os import CognitiveScroll``.

Sub-modules
-----------
- **symbols** — constants, environment detection, shared imports
- **utils** — ``normalize``, ``to_numpy``, ``to_gpu``
- **core** — CSL operators, sentence engine
- **scroll** — cognitive scroll pipeline, demonstration
- **geometry** — 8D→4D→3D quasicrystal projection
- **resonance** — RLC circuit solver and electromagnetics helpers
"""

__version__ = "0.1.0"

# -- core public API (always available) -------------------------------------
from hello_os.symbols import GPU_AVAILABLE, SCIPY_AVAILABLE  # noqa: F401
from hello_os.utils import normalize, to_gpu, to_numpy  # noqa: F401
from hello_os.core import (  # noqa: F401
    Activation,
    CognitiveState,
    Compression,
    CSLOperator,
    CSLSentence,
    Loop,
    Memory,
    OperatorRegistry,
    Recursion,
    Source,
    Synthesis,
    Thread,
    Time,
    Triad,
)
from hello_os.scroll import (  # noqa: F401
    CognitiveScroll,
    demonstrate_csl,
)

__all__ = [
    # metadata
    "__version__",
    # symbols
    "GPU_AVAILABLE",
    "SCIPY_AVAILABLE",
    # utils
    "normalize",
    "to_numpy",
    "to_gpu",
    # core
    "CognitiveState",
    "CSLOperator",
    "Source",
    "Triad",
    "Recursion",
    "Memory",
    "Compression",
    "Loop",
    "Time",
    "Thread",
    "Activation",
    "Synthesis",
    "OperatorRegistry",
    "CSLSentence",
    "CognitiveScroll",
    "demonstrate_csl",
]
