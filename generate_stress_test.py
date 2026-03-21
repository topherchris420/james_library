"""Generate a random 3-SAT formula at the phase-transition threshold (alpha ~= 4.26).

Usage:
    python generate_stress_test.py          # defaults to N=20
    python generate_stress_test.py --vars 50
"""

import argparse
import json
import random


CRITICAL_RATIO = 4.26


def generate_3sat(num_vars: int, seed: int | None = None) -> str:
    """Return a human-readable 3-SAT formula string.

    Each clause contains exactly 3 literals drawn (without replacement within
    a clause) from variables V1..V<num_vars>, each independently negated with
    probability 0.5.  The number of clauses is int(4.26 * num_vars).
    """
    if num_vars < 3:
        raise ValueError("Need at least 3 variables for 3-SAT")

    rng = random.Random(seed)
    num_clauses = int(CRITICAL_RATIO * num_vars)
    clauses = []

    for _ in range(num_clauses):
        vars_chosen = rng.sample(range(1, num_vars + 1), 3)
        literals = []
        for v in vars_chosen:
            if rng.random() < 0.5:
                literals.append(f"(NOT V{v})")
            else:
                literals.append(f"V{v}")
        clauses.append(f"({' OR '.join(literals)})")

    return " AND ".join(clauses)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a random 3-SAT stress test")
    parser.add_argument("--vars", type=int, default=20, help="Number of variables (default: 20)")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    args = parser.parse_args()

    formula = generate_3sat(args.vars, seed=args.seed)
    payload = {"formula": formula}

    out_file = f"stress_test_{args.vars}_vars.json"
    with open(out_file, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"Wrote {out_file} ({args.vars} vars, {int(CRITICAL_RATIO * args.vars)} clauses)")
