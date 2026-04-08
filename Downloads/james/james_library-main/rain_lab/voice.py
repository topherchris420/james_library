"""Voice engine — pyttsx3 primary, edge-tts fallback, silent mode."""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from pathlib import Path
from typing import Dict, Optional

# Optional TTS backends
try:
    import pyttsx3 as _pyttsx3
except Exception:
    _pyttsx3 = None

pyttsx3 = _pyttsx3

try:
    import edge_tts as _edge_tts
except Exception:
    _edge_tts = None

edge_tts = _edge_tts


def _safe_console_print(message: str) -> None:
    """Print a warning without crashing on non-UTF-8 Windows consoles."""
    try:
        print(message)
    except UnicodeEncodeError:
        fallback = message.encode("ascii", errors="ignore").decode("ascii").lstrip()
        print(fallback or "Console output contained unsupported characters.")


class VoiceEngine:
    """Voice wrapper with pyttsx3 first, edge-tts fallback, then silent mode."""

    EDGE_VOICE_BY_CHARACTER = {
        "James": "en-US-GuyNeural",
        "Luca": "en-US-GuyNeural",
        "Jasmine": "en-US-AriaNeural",
        "Elena": "en-US-AriaNeural",
    }

    def __init__(self):
        self.enabled = False
        self.export_enabled = False
        self.backend = "silent"
        self.engine = None
        self.voice_id_by_character: Dict[str, str] = {}
        self.default_voice_id: Optional[str] = None

        if pyttsx3 is not None:
            try:
                self.engine = pyttsx3.init()
                self._initialize_character_voices()
                self.enabled = True
                self.export_enabled = True
                self.backend = "pyttsx3"
                return
            except Exception as e:
                _safe_console_print(f"\u26a0\ufe0f  Voice engine unavailable: {e}")
                self.engine = None
                self.enabled = False

        if edge_tts is not None:
            self.enabled = True
            self.export_enabled = True
            self.backend = "edge-tts"

    def _initialize_character_voices(self):
        """Load Windows character voices and map them to known agents."""
        if not self.engine:
            return

        try:
            available_voices = self.engine.getProperty("voices") or []
        except Exception:
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
        return self.voice_id_by_character.get(agent_name, self.default_voice_id)

    def _edge_voice_for_agent(self, agent_name: Optional[str]) -> str:
        return self.EDGE_VOICE_BY_CHARACTER.get(agent_name or "", "en-US-AriaNeural")

    async def _save_edge_tts_audio(self, text: str, agent_name: Optional[str], output_path: Path) -> Path:
        communicate = edge_tts.Communicate(text, self._edge_voice_for_agent(agent_name))
        await communicate.save(str(output_path))
        return output_path

    def _export_edge_tts_audio(self, text: str, agent_name: Optional[str], output_path: Path) -> Optional[Path]:
        if edge_tts is None:
            return None

        target_path = output_path.with_suffix(".mp3")
        target_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            return asyncio.run(self._save_edge_tts_audio(text, agent_name, target_path))
        except Exception as e:
            self.enabled = False
            self.export_enabled = False
            _safe_console_print(f"Voice export failed: {e}")
            return None

    def _play_audio_file(self, audio_path: Path) -> None:
        if os.name != "nt":
            return
        try:
            resolved = audio_path.resolve()
            os.startfile(str(resolved))
        except Exception as e:
            self.enabled = False
            _safe_console_print(f"Voice playback failed: {e}")

    def speak(self, text: str, agent_name: Optional[str] = None):
        """Speak text synchronously; no-op if voice is unavailable."""
        if not text:
            return

        if self.backend == "edge-tts":
            audio_path = self._export_edge_tts_audio(
                text,
                agent_name,
                Path(tempfile.gettempdir()) / f"rain_lab_tts_{uuid.uuid4().hex}.mp3",
            )
            if audio_path is not None:
                self._play_audio_file(audio_path)
            return

        if not self.enabled or not self.engine:
            return

        try:
            target_voice = self._voice_for_agent(agent_name or "")
            if target_voice:
                self.engine.setProperty("voice", target_voice)
            self.engine.say(text)
            self.engine.runAndWait()
        except Exception as e:
            _safe_console_print(f"\u26a0\ufe0f  Voice playback failed: {e}")
            self.enabled = False

    @staticmethod
    def estimate_duration_ms(text: str) -> int:
        """Estimate speech duration for subtitle timing."""
        words = max(1, len(text.split()))
        words_per_minute = 165
        duration_ms = int((words / words_per_minute) * 60_000)
        return max(900, duration_ms)

    def export_to_file(self, text: str, agent_name: Optional[str], output_path: Path) -> Optional[Path]:
        """Synthesize speech to a local audio file for external visual clients."""
        if not self.export_enabled:
            return None
        if not text:
            return None

        if self.backend == "edge-tts":
            return self._export_edge_tts_audio(text, agent_name, output_path)

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            export_engine = pyttsx3.init()

            target_voice = self._voice_for_agent(agent_name or "")
            if target_voice:
                export_engine.setProperty("voice", target_voice)

            export_engine.save_to_file(text, str(output_path))
            export_engine.runAndWait()
            export_engine.stop()

            if output_path.exists() and output_path.stat().st_size > 0:
                return output_path
            return None

        except Exception as e:
            self.export_enabled = False
            _safe_console_print(f"\u26a0\ufe0f  Voice export failed: {e}")
            return None
