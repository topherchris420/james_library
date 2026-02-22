import ast
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools


def test_setup_code_is_valid_python():
    ast.parse(tools.get_setup_code())
