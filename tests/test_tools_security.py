import os
import unittest
import sys
from pathlib import Path

# Add repo root to path for imports
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Mock globals before importing tools
os.environ["JAMES_LIBRARY_PATH"] = str(REPO_ROOT)

from tools import _policy_guard, export_to_file, generate_html

class TestToolsSecurity(unittest.TestCase):
    def test_policy_guard_schemes(self):
        allowed, msg = _policy_guard("test_tool", "search for javascript: variables")
        self.assertFalse(allowed)
        
        allowed, msg = _policy_guard("test_tool", "what is data:text/html in forms?")
        self.assertFalse(allowed)
        
        allowed, msg = _policy_guard("test_tool", "read file:///C:/Windows/System32")
        self.assertFalse(allowed)
        
        allowed, msg = _policy_guard("test_tool", "normal query about python")
        self.assertTrue(allowed)

    def test_export_path_traversal(self):
        # Path traversal should fail
        result = export_to_file("../../../etc/passwd", "hacked")
        self.assertIn("path traversal prevented", result)
        
        result2 = export_to_file("C:\\Windows\\System32\\cmd.exe", "hacked")
        self.assertIn("path traversal prevented", result2)
        
        result3 = export_to_file("/etc/shadow", "hacked")
        self.assertIn("path traversal prevented", result3)
        
        # Valid name should attempt to write
        result4 = export_to_file("safe_file.md", "content")
        self.assertIn("Exported to:", result4)

    def test_generate_html_xss(self):
        topic = "<script>alert(1)</script>"
        agent_responses = [("James", "Response with <img src=x onerror=alert(2)>")]
        metadata = {"<bold>": "value<br>"}
        
        html = generate_html(topic, agent_responses, metadata)
        
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)
        self.assertNotIn("<bold>", html)
        self.assertIn("&lt;bold&gt;", html)

if __name__ == "__main__":
    unittest.main()
