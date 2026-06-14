from __future__ import annotations

import ast

from backend.tools.neutralize import neutralize_nontermination


def _compiles(code: str) -> bool:
    try:
        ast.parse(code)
    except SyntaxError:
        return False
    return True


def test_daemonizes_threading_thread() -> None:
    code = "import threading\nt = threading.Thread(target=work)\nt.start()\n"
    out, notes = neutralize_nontermination(code)
    assert "threading.Thread(target=work, daemon=True)" in out
    assert notes and "daemon=True" in notes[0]
    assert _compiles(out)


def test_daemonizes_bare_thread_from_import() -> None:
    code = "from threading import Thread\nThread(target=work).start()\n"
    out, _ = neutralize_nontermination(code)
    assert "Thread(target=work, daemon=True)" in out


def test_daemonizes_multiprocessing_process() -> None:
    code = "import multiprocessing\np = multiprocessing.Process(target=work)\n"
    out, _ = neutralize_nontermination(code)
    assert "daemon=True" in out


def test_no_change_when_already_daemon() -> None:
    code = "import threading\nthreading.Thread(target=work, daemon=True).start()\n"
    out, notes = neutralize_nontermination(code)
    assert out == code
    assert notes == []


def test_no_change_without_threads() -> None:
    code = "x = 1\nprint(x)\n"
    out, notes = neutralize_nontermination(code)
    assert out == code
    assert notes == []


def test_handles_no_args_constructor() -> None:
    code = "from threading import Thread\nt = Thread()\n"
    out, _ = neutralize_nontermination(code)
    assert "Thread(daemon=True)" in out
    assert _compiles(out)


def test_returns_original_on_syntax_error() -> None:
    code = "def f(:\n    pass\n"
    out, notes = neutralize_nontermination(code)
    assert out == code
    assert notes == []
