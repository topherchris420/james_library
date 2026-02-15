
import unittest
import sys
import os
import re
from unittest.mock import MagicMock

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock openai
sys.modules['openai'] = MagicMock()

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
        text = 'This is a "quoted text" and another \'single quoted text\' with enough words.'
        # "quoted text" -> 2 words -> excluded
        # "single quoted text" -> 3 words -> excluded (needs > 3, so 4+)
        expected = []
        actual = extract(None, text)
        self.assertEqual(expected, actual, "Should exclude short quotes")

        # Test 2: Long enough quote (4 words)
        text_long = 'This is a "very long enough quote" here.'
        # "very long enough quote" -> 4 words -> included
        expected_long = ['very long enough quote']
        actual_long = extract(None, text_long)
        self.assertEqual(expected_long, actual_long, "Should include 4-word quote")

        # Test 3: Multiple quotes
        text_multi = '"One two three four" and \'Five six seven eight\''
        expected_multi = ['One two three four', 'Five six seven eight']
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

        # No prefix
        text_none = "Hello world."
        cleaned = strip(None, text_none, "James")
        self.assertEqual(cleaned, "Hello world.")

        # Wrong agent
        text_wrong = "Elena: Hello world."
        cleaned = strip(None, text_wrong, "James")
        self.assertEqual(cleaned, "Elena: Hello world.")

if __name__ == '__main__':
    unittest.main()
