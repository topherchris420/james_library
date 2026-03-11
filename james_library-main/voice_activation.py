"""
R.A.I.N. Lab Voice Activation Module

Wake word detection for hands-free operation.
Supports: "Hey James" or custom wake words.
"""

import queue
import threading
import time

# Try to import speech recognition
try:
    import speech_recognition as sr
    SPEECH_RECOGNITION_AVAILABLE = True
except ImportError:
    SPEECH_RECOGNITION_AVAILABLE = False


class VoiceActivator:
    """Voice activation with wake word detection."""

    def __init__(self, wake_words: list = None, threshold: float = 0.5):
        """
        Initialize voice activator.

        Args:
            wake_words: List of wake words/phrases (default: ["hey james", "james"])
            threshold: Energy threshold for voice detection
        """
        self.wake_words = wake_words or ["hey james", "james"]
        self.threshold = threshold
        self.recognizer = None
        self.microphone = None
        self.is_listening = False
        self.stop_event = threading.Event()
        self.listen_thread = None
        self.callback = None
        self._init_audio()

    def _init_audio(self):
        """Initialize audio components."""
        if not SPEECH_RECOGNITION_AVAILABLE:
            print("Speech recognition not available. Install: pip install SpeechRecognition")
            return

        try:
            self.recognizer = sr.Recognizer()
            self.recognizer.energy_threshold = self.threshold
            self.microphone = sr.Microphone()
            # Calibrate for ambient noise
            with self.microphone as source:
                print("🎤 Calibrating microphone...")
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
                print("🎤 Microphone ready.")
        except Exception as e:
            print(f"Microphone error: {e}")
            self.microphone = None

    def start_listening(self, callback):
        """Start listening for wake words.

        Args:
            callback: Function to call when wake word is detected
        """
        if not SPEECH_RECOGNITION_AVAILABLE or not self.microphone:
            print("Voice activation not available")
            return

        self.callback = callback
        self.stop_event.clear()
        self.is_listening = True

        self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listen_thread.start()
        print("🎤 Listening for wake word... (say 'Hey James' to start)")

    def _listen_loop(self):
        """Main listening loop."""
        while not self.stop_event.is_set():
            try:
                with self.microphone as source:
                    audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=5)

                # Recognize speech
                try:
                    text = self.recognizer.recognize_google(audio).lower()
                    print(f" Heard: {text}")

                    # Check for wake words
                    for wake_word in self.wake_words:
                        if wake_word in text:
                            print(f"✅ Wake word detected: {wake_word}")
                            if self.callback:
                                self.callback(wake_word, text)
                            break

                except sr.UnknownValueError:
                    pass  # Didn't understand
                except sr.RequestError as e:
                    print(f"Speech recognition error: {e}")

            except queue.Empty:
                pass  # Timeout, keep listening
            except Exception as e:
                print(f"Listen error: {e}")
                time.sleep(0.5)

    def stop_listening(self):
        """Stop listening for wake words."""
        self.stop_event.set()
        self.is_listening = False
        print("🎤 Stopped listening.")

    def listen_once(self, timeout: int = 5) -> str:
        """Listen once and return recognized text.

        Args:
            timeout: Timeout in seconds

        Returns:
            Recognized text or None
        """
        if not self.recognizer or not self.microphone:
            return None

        try:
            with self.microphone as source:
                audio = self.recognizer.listen(source, timeout=timeout)
            return self.recognizer.recognize_google(audio)
        except Exception as e:
            return None


def start_voice_activation(callback):
    """Start voice activation in background thread."""
    activator = VoiceActivator()
    activator.start_listening(callback)
    return activator


# Installation help
INSTALL_HELP = """
To enable voice activation, install:

    pip install SpeechRecognition

For better recognition:
    pip install pip install google-cloud-speech  # Optional

Then run with voice activation:
    python rain_lab_meeting.py --voice-activation
"""
