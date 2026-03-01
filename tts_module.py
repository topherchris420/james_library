"""
R.A.I.N. Lab TTS Module (Unified)

Text-to-Speech for agent responses.
Uses edge-tts for high-quality neural voices, falls back to pyttsx3.
"""

import asyncio
import os
import queue
import threading

# Try to import TTS libraries
edge_tts = None
try:
    import edge_tts
except ImportError:
    pass

pyttsx3 = None
try:
    import pyttsx3
except ImportError:
    pass


class TTSEngine:
    """Unified Text-to-Speech engine with agent-specific voices."""

    # Agent voice configurations (rate, volume, edge-tts voice)
    VOICE_CONFIG = {
        # Male agents
        "James": {"rate": 150, "volume": 1.0, "edge_voice": "en-US-GuyNeural", "pyttsx3_id": 0},
        "Luca": {"rate": 145, "volume": 1.0, "edge_voice": "en-US-GuyNeural", "pyttsx3_id": 0},
        "Alex": {"rate": 150, "volume": 1.0, "edge_voice": "en-US-GuyNeural", "pyttsx3_id": 0},
        "Ryan": {"rate": 150, "volume": 1.0, "edge_voice": "en-US-GuyNeural", "pyttsx3_id": 0},
        "Marcus": {"rate": 150, "volume": 1.0, "edge_voice": "en-US-GuyNeural", "pyttsx3_id": 0},
        # Female agents
        "Jasmine": {"rate": 160, "volume": 1.0, "edge_voice": "en-US-AriaNeural", "pyttsx3_id": 1},
        "Elena": {"rate": 155, "volume": 0.9, "edge_voice": "en-US-AriaNeural", "pyttsx3_id": 1},
        "Sarah": {"rate": 165, "volume": 1.0, "edge_voice": "en-US-AriaNeural", "pyttsx3_id": 1},
        "Diana": {"rate": 155, "volume": 0.95, "edge_voice": "en-US-AriaNeural", "pyttsx3_id": 1},
        "Eve": {"rate": 160, "volume": 1.0, "edge_voice": "en-US-AriaNeural", "pyttsx3_id": 1},
        "Nova": {"rate": 160, "volume": 1.0, "edge_voice": "en-US-AriaNeural", "pyttsx3_id": 1},
    }

    # Default voices when agent not found
    DEFAULT_MALE_VOICE = "en-US-GuyNeural"
    DEFAULT_FEMALE_VOICE = "en-US-AriaNeural"

    # pyttsx3 voice indices (0 = male, 1 = female typically)
    MALE_VOICE_IDX = 0
    FEMALE_VOICE_IDX = 1

    def __init__(self, enabled: bool = True, backend: str = "auto", rate: str = "+0%", volume: str = "+0%"):
        """
        Initialize TTS engine.

        Args:
            enabled: Whether TTS is enabled
            backend: TTS backend ('edge-tts', 'pyttsx3', or 'auto' for best available)
            rate: Default speech rate adjustment (e.g., "+20%", "-10%")
            volume: Default volume adjustment
        """
        self.enabled = enabled
        self.default_rate = rate
        self.default_volume = volume
        self.speech_queue = queue.Queue()
        self.speaking = False
        self._pyttsx3_engine = None

        # Determine backend
        if backend == "auto":
            if edge_tts:
                self.backend = "edge-tts"
            elif pyttsx3:
                self.backend = "pyttsx3"
            else:
                self.backend = "silent"
        else:
            self.backend = backend

        # Validate backend is available
        if self.backend == "edge-tts" and not edge_tts:
            self.backend = "pyttsx3" if pyttsx3 else "silent"
        if self.backend == "pyttsx3" and not pyttsx3:
            self.backend = "silent"

        # Initialize pyttsx3 engine if using that backend
        if self.backend == "pyttsx3" and pyttsx3:
            try:
                self._pyttsx3_engine = pyttsx3.init()
            except Exception as e:
                print(f"pyttsx3 init warning: {e}")
                self.backend = "silent"

    def speak(self, text: str, agent_name: str = None, async_mode: bool = True):
        """Speak the given text with optional agent-specific voice.

        Args:
            text: Text to speak
            agent_name: Agent name for voice selection (optional)
            async_mode: If True, speak in background thread
        """
        if not self.enabled:
            print(f"[TTS] {text}")
            return

        if async_mode:
            thread = threading.Thread(target=self._speak_text, args=(text, agent_name))
            thread.daemon = True
            thread.start()
        else:
            self._speak_text(text, agent_name)

    def _speak_text(self, text: str, agent_name: str = None):
        """Internal speak implementation."""
        # Get agent config
        config = self.VOICE_CONFIG.get(agent_name, {})

        # Clean text for speech
        clean_text = self._clean_text_for_speech(text)

        if self.backend == "edge-tts" and edge_tts:
            voice = config.get("edge_voice", self.DEFAULT_FEMALE_VOICE)
            rate = config.get("rate", 150)
            # Convert rate to edge-tts format
            rate_adj = self._rate_to_edge_format(rate)
            try:
                asyncio.run(self._edge_speak(clean_text, voice, rate_adj))
            except Exception as e:
                print(f"edge-tts error: {e}")

        elif self.backend == "pyttsx3" and self._pyttsx3_engine:
            try:
                engine = pyttsx3.init()
                voice_id = config.get("pyttsx3_id", self.FEMALE_VOICE_IDX)

                # Try to set voice
                try:
                    voices = engine.getProperty('voices')
                    if voice_id < len(voices):
                        engine.setProperty('voice', voices[voice_id].id)
                except Exception:
                    pass

                # Set rate and volume from config or defaults
                rate = config.get("rate", 180)
                volume = config.get("volume", 1.0)
                engine.setProperty('rate', rate)
                engine.setProperty('volume', volume)

                engine.say(clean_text)
                engine.runAndWait()
                engine.stop()
            except Exception as e:
                print(f"pyttsx3 error: {e}")

        else:
            # Silent mode - just print
            print(f"[TTS] {clean_text}")

    async def _edge_speak(self, text: str, voice: str, rate: str = "+0%", volume: str = "+0%"):
        """Speak using edge-tts."""
        import time
        # Use unique filename for each speak to avoid overwrite
        temp_dir = os.environ.get('TEMP', '/tmp')
        temp_file = os.path.join(temp_dir, f'rain_lab_tts_{int(time.time()*1000)}.mp3')

        communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
        await communicate.save(temp_file)

        # Play the audio
        if os.name == 'nt':
            os.system(f'start "" "{temp_file}"')
        else:
            os.system(f"afplay {temp_file} &")

    def _rate_to_edge_format(self, rate: int) -> str:
        """Convert pyttsx3 rate (words per minute) to edge-tts format (+X%)."""
        # pyttsx3 default is 200, edge-tts default is +0%
        # Rate 150 = -25%, Rate 200 = +0%, Rate 250 = +25%
        percent = int(((rate - 200) / 200) * 100)
        return f"{percent:+d}%"

    def _clean_text_for_speech(self, text: str) -> str:
        """Clean text for better speech output."""
        import re

        # Remove code blocks
        text = re.sub(r'```[\s\S]*?```', '', text)
        # Remove inline code
        text = re.sub(r'`[^`]+`', '', text)
        # Remove bold
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        # Remove italic
        text = re.sub(r'\*([^*]+)\*', r'\1', text)
        # Remove URLs
        text = re.sub(r'http[s]?://\S+', '', text)
        # Clean up extra whitespace
        text = ' '.join(text.split())
        # Truncate if too long
        if len(text) > 5000:
            text = text[:5000] + "..."

        return text

    def speak_agent(self, agent_name: str, text: str, async_mode: bool = True):
        """Speak an agent's response with their voice.

        Args:
            agent_name: Name of the agent
            response: Response text
            async_mode: If True, speak in background thread
        """
        self.speak(text, agent_name=agent_name, async_mode=async_mode)

    def stop(self):
        """Stop any ongoing speech."""
        if self._pyttsx3_engine:
            try:
                self._pyttsx3_engine.stop()
            except:
                pass


# Global TTS instance
_tts_engine = None


def get_tts(**kwargs) -> TTSEngine:
    """Get or create global TTS engine."""
    global _tts_engine
    if _tts_engine is None:
        _tts_engine = TTSEngine(**kwargs)
    return _tts_engine


def speak(text: str, agent_name: str = None, async_mode: bool = True):
    """Speak text using global engine."""
    get_tts().speak(text, agent_name=agent_name, async_mode=async_mode)


def speak_agent(agent_name: str, text: str, async_mode: bool = True):
    """Speak agent response with appropriate voice."""
    get_tts().speak_agent(agent_name, text, async_mode=async_mode)


def is_available() -> bool:
    """Check if TTS is available."""
    return edge_tts is not None or pyttsx3 is not None


def list_voices() -> list:
    """List available voices for the current backend."""
    if edge_tts:
        # Return available edge-tts voices
        return [
            ("en-US-GuyNeural", "Male - Guy"),
            ("en-US-AriaNeural", "Female - Aria"),
            ("en-US-JennyNeural", "Female - Jenny"),
            ("en-US-SaraNeural", "Female - Sara"),
        ]
    elif pyttsx3:
        try:
            engine = pyttsx3.init()
            voices = engine.getProperty('voices')
            return [(v.id, v.name) for v in voices]
        except:
            return []
    return []


# Backwards compatibility aliases
TTS_AVAILABLE = is_available()


# Test
if __name__ == "__main__":
    print("Testing Unified TTS...")
    tts = get_tts()
    print(f"Backend: {tts.backend}")
    print(f"Available: {is_available()}")

    print("\nAvailable voices:")
    for vid, vname in list_voices():
        print(f"  {vid}: {vname}")

    print("\n--- Testing male voice (James) ---")
    speak_agent("James", "Hello, I am James. Testing the unified TTS system.")

    print("\n--- Testing female voice (Elena) ---")
    speak_agent("Elena", "Hello, I am Elena. Testing the female voice.")

    print("\nDone!")
