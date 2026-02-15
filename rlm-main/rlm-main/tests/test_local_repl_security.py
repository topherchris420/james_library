"""Security tests for LocalREPL environment."""

import pytest
import os
from rlm.environments.local_repl import LocalREPL

class TestLocalREPLSecurity:
    """Security tests for LocalREPL."""

    def test_block_os_system(self):
        """Test that os.system cannot be executed via import."""
        repl = LocalREPL()
        code = """
import os
os.system('echo "pwned"')
"""
        result = repl.execute_code(code)
        assert "ImportError" in result.stderr or "AttributeError" in result.stderr or "NameError" in result.stderr
        repl.cleanup()

    def test_block_subprocess(self):
        """Test that subprocess cannot be executed via import."""
        repl = LocalREPL()
        code = """
import subprocess
subprocess.run(['echo', 'pwned'])
"""
        result = repl.execute_code(code)
        assert "ImportError" in result.stderr or "AttributeError" in result.stderr or "NameError" in result.stderr
        repl.cleanup()

    def test_allowed_imports(self):
        """Test that safe imports are still allowed."""
        repl = LocalREPL()
        code = """
import math
import json
import random
x = math.pi
y = json.dumps({"a": 1})
z = random.randint(1, 10)
"""
        result = repl.execute_code(code)
        assert result.stderr == ""
        repl.cleanup()

    def test_open_allowed_in_temp_dir(self):
        """Test that opening files inside temp dir is allowed."""
        repl = LocalREPL()
        code = """
with open('test_file.txt', 'w') as f:
    f.write('hello')
with open('test_file.txt', 'r') as f:
    content = f.read()
"""
        result = repl.execute_code(code)
        assert result.stderr == ""
        assert repl.locals.get('content') == 'hello'
        repl.cleanup()

    def test_open_blocked_outside_temp_dir(self):
        """Test that opening files outside temp dir is blocked."""
        repl = LocalREPL()
        # Create a dummy file outside temp dir
        outside_file = os.path.abspath("test_outside.txt")
        try:
            with open(outside_file, "w") as f:
                f.write("secret")

            code = f"""
try:
    with open(r'{outside_file}', 'r') as f:
        content = f.read()
except IOError as e:
    print(f"Caught expected error: {{e}}")
except Exception as e:
    print(f"Caught unexpected error: {{type(e).__name__}}: {{e}}")
"""
            result = repl.execute_code(code)
            assert "Caught expected error" in result.stdout
        finally:
            if os.path.exists(outside_file):
                os.remove(outside_file)
            repl.cleanup()

    def test_open_blocked_relative_path_traversal(self):
        """Test that relative path traversal is blocked."""
        repl = LocalREPL()
        code = """
try:
    with open('../outside.txt', 'w') as f:
        f.write('fail')
except IOError as e:
    print(f"Caught expected error: {e}")
except Exception as e:
    print(f"Caught unexpected error: {type(e).__name__}: {e}")
"""
        result = repl.execute_code(code)
        assert "Caught expected error" in result.stdout
        repl.cleanup()
