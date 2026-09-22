"""Optional local Laya adapter; no imports of the ML stack in the host runtime."""

import json
from pathlib import Path
import subprocess
import sys

from .contracts import JudgmentAnswer, JudgmentResult, JudgmentState, QuestionSet, QuestionType, valid_answers
from .state import contains_sensitive_material


class LayaJudgmentProvider:
    """Run a complete, explicitly supplied checkpoint in an offline child process.

    A separate interpreter permits Laya's torch/transformers dependencies to live
    in a dedicated environment. Each evaluation is cold and deadline bounded.
    """

    def __init__(self, checkpoint: str = "", *, device: str = "cpu", timeout: float = 30,
                 python: str = sys.executable):
        if device not in {"cpu", "cuda", "mps"}:
            raise ValueError("unsupported Laya device")
        if not 0 < timeout <= 300:
            raise ValueError("invalid Laya timeout")
        self.checkpoint = checkpoint
        self.device = device
        self.timeout = timeout
        self.python = python

    def evaluate(self, state: JudgmentState, questions: QuestionSet) -> JudgmentResult:
        def failure(code):
            return JudgmentResult("laya", state_hash=state.state_hash,
                                  question_set_version=questions.version, error_code=code)

        if contains_sensitive_material(state.canonical_text + json.dumps(questions.to_dict())):
            return failure("state_contains_secret")
        if not self.checkpoint or not Path(self.checkpoint).is_dir():
            return failure("provider_not_configured")
        payload = {"checkpoint": str(Path(self.checkpoint).resolve()), "device": self.device,
                   "state": state.canonical_text, "questions": questions.to_dict()}
        # Pass no API keys, proxy settings, HF tokens, or user Python import paths.
        import os
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "LD_LIBRARY_PATH")
               if key in os.environ}
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                   DO_NOT_TRACK="1", TOKENIZERS_PARALLELISM="false")
        try:
            process = subprocess.run(
                [self.python, str(Path(__file__).with_name("laya_worker.py"))],
                input=json.dumps(payload), text=True, capture_output=True, env=env,
                timeout=self.timeout, check=False,
            )
            if process.returncode or len(process.stdout) > 100_000:
                return failure("provider_internal_error")
            raw = json.loads(process.stdout)
            if raw.get("error") in {"provider_not_configured", "provider_input_too_large",
                                    "provider_internal_error", "provider_runtime_unsupported"}:
                return failure(raw["error"])
            return parse_laya_response(raw, state, questions)
        except subprocess.TimeoutExpired:
            return failure("provider_timeout")
        except OSError:
            return failure("provider_not_configured")
        except (ValueError, TypeError, KeyError, AttributeError):
            return failure("provider_malformed_response")


def parse_laya_response(raw: dict, state: JudgmentState, questions: QuestionSet) -> JudgmentResult:
    """Laya Noul confidence/action hints are not TypeSafe Noul or permission."""
    model = raw["fingerprint"]
    if not isinstance(model, str) or len(model) != 69 or not model.startswith("laya-"):
        raise ValueError("missing checkpoint fingerprint")
    int(model[5:], 16)
    payload = raw["prediction"]
    if set(payload["answers"]) != {q.question_id for q in questions.questions}:
        raise ValueError("invalid Laya answers")
    answers = []
    for question in questions.questions:
        item = payload["answers"][question.question_id]
        if item["type"] != question.type.value:
            raise ValueError("invalid Laya primitive")
        noul = question.type is QuestionType.NOUL
        if question.type is QuestionType.SCORE and item.get("legend") != {
            str(i): text for i, text in enumerate(question.levels)
        }:
            raise ValueError("invalid Laya rubric")
        answers.append(JudgmentAnswer(
            question.question_id, question.type, item[question.type.value],
            () if noul else tuple(item["probabilities"].items()),
            None if noul else item["confidence"],
        ))
    result = JudgmentResult("laya", model, tuple(answers), state.state_hash, questions.version)
    if not valid_answers(result, questions):
        raise ValueError("invalid Laya distribution")
    return result
