import json
from pathlib import Path

from library_compiler import compile_library


def test_compile_library_builds_artifacts(tmp_path: Path):
    (tmp_path / "A.md").write_text(
        """
# Test Note
Energy is conserved.
Energy is not conserved in this toy sentence.
Equation: $E=mc^2$.
Block:
$$
a^2 + b^2 = c^2
$$
""",
        encoding="utf-8",
    )
    (tmp_path / "B.md").write_text("Physics bridges Geometry and Resonance.", encoding="utf-8")

    result = compile_library(str(tmp_path))
    out = Path(result["output_dir"])

    assert result["file_count"] == 2
    assert (out / "manifest.json").exists()
    assert (out / "equation_index.json").exists()
    assert (out / "grounded_quote_spans.json").exists()

    equations = json.loads((out / "equation_index.json").read_text(encoding="utf-8"))
    assert any("E=mc^2" in e["equation"] for e in equations)

    contradictions = json.loads((out / "contradiction_candidates.json").read_text(encoding="utf-8"))
    assert isinstance(contradictions, list)
