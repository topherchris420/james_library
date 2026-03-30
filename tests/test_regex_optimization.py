import unittest
import sys
import os
import tempfile
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock openai
sys.modules["openai"] = MagicMock()

# Mock sys.argv to prevent side effects or unexpected argument parsing
sys.argv = ["rain_lab_meeting_chat_version.py"]

# Now import the module
import rain_lab_meeting_chat_version as rlm


class TestRegexOptimization(unittest.TestCase):
    def test_extract_quotes(self):
        # Call as unbound method with None for self
        # extract_quotes is an instance method but doesn't use self.
        extract = rlm.CitationAnalyzer.extract_quotes

        # Test 1: Quotes excluded because too short (< 3 words)
        text = "This is a \"quoted text\" and another 'single quoted text' with enough words."
        # "quoted text" -> 2 words -> excluded
        # "single quoted text" -> 3 words -> excluded (needs > 3, so 4+)
        expected = []
        actual = extract(None, text)
        self.assertEqual(expected, actual, "Should exclude short quotes")

        # Test 2: Long enough quote (4 words)
        text_long = 'This is a "very long enough quote" here.'
        # "very long enough quote" -> 4 words -> included
        expected_long = ["very long enough quote"]
        actual_long = extract(None, text_long)
        self.assertEqual(expected_long, actual_long, "Should include 4-word quote")

        # Test 3: Multiple quotes
        text_multi = "\"One two three four\" and 'Five six seven eight'"
        expected_multi = ["One two three four", "Five six seven eight"]
        actual_multi = extract(None, text_multi)
        self.assertEqual(expected_multi, actual_multi)

    def test_is_corrupted_response(self):
        # Call as unbound method
        is_corrupted = rlm.RainLabOrchestrator._is_corrupted_response

        # Normal text
        text = "This is a normal response with enough length and normal characters."
        is_corr, reason = is_corrupted(None, text)
        self.assertFalse(is_corr, f"Should be valid: {reason}")

        # Caps corruption
        text_caps = "This is CORRUPTEDTEXTHERE because of caps."
        is_corr, reason = is_corrupted(None, text_caps)
        self.assertTrue(is_corr, "Should detect caps corruption")
        self.assertIn("consecutive capitals", reason)

        # Pattern corruption
        text_pattern = "Some text with |eoc_fim| inside."
        is_corr, reason = is_corrupted(None, text_pattern)
        self.assertTrue(is_corr, "Should detect pattern corruption")
        self.assertIn("Corruption pattern", reason)

        # Case insensitive pattern
        text_pattern_case = "Some text with arilex inside."
        is_corr, reason = is_corrupted(None, text_pattern_case)
        self.assertTrue(is_corr, "Should detect case-insensitive corruption")

    def test_is_corrupted_response_allows_short_complete_sentence(self):
        is_corrupted = rlm.RainLabOrchestrator._is_corrupted_response

        is_corr, reason = is_corrupted(None, "It helps.")

        self.assertFalse(is_corr, f"Short complete sentence should be valid: {reason}")

    def test_is_corrupted_response_flags_incomplete_clause(self):
        is_corrupted = rlm.RainLabOrchestrator._is_corrupted_response

        is_corr, reason = is_corrupted(None, "Imagine a study buddy who never sleeps,")

        self.assertTrue(is_corr)
        self.assertEqual(reason, "Incomplete sentence")

    def test_agent_load_soul_requests_complete_thought_length(self):
        agent = rlm.Agent(
            name="Jasmine",
            role="Guide",
            personality="Warm and practical",
            focus="Beginner-friendly teaching",
            color="green",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "JASMINE_SOUL.md").write_text("# Jasmine soul", encoding="utf-8")
            soul = agent.load_soul(tmpdir)

        self.assertIn("90-140 words", soul)
        self.assertIn("3-5 complete sentences", soul)
        self.assertIn("Do not start with your own name", soul)

    def test_repair_too_short_response_requests_expanded_retry(self):
        repair = rlm.RainLabOrchestrator._repair_too_short_response
        expanded = "An AI tutor is like a calm coach who breaks one huge assignment into smaller steps."
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=expanded))]
        )
        fake_self = SimpleNamespace(
            client=fake_client,
            config=SimpleNamespace(model_name="test-model", temperature=0.7, max_tokens=320),
            _strip_agent_prefix=lambda response, agent_name: rlm.RainLabOrchestrator._strip_agent_prefix(
                None, response, agent_name
            ),
        )
        agent = SimpleNamespace(name="Jasmine", soul="Keep explanations grounded and concise.")

        repaired = repair(
            fake_self,
            agent=agent,
            topic="an AI tutor for overwhelmed college students",
            context_block="paper context",
            short_content="*nods*",
        )

        self.assertEqual(repaired, expanded)
        prompt = fake_client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        self.assertIn("90-140 words", prompt)
        self.assertIn("3 or 4 complete sentences", prompt)
        self.assertIn("Do not start with your own name", prompt)

    def test_looks_truncated_response_flags_dangling_clause(self):
        looks_truncated = rlm.RainLabOrchestrator._looks_truncated_response

        self.assertTrue(looks_truncated(None, "Imagine a study buddy who never sleeps,", None))

    def test_looks_truncated_response_allows_complete_sentence(self):
        looks_truncated = rlm.RainLabOrchestrator._looks_truncated_response

        self.assertFalse(looks_truncated(None, "Imagine a study buddy who never sleeps.", None))

    def test_repair_incomplete_response_expands_dangling_clause(self):
        repair_incomplete = rlm.RainLabOrchestrator._repair_incomplete_response
        expanded = (
            "Imagine a study buddy who never sleeps, but it still slows down long assignments "
            "into manageable next steps for you."
        )
        fake_self = SimpleNamespace(
            _looks_truncated_response=lambda text, finish_reason=None: text.endswith(","),
            _repair_too_short_response=lambda **kwargs: expanded,
            _is_corrupted_response=lambda text: (False, ""),
        )

        repaired = repair_incomplete(
            fake_self,
            agent=SimpleNamespace(name="James"),
            topic="an AI tutor for overwhelmed college students",
            context_block="paper context",
            content="Imagine a study buddy who never sleeps,",
            finish_reason=None,
        )

        self.assertEqual(repaired, expanded)

    def test_voice_engine_init_failure_prints_ascii_safe_warning(self):
        def ascii_only_print(*args, **kwargs):
            rendered = " ".join(str(arg) for arg in args)
            rendered.encode("ascii")

        failing_tts = MagicMock()
        failing_tts.init.side_effect = RuntimeError("sapi failure")

        with patch.object(rlm, "pyttsx3", failing_tts):
            with patch.object(rlm, "edge_tts", None):
                with patch("builtins.print", side_effect=ascii_only_print):
                    voice = rlm.VoiceEngine()

        self.assertFalse(voice.enabled)

    def test_voice_engine_falls_back_to_edge_tts_when_pyttsx3_init_fails(self):
        failing_tts = MagicMock()
        failing_tts.init.side_effect = RuntimeError("sapi failure")

        with patch.object(rlm, "pyttsx3", failing_tts):
            with patch.object(rlm, "edge_tts", object()):
                voice = rlm.VoiceEngine()

        self.assertTrue(voice.enabled)
        self.assertTrue(voice.export_enabled)
        self.assertEqual(voice.backend, "edge-tts")

    def test_voice_engine_edge_tts_export_returns_mp3_path(self):
        class FakeCommunicate:
            def __init__(self, text, voice):
                self.text = text
                self.voice = voice

            async def save(self, path):
                Path(path).write_bytes(b"mp3-bytes")

        fake_edge_tts = SimpleNamespace(Communicate=FakeCommunicate)
        failing_tts = MagicMock()
        failing_tts.init.side_effect = RuntimeError("sapi failure")

        with patch.object(rlm, "pyttsx3", failing_tts):
            with patch.object(rlm, "edge_tts", fake_edge_tts):
                voice = rlm.VoiceEngine()
                with tempfile.TemporaryDirectory() as tmpdir:
                    exported = voice.export_to_file("hello world", "James", Path(tmpdir) / "clip.wav")
                    self.assertEqual(exported.suffix, ".mp3")
                    self.assertTrue(exported.exists())

    def test_voice_engine_export_skips_retry_after_init_failure(self):
        failing_tts = MagicMock()
        failing_tts.init.side_effect = RuntimeError("sapi failure")

        with patch.object(rlm, "pyttsx3", failing_tts):
            with patch.object(rlm, "edge_tts", None):
                voice = rlm.VoiceEngine()
                with tempfile.TemporaryDirectory() as tmpdir:
                    exported = voice.export_to_file("hello world", "James", Path(tmpdir) / "clip.wav")

        self.assertIsNone(exported)
        self.assertEqual(failing_tts.init.call_count, 1)

    def test_voice_engine_speak_uses_edge_tts_playback(self):
        failing_tts = MagicMock()
        failing_tts.init.side_effect = RuntimeError("sapi failure")

        with patch.object(rlm, "pyttsx3", failing_tts):
            with patch.object(rlm, "edge_tts", object()):
                voice = rlm.VoiceEngine()

        fake_audio = Path("C:/temp/fake.mp3")
        with patch.object(voice, "_export_edge_tts_audio", return_value=fake_audio) as export_audio:
            with patch.object(voice, "_play_audio_file") as play_audio:
                voice.speak("hello world", "James")

        export_audio.assert_called_once()
        play_audio.assert_called_once_with(fake_audio)

    def test_strip_agent_prefix(self):
        # Call as unbound method
        strip = rlm.RainLabOrchestrator._strip_agent_prefix

        # Simple case
        text = "James: Hello world."
        cleaned = strip(None, text, "James")
        self.assertEqual(cleaned, "Hello world.")

        # With parentheses
        text_paren = "James (Lead Scientist): Hello world."
        cleaned = strip(None, text_paren, "James")
        self.assertEqual(cleaned, "Hello world.")

        # With dash label
        text_dash = "James - Hello world."
        cleaned = strip(None, text_dash, "James")
        self.assertEqual(cleaned, "Hello world.")

        # Conversational self-intro
        text_here = "James here, hello world."
        cleaned = strip(None, text_here, "James")
        self.assertEqual(cleaned, "hello world.")

        # First-person self-intro
        text_im = "I'm James, and here is my take."
        cleaned = strip(None, text_im, "James")
        self.assertEqual(cleaned, "and here is my take.")

        # No prefix
        text_none = "Hello world."
        cleaned = strip(None, text_none, "James")
        self.assertEqual(cleaned, "Hello world.")

        # Wrong agent
        text_wrong = "Elena: Hello world."
        cleaned = strip(None, text_wrong, "James")
        self.assertEqual(cleaned, "Elena: Hello world.")


if __name__ == "__main__":
    unittest.main()
