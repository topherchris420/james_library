"""Voice playback wrapper with robust fallback behavior."""

import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from rain_lab_chat._logging import get_logger

log = get_logger(__name__)

try:
    from rich_ui import status_indicator, supports_ansi
    _RICH_UI = True
    _ANSI_OK = supports_ansi()
except ImportError:
    _RICH_UI = False
    _ANSI_OK = True

try:
    import pyttsx3 as _pyttsx3
except (ImportError, OSError) as _exc:
    log.debug("pyttsx3 unavailable: %s", _exc)
    _pyttsx3 = None
pyttsx3 = _pyttsx3


class VoiceEngine:
    """Primary pyttsx3 playback with optional fallback to tts_module."""

    def __init__(self):

        self.enabled = False

        self.engine = None

        self.voice_id_by_character: Dict[str, str] = {}

        self.default_voice_id: Optional[str] = None

        self._fallback_tts: Any = None
        self._init_failed_permanently = False
        self._export_disabled = False
        self._warned_no_tts_backend = False
        self._init_fallback_backend()

        if pyttsx3 is None:
            return

        self._try_init_engine()

    _user_warned: bool = False  # class-level: only show one terminal warning

    def _safe_print(self, message: str) -> None:
        """Log warnings and surface the first failure visibly to the user."""
        log.warning("%s", message)
        if not VoiceEngine._user_warned:
            VoiceEngine._user_warned = True
            try:
                if _RICH_UI:
                    indicator = status_indicator("warning")
                    print(f"  {indicator} Voice: {message}", file=sys.stderr)
                elif _ANSI_OK:
                    print(f"\033[93m⚠ Voice: {message}\033[0m", file=sys.stderr)
                else:
                    print(f"Warning — Voice: {message}", file=sys.stderr)
            except Exception:
                pass  # never crash on warning output

    def _init_fallback_backend(self) -> None:
        """Initialize optional fallback TTS backend from tts_module."""

        try:
            from tts_module import get_tts

            self._fallback_tts = get_tts(enabled=True, backend="auto")
        except (ImportError, OSError) as exc:
            log.debug("Fallback TTS backend unavailable: %s", exc)
            self._fallback_tts = None

    def _try_init_engine(self) -> bool:
        """Attempt pyttsx3 initialization and voice mapping."""

        if self._init_failed_permanently:
            return False

        if pyttsx3 is None:
            self.engine = None
            self.enabled = False
            return False

        try:
            self.engine = pyttsx3.init()
            self._initialize_character_voices()
            self.enabled = True
            return True
        except Exception as e:
            self._safe_print(f"Voice engine unavailable: {e}")
            self.engine = None
            self.enabled = False
            self._init_failed_permanently = True
            return False

    def _initialize_character_voices(self):
        """Load Windows character voices and map them to known agents."""

        if not self.engine:
            return

        try:
            available_voices = self.engine.getProperty("voices") or []

        except (RuntimeError, OSError):
            available_voices = []

        male_voice_id = None

        female_voice_id = None

        for voice in available_voices:
            voice_name = (getattr(voice, "name", "") or "").lower()

            if "david" in voice_name and male_voice_id is None:
                male_voice_id = voice.id

            if "zira" in voice_name and female_voice_id is None:
                female_voice_id = voice.id

        current_voice_id = self.engine.getProperty("voice")

        self.default_voice_id = male_voice_id or female_voice_id or current_voice_id

        self.voice_id_by_character = {
            "James": male_voice_id or self.default_voice_id,
            "Luca": male_voice_id or self.default_voice_id,
            "Jasmine": female_voice_id or self.default_voice_id,
            "Elena": female_voice_id or self.default_voice_id,
        }

    def _voice_for_agent(self, agent_name: str) -> Optional[str]:
        """Return mapped voice id for known characters."""

        return self.voice_id_by_character.get(agent_name, self.default_voice_id)

    def speak(self, text: str, agent_name: Optional[str] = None):
        """Speak text synchronously via a subprocess.

        Each utterance runs in its own Python process so the Windows
        SAPI5 COM handle is always fresh — this avoids the pyttsx3
        singleton-cache bug where ``runAndWait()`` silently produces
        no audio after the first call.
        """

        if not text:
            return

        if pyttsx3 is None:
            self._speak_with_fallback(text, agent_name)
            return

        target_voice = self._voice_for_agent(agent_name or "")

        # Build a small self-contained script executed in a child process.
        script_lines = [
            "import pyttsx3",
            "e = pyttsx3.init()",
        ]
        if target_voice:
            script_lines.append(f"e.setProperty('voice', {target_voice!r})")
        script_lines.append(f"e.say({text!r})")
        script_lines.append("e.runAndWait()")
        script_lines.append("e.stop()")
        script = "\n".join(script_lines)

        try:
            subprocess.run(
                [sys.executable, "-c", script],
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self._safe_print("Voice subprocess timed out")
        except Exception as e:
            self._safe_print(f"Voice playback failed: {e}")
            self._speak_with_fallback(text, agent_name)

    def _speak_with_fallback(self, text: str, agent_name: Optional[str]) -> None:
        """Use tts_module backend when pyttsx3 is unavailable."""

        if self._fallback_tts is None:
            if not self._warned_no_tts_backend:
                self._safe_print("Voice unavailable: no fallback TTS backend is configured.")
                self._warned_no_tts_backend = True
            return

        try:
            self._fallback_tts.speak(text, agent_name=agent_name, async_mode=False)
        except Exception as e:
            self._safe_print(f"Fallback voice playback failed: {e}")

    @staticmethod
    def estimate_duration_ms(text: str) -> int:
        """Estimate speech duration for subtitle timing when no media metadata exists."""

        words = max(1, len(text.split()))
        words_per_minute = 165
        duration_ms = int((words / words_per_minute) * 60_000)
        return max(900, duration_ms)

    def export_to_file(self, text: str, agent_name: Optional[str], output_path: Path) -> bool:
        """Synthesize speech to a local WAV file for external visual clients."""

        if self._export_disabled:
            return False
        if pyttsx3 is None:
            return False
        if not text:
            return False

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            export_engine = pyttsx3.init()

            target_voice = self._voice_for_agent(agent_name or "")
            if target_voice:
                export_engine.setProperty("voice", target_voice)

            export_engine.save_to_file(text, str(output_path))
            export_engine.runAndWait()
            export_engine.stop()

            return output_path.exists() and output_path.stat().st_size > 0

        except Exception as e:
            self._safe_print(f"Voice export failed: {e}")
            self._export_disabled = True

            return False
