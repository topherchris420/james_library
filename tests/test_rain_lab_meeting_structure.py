import ast
from collections import Counter
from pathlib import Path


def test_rain_lab_meeting_has_no_duplicate_host_helpers():
    source = (Path(__file__).resolve().parent.parent / "rain_lab_meeting.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    counts = Counter(names)

    assert counts["_host_select_files"] == 1
    assert counts["_host_snippets"] == 1


def test_rain_lab_meeting_validates_external_setup_code():
    source = (Path(__file__).resolve().parent.parent / "rain_lab_meeting.py").read_text(encoding="utf-8")
    assert "def _resolve_setup_code" in source
    assert "compile(candidate, \"<tools_setup_code>\", \"exec\")" in source


def test_rain_lab_meeting_caps_model_calls_per_turn():
    source = (Path(__file__).resolve().parent.parent / "rain_lab_meeting.py").read_text(encoding="utf-8")
    assert "RAIN_MAX_CALLS_PER_TURN" in source
    assert "turn_model_calls >= self.max_model_calls_per_turn" in source
