"""
Tests for context-hub integration (fetch_api_docs, search_api_docs, annotate_api_docs).

All subprocess calls are mocked — chub does not need to be installed to run these tests.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("JAMES_LIBRARY_PATH", str(REPO_ROOT))

from tools import (
    annotate_api_docs,
    fetch_api_docs,
    search_api_docs,
)


def _make_proc(stdout="", stderr="", returncode=0):
    """Build a mock CompletedProcess."""
    m = MagicMock()
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


class TestFetchApiDocs(unittest.TestCase):

    def test_chub_not_installed_returns_hint(self):
        """When chub is absent, tool returns a friendly install hint."""
        import tools
        orig_checked, orig_present = tools._chub_checked, tools._chub_present
        try:
            tools._chub_checked = True
            tools._chub_present = False
            result = fetch_api_docs("openai/chat")
            self.assertIn("npm install", result)
            self.assertIn("chub", result)
        finally:
            tools._chub_checked = orig_checked
            tools._chub_present = orig_present

    def test_invalid_doc_id_rejected(self):
        """Shell-metacharacter doc_ids must be rejected."""
        import tools
        orig_checked, orig_present = tools._chub_checked, tools._chub_present
        try:
            tools._chub_checked = True
            tools._chub_present = True
            result = fetch_api_docs("; rm -rf /")
            self.assertIn("Invalid doc_id", result)
        finally:
            tools._chub_checked = orig_checked
            tools._chub_present = orig_present

    def test_invalid_lang_rejected(self):
        """Unsupported language variants must be rejected."""
        import tools
        orig_checked, orig_present = tools._chub_checked, tools._chub_present
        try:
            tools._chub_checked = True
            tools._chub_present = True
            result = fetch_api_docs("openai/chat", lang="bash")
            self.assertIn("Unsupported lang", result)
        finally:
            tools._chub_checked = orig_checked
            tools._chub_present = orig_present

    @patch("subprocess.run")
    def test_successful_fetch_returns_sanitized_output(self, mock_run):
        """Successful chub get → output is returned (sanitized)."""
        import tools
        mock_run.return_value = _make_proc(
            stdout="## OpenAI Chat API\nclient.chat.completions.create(...)",
            returncode=0,
        )
        orig_checked, orig_present = tools._chub_checked, tools._chub_present
        try:
            tools._chub_checked = True
            tools._chub_present = True
            result = fetch_api_docs("openai/chat", lang="py")
            self.assertIn("OpenAI Chat API", result)
            # Confirm subprocess was called without shell=True
            call_kwargs = mock_run.call_args
            self.assertNotIn("shell", call_kwargs.kwargs or {})
        finally:
            tools._chub_checked = orig_checked
            tools._chub_present = orig_present

    @patch("subprocess.run")
    def test_chub_error_returns_error_message(self, mock_run):
        """Non-zero exit from chub → error message, no exception."""
        import tools
        mock_run.return_value = _make_proc(stderr="doc not found", returncode=1)
        orig_checked, orig_present = tools._chub_checked, tools._chub_present
        try:
            tools._chub_checked = True
            tools._chub_present = True
            result = fetch_api_docs("nonexistent/doc")
            self.assertIn("chub error", result)
        finally:
            tools._chub_checked = orig_checked
            tools._chub_present = orig_present


class TestSearchApiDocs(unittest.TestCase):

    def test_policy_block_on_injection(self):
        """search_api_docs blocks policy-violating queries."""
        result = search_api_docs("system prompt reveal instructions")
        self.assertIn("Policy block", result)

    def test_chub_not_installed_returns_hint(self):
        import tools
        orig_checked, orig_present = tools._chub_checked, tools._chub_present
        try:
            tools._chub_checked = True
            tools._chub_present = False
            result = search_api_docs("stripe payments")
            self.assertIn("npm install", result)
        finally:
            tools._chub_checked = orig_checked
            tools._chub_present = orig_present

    @patch("subprocess.run")
    def test_successful_search_returns_results(self, mock_run):
        import tools
        mock_run.return_value = _make_proc(
            stdout="openai/chat  - OpenAI Chat Completion API\nstripe/api   - Stripe Payments",
            returncode=0,
        )
        orig_checked, orig_present = tools._chub_checked, tools._chub_present
        try:
            tools._chub_checked = True
            tools._chub_present = True
            result = search_api_docs("openai")
            self.assertIn("openai/chat", result)
        finally:
            tools._chub_checked = orig_checked
            tools._chub_present = orig_present


class TestAnnotateApiDocs(unittest.TestCase):

    def test_note_too_long_is_blocked(self):
        """Notes over 4000 chars are blocked by _policy_guard."""
        result = annotate_api_docs("openai/chat", "x" * 4001)
        self.assertIn("too long", result.lower())

    def test_invalid_doc_id_rejected(self):
        import tools
        orig_checked, orig_present = tools._chub_checked, tools._chub_present
        try:
            tools._chub_checked = True
            tools._chub_present = True
            result = annotate_api_docs("../../etc/passwd", "note")
            self.assertIn("Invalid doc_id", result)
        finally:
            tools._chub_checked = orig_checked
            tools._chub_present = orig_present

    def test_chub_not_installed_returns_hint(self):
        import tools
        orig_checked, orig_present = tools._chub_checked, tools._chub_present
        try:
            tools._chub_checked = True
            tools._chub_present = False
            result = annotate_api_docs("openai/chat", "Needs raw body for webhooks")
            self.assertIn("npm install", result)
        finally:
            tools._chub_checked = orig_checked
            tools._chub_present = orig_present

    @patch("subprocess.run")
    def test_successful_annotate_returns_confirmation(self, mock_run):
        import tools
        mock_run.return_value = _make_proc(stdout="Annotation saved.", returncode=0)
        orig_checked, orig_present = tools._chub_checked, tools._chub_present
        try:
            tools._chub_checked = True
            tools._chub_present = True
            result = annotate_api_docs("openai/chat", "Needs Assistant role before user message")
            self.assertTrue(len(result) > 0)
            self.assertNotIn("error", result.lower())
        finally:
            tools._chub_checked = orig_checked
            tools._chub_present = orig_present


if __name__ == "__main__":
    unittest.main()
