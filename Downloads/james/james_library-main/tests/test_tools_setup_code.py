import ast
from james_library.utilities import tools


def test_setup_code_is_valid_python():
    ast.parse(tools.get_setup_code())
