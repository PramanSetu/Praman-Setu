"""Tests for the AST-based TestModuleConstructor.

Covers every KEEP/STRIP case from the spec:
  - Safe literals kept, non-literal assignments stripped
  - Imports, defs, classes always kept
  - Loops, try/except, if blocks stripped
  - __name__ == "__main__" guard stripped
  - Decorators preserved on defs/classes
  - Module docstring kept
  - AnnAssign with/without value
  - Nested safe literals
  - Dict unpacking (unsafe) stripped
  - build_test_module: pytest import injection, local-import stripping
"""
from __future__ import annotations

import pytest

from backend.tools.test_module_constructor import (
    _is_safe_literal,
    _is_safe_module_node,
    build_test_module,
    reconstruct_safe_module,
)
import ast


# ---------------------------------------------------------------------------
# _is_safe_literal
# ---------------------------------------------------------------------------

class TestIsSafeLiteral:
    def _node(self, src: str) -> ast.expr:
        return ast.parse(src, mode="eval").body

    def test_integer_constant(self):
        assert _is_safe_literal(self._node("42"))

    def test_float_constant(self):
        assert _is_safe_literal(self._node("3.14"))

    def test_string_constant(self):
        assert _is_safe_literal(self._node('"hello"'))

    def test_none_constant(self):
        assert _is_safe_literal(self._node("None"))

    def test_bool_constant(self):
        assert _is_safe_literal(self._node("True"))

    def test_ellipsis_constant(self):
        assert _is_safe_literal(self._node("..."))

    def test_list_of_literals(self):
        assert _is_safe_literal(self._node("[1, 2, 3]"))

    def test_tuple_of_literals(self):
        assert _is_safe_literal(self._node("(1, 'a', True)"))

    def test_set_of_literals(self):
        assert _is_safe_literal(self._node("{1, 2, 3}"))

    def test_dict_of_literals(self):
        assert _is_safe_literal(self._node('{"key": 1, "other": True}'))

    def test_nested_list_dict(self):
        assert _is_safe_literal(self._node('[{"a": 1}, {"b": 2}]'))

    def test_empty_list(self):
        assert _is_safe_literal(self._node("[]"))

    def test_empty_dict(self):
        assert _is_safe_literal(self._node("{}"))

    def test_call_is_unsafe(self):
        assert not _is_safe_literal(self._node("foo()"))

    def test_name_is_unsafe(self):
        assert not _is_safe_literal(self._node("my_var"))

    def test_attribute_is_unsafe(self):
        assert not _is_safe_literal(self._node("os.sep"))

    def test_binop_is_unsafe(self):
        assert not _is_safe_literal(self._node("1 + 2"))

    def test_list_with_call_is_unsafe(self):
        assert not _is_safe_literal(self._node("[1, foo()]"))

    def test_dict_with_call_value_is_unsafe(self):
        assert not _is_safe_literal(self._node('{"k": get_value()}'))

    def test_dict_with_name_key_is_unsafe(self):
        assert not _is_safe_literal(self._node("{KEY: 1}"))


# ---------------------------------------------------------------------------
# reconstruct_safe_module — KEEP cases
# ---------------------------------------------------------------------------

class TestReconstructKeeps:
    def _has(self, source: str, fragment: str) -> bool:
        return fragment in reconstruct_safe_module(source)

    def test_keeps_import(self):
        src = "import os"
        assert "import os" in reconstruct_safe_module(src)

    def test_keeps_import_from(self):
        src = "from typing import List, Dict"
        assert "from typing import List, Dict" in reconstruct_safe_module(src)

    def test_keeps_function_def(self):
        src = "def foo(x):\n    return x + 1"
        assert "def foo(x)" in reconstruct_safe_module(src)

    def test_keeps_async_function_def(self):
        src = "async def bar():\n    return 42"
        assert "async def bar()" in reconstruct_safe_module(src)

    def test_keeps_class_def(self):
        src = "class MyClass:\n    pass"
        assert "class MyClass" in reconstruct_safe_module(src)

    def test_keeps_integer_constant_assign(self):
        src = "MAX_RETRIES = 5"
        assert "MAX_RETRIES = 5" in reconstruct_safe_module(src)

    def test_keeps_string_constant_assign(self):
        src = 'DEFAULT_NAME = "world"'
        assert "DEFAULT_NAME" in reconstruct_safe_module(src)

    def test_keeps_dict_constant_assign(self):
        src = 'DEFAULTS = {"key": "val", "n": 42}'
        assert "DEFAULTS" in reconstruct_safe_module(src)

    def test_keeps_list_constant_assign(self):
        src = "FLAGS = [True, False, True]"
        assert "FLAGS" in reconstruct_safe_module(src)

    def test_keeps_annotation_without_value(self):
        src = "count: int"
        assert "count" in reconstruct_safe_module(src)

    def test_keeps_module_docstring(self):
        src = '"""This is a module docstring."""\n\nimport os'
        result = reconstruct_safe_module(src)
        assert "This is a module docstring" in result

    def test_keeps_pass(self):
        src = "pass"
        assert "pass" in reconstruct_safe_module(src)

    def test_keeps_decorators_on_functions(self):
        src = "@staticmethod\ndef helper():\n    return 1"
        result = reconstruct_safe_module(src)
        assert "def helper" in result

    def test_keeps_dataclass_decorator(self):
        src = "from dataclasses import dataclass\n@dataclass\nclass Point:\n    x: int\n    y: int"
        result = reconstruct_safe_module(src)
        assert "class Point" in result
        assert "dataclass" in result

    def test_syntax_error_returns_original(self):
        broken = "def foo(:\n    pass"
        assert reconstruct_safe_module(broken) == broken


# ---------------------------------------------------------------------------
# reconstruct_safe_module — STRIP cases
# ---------------------------------------------------------------------------

class TestReconstructStrips:
    def _absent(self, source: str, fragment: str) -> bool:
        return fragment not in reconstruct_safe_module(source)

    def test_strips_bare_function_call(self):
        src = "setup()"
        result = reconstruct_safe_module(src)
        assert "setup()" not in result

    def test_strips_assignment_with_call(self):
        src = "result = compute_value()"
        assert "result" not in reconstruct_safe_module(src)

    def test_strips_assignment_with_attribute(self):
        src = "SEP = os.sep"
        assert "SEP" not in reconstruct_safe_module(src)

    def test_strips_assignment_with_binop(self):
        src = "TOTAL = A + B"
        assert "TOTAL" not in reconstruct_safe_module(src)

    def test_strips_annotated_assign_with_call_value(self):
        src = "x: int = compute()"
        assert "compute" not in reconstruct_safe_module(src)

    def test_strips_for_loop(self):
        src = "for i in range(10):\n    print(i)"
        assert "for" not in reconstruct_safe_module(src)

    def test_strips_while_loop(self):
        src = "while True:\n    break"
        assert "while" not in reconstruct_safe_module(src)

    def test_strips_with_block(self):
        src = 'with open("file.txt") as f:\n    data = f.read()'
        assert "with" not in reconstruct_safe_module(src)

    def test_strips_try_except(self):
        src = "try:\n    risky()\nexcept Exception:\n    pass"
        assert "try" not in reconstruct_safe_module(src)

    def test_strips_if_block(self):
        src = "if debug:\n    setup_logging()"
        assert "setup_logging" not in reconstruct_safe_module(src)

    def test_strips_main_guard(self):
        src = 'def run():\n    pass\n\nif __name__ == "__main__":\n    run()'
        result = reconstruct_safe_module(src)
        assert "def run" in result          # function kept
        assert "__main__" not in result    # guard stripped

    def test_strips_assert(self):
        src = "assert x > 0"
        assert "assert" not in reconstruct_safe_module(src)

    def test_strips_delete(self):
        src = "del x"
        assert "del" not in reconstruct_safe_module(src)

    def test_strips_assignment_with_dict_unpack(self):
        # {**other} is not a safe literal (None key in ast.Dict)
        src = "MERGED = {**base_config}"
        assert "MERGED" not in reconstruct_safe_module(src)

    def test_strips_complex_top_level_execution(self):
        """The exact pattern that caused the original pipeline failure."""
        src = (
            "from typing import List\n"
            "import json\n"
            "\n"
            "class DataAggregator:\n"
            "    def compute_average(self, values: List[float]) -> float:\n"
            "        if not values:\n"
            "            return float('nan')\n"
            "        return sum(values) / len(values)\n"
            "\n"
            "aggregator = DataAggregator({'mode': 'standard'})\n"
            "test_data = '{\"records\": [{\"scores\": []}]}'\n"
            "output = aggregator.run_analysis(test_data)\n"
            "for line in output:\n"
            "    print(line)\n"
        )
        result = reconstruct_safe_module(src)

        # Definitions and imports must survive
        assert "from typing import" in result
        assert "import json" in result
        assert "class DataAggregator" in result
        assert "def compute_average" in result

        # All top-level execution must be gone
        assert "aggregator = DataAggregator" not in result
        assert "for line in" not in result
        assert "output = " not in result
        # test_data is a string literal assignment — KEEP it
        assert "test_data" in result


# ---------------------------------------------------------------------------
# build_test_module
# ---------------------------------------------------------------------------

class TestBuildTestModule:
    def test_appends_test_after_module(self):
        module = "def add(a, b):\n    return a + b"
        test = "def test_add():\n    assert add(1, 2) == 3"
        result = build_test_module(module, test)
        assert "def add" in result
        assert "def test_add" in result

    def test_injects_pytest_import_when_missing(self):
        module = "def f():\n    return 1"
        test = "def test_f():\n    with pytest.raises(ValueError):\n        f()"
        result = build_test_module(module, test)
        assert "import pytest" in result

    def test_does_not_duplicate_pytest_import(self):
        module = "def f():\n    return 1"
        test = "import pytest\n\ndef test_f():\n    with pytest.raises(ValueError):\n        f()"
        result = build_test_module(module, test)
        assert result.count("import pytest") == 1

    def test_strips_local_import_from_test(self):
        module = "def add(a, b):\n    return a + b"
        test = "from user_code import add\ndef test_add():\n    assert add(1, 2) == 3"
        result = build_test_module(module, test)
        assert "from user_code import" not in result

    def test_strips_top_level_execution_from_module(self):
        module = "def greet(name):\n    return f'hello {name}'\n\nprint(greet('world'))"
        test = "def test_greet():\n    assert greet('alice') == 'hello alice'"
        result = build_test_module(module, test)
        assert "print(" not in result
        assert "def greet" in result

    def test_strips_assignment_with_call_from_module(self):
        module = (
            "class Aggregator:\n"
            "    def run(self):\n"
            "        return 42\n"
            "\n"
            "agg = Aggregator()\n"
            "result = agg.run()\n"
            "for x in [result]:\n"
            "    print(x)\n"
        )
        test = "def test_run():\n    a = Aggregator()\n    assert a.run() == 42"
        result = build_test_module(module, test)
        assert "class Aggregator" in result
        assert "agg = Aggregator()" not in result
        assert "result = agg.run()" not in result
        assert "for x in" not in result
