# -*- coding: utf-8 -*-
"""CognitiveScroll pipeline and CSL demonstration.

Dependencies: hello_os.symbols, hello_os.utils, hello_os.core
"""

from hello_os.symbols import (
    GPU_AVAILABLE,
    HTML,
    FancyArrowPatch,
    animation,
    logger,
    plt,
)
from hello_os.utils import to_numpy
from hello_os.core import (
    Activation,
    CSLSentence,
    CognitiveState,
    Memory,
    OperatorRegistry,
    Recursion,
    Source,
    Triad,
    Compression,
    Loop,
    Time,
    Thread,
    Synthesis,
)

__all__ = [
    "CognitiveScroll",
    "demonstrate_csl",
]


class CognitiveScroll:
    def __init__(self):
        self.registry = OperatorRegistry()
        for op in [
            Source(),
            Triad(),
            Recursion(),
            Memory(),
            Compression(),
            Loop(),
            Time(),
            Thread(),
            Activation(),
            Synthesis(),
        ]:
            self.registry.register(op)
        self.full_trace: list[tuple] = []

    def process(self, input_seed: float = 42) -> CognitiveState:
        self.registry.reset_all()
        self.full_trace = []
        logger.info(" COGNITIVE SCROLL EXECUTION")
        logger.info("=" * 60)

        ops = self.registry.ops

        s1 = ops["∅"]()
        self.full_trace.append(("∅ Source", s1))

        s2 = ops["◬"](s1)
        self.full_trace.append(("◬ Triad", s2))

        s3 = ops["🜂"](s2)
        self.full_trace.append(("🜂 Recursion", s3))

        s4 = ops["μ"](s3)
        self.full_trace.append(("μ Memory", s4))

        s5 = ops["⧉"](s4)
        self.full_trace.append(("⧉ Compression", s5))

        s6 = ops["λ"](s5, iterations=3)
        self.full_trace.append(("λ Loop", s6))

        s7 = ops["⧖"](s6)
        self.full_trace.append(("⧖ Time", s7))

        s8 = ops["θ"](s5, s6, s7)
        self.full_trace.append(("θ Thread", s8))

        s9 = ops["✶"](s8)
        self.full_trace.append(("✶ Activation", s9))

        logger.info("=" * 60)
        logger.info(f" OUTPUT STATE: {s9}")
        return s9

    def visualize_scroll(self, save_path: str = "csl_scroll.png"):
        if not self.full_trace:
            return
        if plt is None:
            logger.warning("matplotlib not available — skipping visualize_scroll")
            return
        fig = plt.figure(figsize=(16, 10))
        gs = fig.add_gridspec(3, 3, hspace=0.3, wspace=0.3)
        ax_flow = fig.add_subplot(gs[0:2, :])
        ax_flow.set_xlim(-1, len(self.full_trace) + 1)
        ax_flow.set_ylim(-2, 2)
        ax_flow.set_title(
            "CSL Cognitive Scroll: Geometric Intelligence Pipeline",
            fontsize=16,
            weight="bold",
            pad=20,
        )
        ax_flow.axis("off")

        for i, (name, state) in enumerate(self.full_trace):
            x = i
            circle = plt.Circle(
                (x, 0),
                0.3,
                color=plt.cm.viridis(state.activation),
                ec="black",
                linewidth=2,
                zorder=3,
            )
            ax_flow.add_patch(circle)
            glyph = name.split()[0]
            ax_flow.text(
                x, 0, glyph, ha="center", va="center", fontsize=20, weight="bold"
            )
            op_name = " ".join(name.split()[1:])
            ax_flow.text(
                x, -0.6, op_name, ha="center", va="top", fontsize=9, style="italic"
            )
            info = f"α={state.activation:.2f}\nd={state.compression_depth}"
            ax_flow.text(
                x,
                0.6,
                info,
                ha="center",
                va="bottom",
                fontsize=7,
                family="monospace",
            )
            if i < len(self.full_trace) - 1:
                arrow = FancyArrowPatch(
                    (x + 0.35, 0),
                    (x + 0.65, 0),
                    arrowstyle="->",
                    mutation_scale=30,
                    linewidth=2,
                    color="black",
                )
                ax_flow.add_patch(arrow)

        ax_energy = fig.add_subplot(gs[2, 0])
        ax_energy.plot(
            [s.activation for _, s in self.full_trace], "o-", color="crimson"
        )
        ax_energy.set_title("Activation Energy")
        ax_energy.grid(alpha=0.3)
        ax_energy.set_ylim(0, 1.1)

        ax_depth = fig.add_subplot(gs[2, 1])
        ax_depth.bar(
            range(len(self.full_trace)),
            [s.compression_depth for _, s in self.full_trace],
            color="steelblue",
        )
        ax_depth.set_title("Compression Depth")

        ax_phase = fig.add_subplot(gs[2, 2])
        ax_phase.plot(
            [s.temporal_phase for _, s in self.full_trace], "s-", color="darkgreen"
        )
        ax_phase.set_title("Temporal Phase")
        ax_phase.grid(alpha=0.3)

        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        logger.info(f"Saved scroll visualization to {save_path}")
        plt.close()

    def animate_field_evolution(self, save_path: str = "csl_animation.gif"):
        if not self.full_trace:
            return None
        if plt is None or animation is None:
            logger.warning(
                "matplotlib not available — skipping animate_field_evolution"
            )
            return None
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

        def _update(frame):
            name, state = self.full_trace[frame]
            v = to_numpy(state.symbolic_vector)
            ax1.clear()
            ax1.plot(
                v,
                linewidth=3,
                color=plt.cm.plasma(frame / len(self.full_trace)),
            )
            ax1.fill_between(
                range(len(v)),
                0,
                v,
                alpha=0.3,
                color=plt.cm.plasma(frame / len(self.full_trace)),
            )
            ax1.set_title(
                f"{name}\nStage {frame + 1}/{len(self.full_trace)}",
                fontsize=14,
                weight="bold",
            )
            ax1.set_ylim(-1.5, 1.5)
            ax1.grid(alpha=0.3)
            ax1.axhline(0, color="black", linewidth=1)

            ax2.clear()
            min_len = min(len(v[::2]), len(v[1::2]))
            for j in range(max(0, frame - 3), frame + 1):
                _, s = self.full_trace[j]
                vp = to_numpy(s.symbolic_vector)
                ax2.scatter(
                    vp[::2][:min_len],
                    vp[1::2][:min_len],
                    alpha=0.3 + 0.7 * (j - max(0, frame - 3)) / 3,
                    s=50,
                    c=[plt.cm.plasma(j / len(self.full_trace))],
                )
            ax2.set_aspect("equal")
            ax2.set_xlim(-1.5, 1.5)
            ax2.set_ylim(-1.5, 1.5)
            ax2.grid(alpha=0.3)

        anim = animation.FuncAnimation(
            fig,
            _update,
            frames=len(self.full_trace),
            interval=800,
            repeat=True,
        )
        try:
            anim.save(save_path, writer="pillow", fps=2)
            logger.info(f"Saved animation to {save_path}")
        except Exception as e:
            logger.warning(f"Could not save animation: {e}")
        plt.close()
        if HTML is not None:
            return HTML(anim.to_jshtml())
        return None


# ============================================================================
# DEMONSTRATION
# ============================================================================


def demonstrate_csl():
    """Run the full CSL demonstration and return (scroll, animation_html)."""
    print("╔" + "═" * 78 + "╗")
    print("║" + " CSL: COGNISPHERIC SYMBOLIC LANGUAGE ".center(78) + "║")
    print("║" + " Geometric Intelligence Engine ".center(78) + "║")
    from hello_os.symbols import GPU_AVAILABLE as _gpu
    print("║" + f" {'GPU Accelerated' if _gpu else 'CPU Mode'} ".center(78) + "║")
    print("╚" + "═" * 78 + "╝")
    print()

    registry = OperatorRegistry()
    for op in [Source(), Triad(), Recursion(), Memory(), Activation()]:
        registry.register(op)

    print("\nEXAMPLE 1: Birth of Cognition")
    print("Sentence: ∅ ◬ 🜂")
    sentence1 = CSLSentence("∅ ◬ 🜂", registry)
    result1 = sentence1.execute()
    print(f"Result: {result1}")

    print("\nEXAMPLE 2: Memory Formation")
    print("Sentence: 🜂 μ ✶")
    sentence2 = CSLSentence("🜂 μ ✶", registry)
    result2 = sentence2.execute()
    print(f"Result: {result2}")

    print("\nEXAMPLE 3: Complete Cognitive Scroll")
    scroll = CognitiveScroll()
    scroll.process()

    print("\n" + "─" * 80)
    print(" CSL DEMONSTRATION COMPLETE")
    print("─" * 80)

    return scroll, None
