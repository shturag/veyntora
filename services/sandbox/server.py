"""Code sandbox: runs Python for the chat's code interpreter (ADR 0030).

Reached only by the graph server, on an internal Docker network without internet access.
Each run is a fresh `python -I` process in its own empty folder, which is deleted
afterwards, with limits on CPU time, memory, file size, processes and wall time. Files the
code writes (charts, CSV) come back with the output. Nothing is kept between runs.

Standard library only; the libraries offered to the code are listed in requirements.txt.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

PORT = int(os.environ.get("SANDBOX_PORT", "8090"))
# Optional shared secret: when set, callers must send it as a bearer token.
TOKEN = os.environ.get("SANDBOX_TOKEN", "")

MAX_CODE_CHARS = 20_000
MAX_OUTPUT_CHARS = 20_000
WALL_SECONDS = 30
CPU_SECONDS = 20
MEMORY_BYTES = 768 * 1024 * 1024
FILE_BYTES = 20 * 1024 * 1024
PROCESSES = 32
# Files returned to the caller: up to this many, this large in total.
MAX_FILES = 5
MAX_FILES_BYTES = 2 * 1024 * 1024
MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".json": "application/json",
}
# Runs at the same time; more wait their turn.
SLOTS = threading.BoundedSemaphore(int(os.environ.get("SANDBOX_PARALLEL", "2")))


def _limits() -> None:  # pragma: no cover - runs in the child process
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_BYTES, FILE_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_NPROC, (PROCESSES, PROCESSES))


def _cut(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n… ({len(text) - MAX_OUTPUT_CHARS} more characters)"


def _files(folder: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    total = 0
    for path in sorted(folder.rglob("*")):
        mime = MIME.get(path.suffix.lower())
        hidden = any(part.startswith(".") for part in path.relative_to(folder).parts)
        if mime is None or hidden or not path.is_file() or path.name == "main.py":
            continue
        size = path.stat().st_size
        if len(out) == MAX_FILES or total + size > MAX_FILES_BYTES:
            break
        total += size
        out.append(
            {
                "name": str(path.relative_to(folder))[:200],
                "mime": mime,
                "base64": base64.b64encode(path.read_bytes()).decode(),
            }
        )
    return out


def run(code: str) -> dict[str, Any]:
    """Runs `code` with the limits above; returns its output and the files it wrote."""
    folder = Path(tempfile.mkdtemp(prefix="run-"))
    try:
        (folder / "main.py").write_text(code, encoding="utf-8")
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(folder),
            "MPLCONFIGDIR": str(folder / ".mpl"),
            "MPLBACKEND": "Agg",
            "PYTHONDONTWRITEBYTECODE": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
        }
        # A session of its own, so a timeout ends everything the code started.
        proc = subprocess.Popen(
            [sys.executable, "-I", "main.py"],
            cwd=folder,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            preexec_fn=_limits,  # noqa: PLW1509 - limits must be set in the child
        )
        try:
            stdout, stderr = proc.communicate(timeout=WALL_SECONDS)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            stdout, _ = proc.communicate()
            return {
                "stdout": _cut(stdout.decode(errors="replace")),
                "stderr": f"Stopped: the code ran longer than {WALL_SECONDS} seconds.",
                "exit_code": None,
                "timed_out": True,
                "files": [],
            }
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)  # anything left running in the background
        return {
            "stdout": _cut(stdout.decode(errors="replace")),
            "stderr": _cut(stderr.decode(errors="replace")),
            "exit_code": proc.returncode,
            "timed_out": False,
            "files": _files(folder),
        }
    finally:
        shutil.rmtree(folder, ignore_errors=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "veyntora-sandbox"

    def _reply(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._reply(200, {"status": "ok"})
        else:
            self._reply(404, {"detail": "Not found"})

    def do_POST(self) -> None:
        if self.path != "/run":
            self._reply(404, {"detail": "Not found"})
            return
        if TOKEN and self.headers.get("authorization") != f"Bearer {TOKEN}":
            self._reply(401, {"detail": "Not allowed"})
            return
        length = int(self.headers.get("content-length") or 0)
        if length > MAX_CODE_CHARS * 4 + 1000:
            self._reply(413, {"detail": "The code is too long."})
            return
        try:
            code = json.loads(self.rfile.read(length) or b"{}").get("code")
        except ValueError:
            code = None
        if not isinstance(code, str) or not code.strip() or len(code) > MAX_CODE_CHARS:
            self._reply(422, {"detail": f"Send Python code of up to {MAX_CODE_CHARS} characters."})
            return
        with SLOTS:
            self._reply(200, run(code))

    def log_message(self, fmt: str, *args: Any) -> None:
        # The code and its output are never logged.
        sys.stderr.write(f"{self.command} {self.path} {args[1] if len(args) > 1 else ''}\n")


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()  # noqa: S104
