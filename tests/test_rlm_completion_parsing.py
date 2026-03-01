import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parent.parent / "rlm-main" / "rlm-main" / "rlm" / "__init__.py"
SPEC = importlib.util.spec_from_file_location("rain_local_rlm", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_decode_completion_body_standard_json():
    body = '{"choices":[{"message":{"content":"All good."}}]}'
    raw, text = MODULE._decode_completion_body(body)

    assert raw["choices"][0]["message"]["content"] == "All good."
    assert text == "All good."


def test_decode_completion_body_sse_dump():
    body = "\n".join(
        [
            'data: {"choices":[{"delta":{"content":"Hello "}}]}',
            'data: {"choices":[{"delta":{"content":"world"}}]}',
            "data: [DONE]",
        ]
    )

    raw, text = MODULE._decode_completion_body(body)

    assert "_raw_sse" in raw
    assert text == "Hello world"
