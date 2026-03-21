"""
Local REPL environment for secure code execution.
"""

class LocalREPL:
    """
    A sandboxed REPL environment that executes code locally.
    """

    SAFE_BUILTINS = {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "dir": dir,
        "enumerate": enumerate,
        "float": float,
        "getattr": getattr,
        "hasattr": hasattr,
        "int": int,
        "isinstance": isinstance,
        "issubclass": issubclass,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "pow": pow,
        "print": print,
        "range": range,
        "repr": repr,
        "reversed": reversed,
        "round": round,
        "set": set,
        "slice": slice,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "type": type,
        "zip": zip,

        # Exceptions
        "Exception": Exception,
        "BaseException": BaseException,
    }

    def __init__(self):
        pass
