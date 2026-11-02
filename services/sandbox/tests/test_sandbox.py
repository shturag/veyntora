"""The sandbox runner (ADR 0030). Memory and process limits apply on Linux only."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "sandbox_server", Path(__file__).parents[1] / "server.py"
)
assert _spec and _spec.loader
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)


def test_runs_code_and_returns_output_and_files() -> None:
    out = server.run("print(6 * 7)\nopen('result.csv', 'w').write('a,b\\n1,2\\n')")
    assert out["stdout"] == "42\n" and out["exit_code"] == 0 and not out["timed_out"]
    [file] = out["files"]
    assert file["name"] == "result.csv" and file["mime"] == "text/csv"


def test_errors_come_back_as_output() -> None:
    out = server.run("1 / 0")
    assert out["exit_code"] == 1 and "ZeroDivisionError" in out["stderr"]


def test_every_run_starts_empty() -> None:
    server.run("open('left.txt', 'w').write('x')")
    out = server.run("import os; print(sorted(os.listdir('.')))")
    assert out["stdout"].strip() == "['main.py']"


def test_long_runs_are_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "WALL_SECONDS", 1)
    out = server.run("import time\ntime.sleep(5)")
    assert out["timed_out"] and "longer than 1 seconds" in out["stderr"]


def test_the_environment_is_empty() -> None:
    out = server.run(
        "import os; print(sorted(k for k in os.environ if 'TOKEN' in k or 'KEY' in k))"
    )
    assert out["stdout"].strip() == "[]"


@pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_AS is enforced on Linux")
def test_memory_is_limited() -> None:
    out = server.run("x = bytearray(2 * 1024 ** 3)")
    assert out["exit_code"] != 0 and "MemoryError" in out["stderr"]
