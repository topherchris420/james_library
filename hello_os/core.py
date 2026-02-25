# -*- coding: utf-8 -*-
"""CSL (Cognispheric Symbolic Language) — core operators, sentence engine,
and cognitive scroll pipeline.

Dependencies: hello_os.symbols, hello_os.utils
"""

from hello_os.symbols import (
    GPU_AVAILABLE,
    HTML,
    SCIPY_AVAILABLE,
    FancyArrowPatch,
    Optional,
    animation,
    dataclass,
    deque,
    logger,
    np,
    plt,
    re,
    xp,
)
from hello_os.utils import normalize, to_gpu, to_numpy

# Conditionally import fftconvolve
if SCIPY_AVAILABLE:
    from hello_os.symbols import fftconvolve

__all__ = [
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
]


# ============================================================================
# COGNITIVE STATE
# ============================================================================


@dataclass
class CognitiveState:
    __slots__ = (
        "symbolic_vector",
        "activation",
        "temporal_phase",
        "compression_depth",
    )
    symbolic_vector: xp.ndarray
    activation: float
    temporal_phase: float
    compression_depth: int

    def __repr__(self):
        return (
            f"State(act={self.activation:.2f}, "
            f"phase={self.temporal_phase:.2f}, "
            f"depth={self.compression_depth})"
        )


# ============================================================================
# CSL OPERATORS
# ============================================================================


class CSLOperator:
    def __init__(self, glyph: str, name: str):
        self.glyph = glyph
        self.name = name

    def __call__(self, state: Optional[CognitiveState] = None) -> CognitiveState:
        raise NotImplementedError

    def reset(self):
        pass

    def __repr__(self):
        return f"{self.glyph} ({self.name})"


class Source(CSLOperator):
    def __init__(self, rng_seed: int = 42):
        super().__init__("∅", "Source")
        xp.random.seed(rng_seed)

    def __call__(self, state: Optional[CognitiveState] = None) -> CognitiveState:
        vec = xp.random.randn(64) * 0.1
        return CognitiveState(
            symbolic_vector=vec.astype(xp.float32),
            activation=0.1,
            temporal_phase=0.0,
            compression_depth=0,
        )


class Triad(CSLOperator):
    def __init__(self):
        super().__init__("◬", "Triad")

    def __call__(self, state: Optional[CognitiveState] = None) -> CognitiveState:
        if state is None:
            state = Source()()
        v = state.symbolic_vector
        triad = (xp.roll(v, 1) + xp.roll(v, -1) + v) / 3.0
        return CognitiveState(
            symbolic_vector=triad,
            activation=state.activation * 1.5,
            temporal_phase=state.temporal_phase,
            compression_depth=state.compression_depth + 1,
        )


class Recursion(CSLOperator):
    def __init__(self):
        super().__init__("🜂", "Recursion")

    def __call__(self, state: Optional[CognitiveState] = None) -> CognitiveState:
        if state is None:
            state = Source()()
        v = state.symbolic_vector
        if SCIPY_AVAILABLE and not GPU_AVAILABLE:
            v_np = to_numpy(v)
            conv = fftconvolve(v_np, v_np[::-1], mode="same")
            conv = to_gpu(conv)
        else:
            conv = xp.correlate(v, v, mode="same")
        field = v + 0.3 * xp.tanh(conv)
        return CognitiveState(
            symbolic_vector=normalize(field),
            activation=min(state.activation * 2.0, 1.0),
            temporal_phase=state.temporal_phase + 0.1,
            compression_depth=state.compression_depth,
        )


class Memory(CSLOperator):
    def __init__(self, window_size: int = 5):
        super().__init__("μ", "Memory")
        self.window_size = window_size
        self.trace = deque(maxlen=window_size)

    def reset(self):
        self.trace.clear()

    def __call__(self, state: Optional[CognitiveState] = None) -> CognitiveState:
        if state is None:
            state = Source()()
        self.trace.append(to_numpy(state.symbolic_vector.copy()))
        if len(self.trace) > 1:
            memory_field = to_gpu(np.mean(self.trace, axis=0))
            integrated = 0.7 * state.symbolic_vector + 0.3 * memory_field
        else:
            integrated = state.symbolic_vector
        return CognitiveState(
            symbolic_vector=integrated,
            activation=state.activation,
            temporal_phase=state.temporal_phase,
            compression_depth=state.compression_depth,
        )


class Compression(CSLOperator):
    def __init__(self):
        super().__init__("⧉", "Compression")

    def __call__(self, state: Optional[CognitiveState] = None) -> CognitiveState:
        if state is None:
            state = Source()()
        v = state.symbolic_vector
        if len(v) % 2 != 0:
            v = v[:-1]
        pairs = v.reshape(-1, 2)
        compressed = pairs.mean(axis=1)
        reconstructed = xp.repeat(compressed, 2)
        if len(reconstructed) < len(state.symbolic_vector):
            reconstructed = xp.pad(reconstructed, (0, 1), mode="edge")
        return CognitiveState(
            symbolic_vector=reconstructed,
            activation=state.activation * 1.2,
            temporal_phase=state.temporal_phase,
            compression_depth=state.compression_depth + 1,
        )


class Loop(CSLOperator):
    def __init__(self):
        super().__init__("λ", "Loop")

    def __call__(
        self, state: Optional[CognitiveState] = None, iterations: int = 3
    ) -> CognitiveState:
        if state is None:
            state = Source()()
        v = state.symbolic_vector
        for _ in range(iterations):
            v = 0.8 * v + 0.2 * xp.tanh(v)
        return CognitiveState(
            symbolic_vector=normalize(v),
            activation=state.activation,
            temporal_phase=state.temporal_phase + 0.05 * iterations,
            compression_depth=state.compression_depth,
        )


class Time(CSLOperator):
    def __init__(self):
        super().__init__("⧖", "Time")

    def __call__(
        self, state: Optional[CognitiveState] = None, delta: float = 0.2
    ) -> CognitiveState:
        if state is None:
            state = Source()()
        decay = xp.exp(xp.float32(-0.1 * delta))
        return CognitiveState(
            symbolic_vector=state.symbolic_vector * decay,
            activation=state.activation * 0.95,
            temporal_phase=state.temporal_phase + delta,
            compression_depth=state.compression_depth,
        )


class Thread(CSLOperator):
    def __init__(self):
        super().__init__("θ", "Thread")
        self.narrative = []

    def reset(self):
        self.narrative.clear()

    def __call__(self, *states: CognitiveState) -> CognitiveState:
        if not states:
            return Source()()
        weights = xp.exp(-0.3 * xp.arange(len(states))[::-1])
        weights /= weights.sum()
        vectors = xp.stack([s.symbolic_vector for s in states])
        field = xp.sum(vectors * weights[:, None], axis=0)
        avg_act = float(xp.mean(xp.array([s.activation for s in states])))
        return CognitiveState(
            symbolic_vector=field,
            activation=avg_act,
            temporal_phase=states[-1].temporal_phase,
            compression_depth=max(s.compression_depth for s in states),
        )


class Activation(CSLOperator):
    def __init__(self):
        super().__init__("✶", "Activation")

    def __call__(self, state: Optional[CognitiveState] = None) -> CognitiveState:
        if state is None:
            state = Source()()
        v = state.symbolic_vector
        threshold = xp.percentile(xp.abs(v), 75)
        activated = xp.where(xp.abs(v) > threshold, v, v * 0.1)
        return CognitiveState(
            symbolic_vector=normalize(activated),
            activation=1.0,
            temporal_phase=state.temporal_phase,
            compression_depth=state.compression_depth,
        )


class Synthesis(CSLOperator):
    def __init__(self):
        super().__init__("⊕", "Synthesis")

    def __call__(self, *states: CognitiveState) -> CognitiveState:
        if not states:
            return Source()()
        stacked = xp.stack([s.symbolic_vector for s in states])
        signs = xp.sign(stacked.mean(axis=0))
        log_mean = xp.log(xp.abs(stacked) + 1e-8).mean(axis=0)
        synthesized = signs * xp.exp(log_mean)
        return CognitiveState(
            symbolic_vector=normalize(synthesized),
            activation=float(
                xp.mean(xp.array([s.activation for s in states]))
            ),
            temporal_phase=float(
                xp.mean(xp.array([s.temporal_phase for s in states]))
            ),
            compression_depth=int(
                xp.mean(xp.array([s.compression_depth for s in states]))
            ),
        )


# ============================================================================
# OPERATOR REGISTRY
# ============================================================================


class OperatorRegistry:
    def __init__(self):
        self.ops: dict[str, CSLOperator] = {}

    def register(self, op: CSLOperator):
        if op.glyph in self.ops:
            logger.warning(
                f"Overwriting existing operator for glyph: {op.glyph}"
            )
        self.ops[op.glyph] = op

    def get(self, glyph: str):
        return self.ops.get(glyph)

    def reset_all(self):
        for op in self.ops.values():
            op.reset()

    def __getitem__(self, glyph: str) -> CSLOperator:
        return self.ops[glyph]


# ============================================================================
# CSL SENTENCE ENGINE
# ============================================================================


class CSLSentence:
    def __init__(self, expression: str, registry: OperatorRegistry):
        self.expression = expression
        self.registry = registry
        self.trace: list[tuple] = []

    def execute(self) -> CognitiveState:
        self.trace = []
        tokens = re.findall(r"[∅◬🜂⧉⧖✶⊕μλθ]", self.expression)

        if not tokens:
            logger.warning("No valid glyphs found in expression")
            return Source()()

        state = None
        for glyph in tokens:
            op = self.registry.get(glyph)
            if op is None:
                logger.warning(f"Unknown glyph: {glyph}")
                continue
            if state is None:
                state = op()
            else:
                state = op(state)
            self.trace.append((glyph, state))

        return state

    def visualize_trace(self, save_path=None):
        if not self.trace:
            logger.error("No trace available. Execute first.")
            return
        if plt is None:
            logger.warning("matplotlib not available — skipping visualize_trace")
            return

        fig, axes = plt.subplots(
            2, len(self.trace), figsize=(4 * len(self.trace), 8)
        )
        if len(self.trace) == 1:
            axes = axes.reshape(2, 1)

        for i, (glyph, state) in enumerate(self.trace):
            v = to_numpy(state.symbolic_vector)
            ax1 = axes[0, i]
            ax1.plot(v, linewidth=2, color=plt.cm.viridis(state.activation))
            ax1.set_title(
                f"{glyph}\nActivation: {state.activation:.2f}",
                fontsize=12,
                weight="bold",
            )
            ax1.set_ylabel("Symbolic Magnitude")
            ax1.set_ylim(-1.5, 1.5)
            ax1.grid(alpha=0.3)
            ax1.axhline(0, color="black", linewidth=0.5)

            ax2 = axes[1, i]
            x, y = v[::2], v[1::2]
            min_len = min(len(x), len(y))
            ax2.scatter(
                x[:min_len],
                y[:min_len],
                c=np.arange(min_len),
                cmap="plasma",
                s=100,
                alpha=0.6,
                edgecolors="black",
            )
            ax2.set_title(
                f"Phase Space\nDepth: {state.compression_depth}", fontsize=10
            )
            ax2.set_aspect("equal")
            ax2.grid(alpha=0.3)

        plt.tight_layout()
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches="tight")
            logger.info(f"Saved visualization to {save_path}")
        else:
            plt.show()
