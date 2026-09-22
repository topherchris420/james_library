"""CLI Runner for RAIN <-> CIRCLE Experiment Protocol."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from .analysis import run_deterministic_analysis
from .bundle import save_experiment_bundle, verify_bundle_integrity
from .executor import SimulatedCircleExecutor
from .fixtures import (
    run_artifact_only_fixture,
    run_insufficient_sample_fixture,
    run_negative_control_fixture,
    run_positive_control_fixture,
    run_protocol_modification_fixture,
)
from .manifest import calculate_sha256
from .reasoning import assemble_experiment_analysis, design_experiment

ANSI_CYAN = "\033[96m"
ANSI_GREEN = "\033[92m"
ANSI_YELLOW = "\033[93m"
ANSI_RED = "\033[91m"
ANSI_DIM = "\033[90m"
ANSI_BOLD = "\033[1m"
ANSI_RESET = "\033[0m"


def _console_safe(text: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def print_experiment_report(
    manifest: dict[str, Any],
    result: dict[str, Any],
    analysis: dict[str, Any],
    bundle_path: Path | None = None,
) -> None:
    """Pretty-print a structured scientific report to the console."""
    conclusion = analysis["conclusion"]
    conclusion_color = (
        ANSI_GREEN if conclusion == "SUPPORTS" else (ANSI_RED if conclusion == "REFUTES" else ANSI_YELLOW)
    )

    stats = analysis["statistical_results"]
    effect = analysis["effect_sizes"]
    interval = analysis["confidence_intervals"]
    equivalence = stats["equivalence_test"]
    critique = analysis["adversarial_critique"]
    next_exp = analysis["recommended_next_experiment"]

    lines = [
        "",
        "=" * 70,
        f"{ANSI_BOLD}{ANSI_CYAN}  RAIN <-> CIRCLE EXPERIMENT PROTOCOL REPORT (V1 SIMULATED)  {ANSI_RESET}",
        "=" * 70,
        f"Experiment ID : {manifest['experiment_id']}",
        f"Trial ID      : {manifest['trial_id']}",
        f"Execution ID  : {result['execution_id']}",
        f"Manifest Hash : {result['manifest_sha256'][:16]}...{result['manifest_sha256'][-8:]}",
        f"Protocol Stat : {analysis.get('protocol_status', 'PREREGISTERED_VALID')}",
        f"Executor Type : {result['executor_type']} ({result['provenance']})",
        "-" * 70,
        f"{ANSI_BOLD}Question:{ANSI_RESET} {manifest['research_question']}",
        f"{ANSI_BOLD}Hypothesis:{ANSI_RESET} {manifest['hypothesis']}",
        "-" * 70,
        f"{ANSI_BOLD}Deterministic Statistics:{ANSI_RESET}",
        f"  * Sample size (n) : {stats['sample_size']}",
        f"  * Control mean    : {stats['mean_control']} (sd={stats['std_dev_control']})",
        f"  * Active mean     : {stats['mean_active']} (sd={stats['std_dev_active']})",
        f"  * Mean Difference : {effect['mean_difference']} ({effect.get('mean_difference_percent', 0.0):.2f}%)",
        f"  * Cohen's d       : {effect['cohens_d']}",
        f"  * Welch p-value   : {stats['p_value']:.6g} (alpha={manifest['preregistered_analysis']['alpha_threshold']})",
        (
            f"  * 95% Welch CI    : [{interval['lower_bound']:.4g}, {interval['upper_bound']:.4g}] ohms"
            if interval["lower_bound"] is not None else "  * 95% Welch CI    : not estimable"
        ),
        (
            f"  * Equivalence     : {equivalence['established']} within "
            f"+/-{equivalence['margin_ohms']} ohms "
            f"({equivalence['confidence_level']:.0%} interval)"
            if equivalence["margin_ohms"] is not None else "  * Equivalence     : no preregistered numeric margin"
        ),
        "-" * 70,
        f"{ANSI_BOLD}Artifact Discrimination:{ANSI_RESET}",
    ]
    art = analysis["artifact_analysis"]
    lines.extend([
        f"  * Phantom tested       : {art['phantom_tested']}",
        f"  * Phantom signal found : {art['phantom_signal_detected']}",
        f"  * Artifact explanation : {art['artifact_explanation_plausible']}",
    ])
    if art["artifact_flags"]:
        lines.append(f"  * {ANSI_YELLOW}Artifact flags{ANSI_RESET}       : {', '.join(art['artifact_flags'])}")
    lines.extend([
        "-" * 70,
        (
            f"{ANSI_BOLD}Scientific Conclusion:{ANSI_RESET} "
            f"{conclusion_color}{ANSI_BOLD}{conclusion}{ANSI_RESET} "
            "(statistical conclusion; not a probability of truth)"
        ),
        f"  {analysis['evidence_summary']}",
        "-" * 70,
        f"{ANSI_BOLD}Adversarial Critique:{ANSI_RESET}",
        f"  {critique['critique']}",
        "-" * 70,
        f"{ANSI_BOLD}Proposed Next Experiment (Requires Human Review):{ANSI_RESET}",
        f"  * Reason      : {next_exp['reason']}",
        f"  * Uncertainty : {next_exp['targeted_uncertainty']}",
        f"  * Next Hypoth : {next_exp['hypothesis']}",
        f"  * Control     : {next_exp['control']}",
        f"  * Measurement : {next_exp['measurement']}",
        f"  * Human Review: {ANSI_YELLOW}REQUIRED (never auto-executed){ANSI_RESET}",
    ])
    if bundle_path:
        lines.extend([
            "-" * 70,
            f"{ANSI_GREEN}Provenance Bundle Saved:{ANSI_RESET} {bundle_path.resolve()}",
        ])
    lines.append("=" * 70 + "\n")

    for line in lines:
        print(_console_safe(line))


def run_experiment_workflow(
    question: str,
    hypothesis: str,
    frequency_hz: float = 40.0,
    sample_count: int = 30,
    seed: int = 42,
    executor_name: str = "simulated",
    base_dir: Path | None = None,
    save_bundle: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path | None]:
    """Execute the full end-to-end RAIN ↔ CIRCLE experiment workflow."""
    if executor_name.lower() != "simulated":
        raise ValueError(
            f"Unsupported or prohibited executor '{executor_name}'. "
            "V1 supports ONLY 'simulated' execution. Hardware execution is disabled."
        )

    base_path = base_dir or Path.cwd()

    # 1. Design candidate manifest
    manifest = design_experiment(
        research_question=question,
        hypothesis=hypothesis,
        frequency_hz=frequency_hz,
        min_sample_size=20,
        alpha_threshold=0.05,
        effect_size_threshold=0.5,
        minimum_effect_ohms=15.0,
        expected_direction="decrease",
    )

    # 2. Deterministic serialization & SHA-256 calculation
    manifest_sha = calculate_sha256(manifest)

    # 3. Simulated CIRCLE execution
    executor = SimulatedCircleExecutor(seed=seed)
    scenario = {
        "sample_count": sample_count,
        "baseline_mean": 100.0,
        "active_effect": -16.0,
        "noise_std": 1.2,
        "phantom_effect": 0.05,
    }
    result = executor.run_trial(manifest, manifest_sha, custom_scenario=scenario)

    # 4. Deterministic statistical analysis
    stats = run_deterministic_analysis(manifest, result, manifest_sha)

    # 5. R.A.I.N. reasoning & adversarial critique
    analysis = assemble_experiment_analysis(manifest, result, stats)

    # 6. Save bundle
    bundle_path: Path | None = None
    if save_bundle:
        bundle_path = save_experiment_bundle(
            base_dir=base_path,
            manifest=manifest,
            result=result,
            analysis=analysis,
            logs=[f"Session started for {manifest['experiment_id']}", f"Trial executed with seed {seed}"],
        )

    return manifest, result, analysis, bundle_path


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for running experiments."""
    parser = argparse.ArgumentParser(
        prog="rain_lab.py experiment",
        description="R.A.I.N. <-> CIRCLE Reproducible Experiment Protocol (V1)",
    )
    parser.add_argument(
        "--question", "-q",
        type=str,
        default="Does 40Hz acoustic resonance alter phantom impedance?",
        help="Scientific research question",
    )
    parser.add_argument(
        "--hypothesis", "-H",
        type=str,
        default="40Hz stimulation induces an impedance drop of at least 15 ohms",
        help="Experimental hypothesis",
    )
    parser.add_argument(
        "--frequency",
        type=float,
        default=40.0,
        help="Resonance stimulation frequency in Hz (default: 40.0)",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=30,
        help="Number of simulated sample observations (default: 30)",
    )
    parser.add_argument(
        "--executor",
        type=str,
        default="simulated",
        help="Execution backend (V1 default: simulated; physical is disabled)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Deterministic RNG seed for simulation (default: 42)",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=".",
        help="Base directory for experiment bundles",
    )
    parser.add_argument(
        "--fixture",
        choices=["positive", "negative", "artifact", "insufficient", "protocol-mod"],
        default=None,
        help="Run a standard control verification fixture",
    )
    parser.add_argument(
        "--verify-bundle",
        type=str,
        default=None,
        help="Path to an existing experiment bundle directory to verify",
    )

    args = parser.parse_args(argv)

    if args.verify_bundle:
        target = Path(args.verify_bundle)
        print(_console_safe(f"Verifying bundle at {target}..."))
        res = verify_bundle_integrity(target)
        if res["valid"]:
            count = len(res["checked_files"])
            msg = f"{ANSI_GREEN}[OK] Bundle is valid and untampered ({count} files checked).{ANSI_RESET}"
            print(_console_safe(msg))
            return 0
        else:
            print(_console_safe(f"{ANSI_RED}[FAIL] Bundle verification failed:{ANSI_RESET}"))
            for err in res.get("mismatches", [res.get("error", "Unknown error")]):
                print(_console_safe(f"  * {err}"))
            return 1

    if args.fixture:
        fixtures_map = {
            "positive": run_positive_control_fixture,
            "negative": run_negative_control_fixture,
            "artifact": run_artifact_only_fixture,
            "insufficient": run_insufficient_sample_fixture,
            "protocol-mod": run_protocol_modification_fixture,
        }
        fn = fixtures_map[args.fixture]
        print(_console_safe(f"{ANSI_CYAN}Running fixture: {args.fixture}...{ANSI_RESET}"))
        manifest, result, analysis = fn(seed=args.seed)
        bundle_path = save_experiment_bundle(Path(args.out_dir), manifest, result, analysis)
        print_experiment_report(manifest, result, analysis, bundle_path)
        return 0

    try:
        manifest, result, analysis, bundle_path = run_experiment_workflow(
            question=args.question,
            hypothesis=args.hypothesis,
            frequency_hz=args.frequency,
            sample_count=args.samples,
            seed=args.seed,
            executor_name=args.executor,
            base_dir=Path(args.out_dir),
            save_bundle=True,
        )
        print_experiment_report(manifest, result, analysis, bundle_path)
        return 0
    except Exception as exc:
        print(f"{ANSI_RED}Experiment failed: {exc}{ANSI_RESET}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
