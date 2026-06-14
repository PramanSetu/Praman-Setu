from __future__ import annotations

import ast

from backend.tools.bug_ledger import build_bug_ledger
from backend.tools.semantic_lint import semantic_lint


def _kinds(code: str) -> list[str]:
    return [issue.kind for issue in semantic_lint(ast.parse(code))]


# --- mutable default argument ---


def test_flags_mutable_list_default() -> None:
    issues = semantic_lint(ast.parse("def f(a, items=[]):\n    return items\n"))
    assert [i.kind for i in issues] == ["mutable_default"]
    assert issues[0].symbol == "items"


def test_flags_mutable_dict_and_set_and_call_defaults() -> None:
    assert _kinds("def f(a={}):\n    return a\n") == ["mutable_default"]
    assert _kinds("def f(a=set()):\n    return a\n") == ["mutable_default"]
    assert _kinds("def f(a=list()):\n    return a\n") == ["mutable_default"]


def test_immutable_defaults_are_not_flagged() -> None:
    assert _kinds("def f(a=0, b='x', c=None, d=(1, 2)):\n    return a\n") == []


# --- ignored return value ---


def test_flags_ignored_value_returning_call() -> None:
    code = (
        "def withdraw(amount):\n"
        "    if amount > 0:\n"
        "        return True\n"
        "    return False\n\n"
        "def transfer(amount):\n"
        "    withdraw(amount)\n"  # return ignored
    )
    kinds = _kinds(code)
    assert "ignored_return" in kinds


def test_flags_ignored_method_return() -> None:
    code = (
        "class A:\n"
        "    def withdraw(self, n):\n"
        "        return n > 0\n\n"
        "def go(a):\n"
        "    a.withdraw(5)\n"
    )
    assert "ignored_return" in _kinds(code)


def test_none_returning_call_is_not_flagged() -> None:
    code = (
        "def log(msg):\n"
        "    print(msg)\n\n"
        "def run():\n"
        "    log('hi')\n"  # log returns None -> fine
    )
    assert "ignored_return" not in _kinds(code)


def test_used_return_is_not_flagged() -> None:
    code = (
        "def val():\n"
        "    return 1\n\n"
        "def run():\n"
        "    x = val()\n"  # used, not a bare statement
        "    return x\n"
    )
    assert "ignored_return" not in _kinds(code)


# --- shared state aliasing in clone/copy methods ---


def test_flags_clone_direct_alias_and_nested_shallow_copy() -> None:
    code = (
        "from copy import copy\n\n"
        "class ShoppingCart:\n"
        "    def __init__(self):\n"
        "        self.items = []\n"
        "        self.discounts = {}\n\n"
        "    def add_item(self, name, price):\n"
        "        self.items.append({'name': name, 'price': price})\n\n"
        "    def clone(self):\n"
        "        new_cart = ShoppingCart()\n"
        "        new_cart.items = copy(self.items)\n"
        "        new_cart.discounts = self.discounts\n"
        "        return new_cart\n"
    )

    issues = semantic_lint(ast.parse(code))
    shared = [issue for issue in issues if issue.kind == "shared_state_alias"]

    assert len(shared) == 2
    assert {issue.symbol for issue in shared} == {"items", "discounts"}
    assert any("shallow-copies self.items" in issue.message for issue in shared)
    assert any("assigns mutable self.discounts directly" in issue.message for issue in shared)


def test_shallow_copy_of_flat_mutable_attr_is_not_flagged() -> None:
    code = (
        "class Bag:\n"
        "    def __init__(self):\n"
        "        self.values = []\n\n"
        "    def add(self, value):\n"
        "        self.values.append(value)\n\n"
        "    def clone(self):\n"
        "        other = Bag()\n"
        "        other.values = self.values.copy()\n"
        "        return other\n"
    )
    assert "shared_state_alias" not in _kinds(code)


# --- swallowed exception ---


def test_flags_except_pass() -> None:
    code = "def f():\n    try:\n        risky()\n    except Exception:\n        pass\n"
    assert "swallowed_exception" in _kinds(code)


def test_handled_exception_is_not_flagged() -> None:
    code = "def f():\n    try:\n        risky()\n    except Exception:\n        return None\n"
    assert "swallowed_exception" not in _kinds(code)


# --- infinite loops ---


def test_flags_infinite_while_true() -> None:
    assert "infinite_loop" in _kinds("def w():\n    while True:\n        x = 1\n")


def test_while_true_with_break_is_not_flagged() -> None:
    assert "infinite_loop" not in _kinds("def w():\n    while True:\n        if done():\n            break\n")


def test_while_true_with_return_is_not_flagged() -> None:
    assert "infinite_loop" not in _kinds("def w():\n    while True:\n        return 1\n")


def test_conditional_while_is_not_flagged() -> None:
    assert "infinite_loop" not in _kinds("def w(n):\n    while n > 0:\n        n -= 1\n")


# --- background threads started at module level ---


def test_flags_top_level_thread_start() -> None:
    code = (
        "import threading\n"
        "def worker():\n"
        "    while True:\n"
        "        pass\n"
        "for i in range(3):\n"
        "    t = threading.Thread(target=worker)\n"
        "    t.start()\n"
    )
    assert "background_thread" in _kinds(code)


def test_thread_start_inside_function_is_not_flagged() -> None:
    code = (
        "import threading\n"
        "def run():\n"
        "    t = threading.Thread(target=lambda: None)\n"
        "    t.start()\n"  # only runs if run() is called — not at import
    )
    assert "background_thread" not in _kinds(code)


def test_start_without_concurrency_import_is_not_flagged() -> None:
    # A `.start()` with no threading/multiprocessing import is likely unrelated.
    assert "background_thread" not in _kinds("server = make()\nserver.start()\n")


# --- integration with the ledger ---


def test_ledger_includes_semantic_findings() -> None:
    ledger = build_bug_ledger("def f(a=[]):\n    return a\n")
    kinds = [issue.kind for issue in ledger.issues]
    assert "mutable_default" in kinds
    # semantic findings are warnings, so they survive the UI's info filter
    assert all(i.severity == "warning" for i in ledger.issues if i.kind == "mutable_default")
