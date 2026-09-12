"""Shared helpers: locally generated media and a tiny HTTP server that mimics YouTube streams."""

from __future__ import annotations

import functools
import subprocess
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def make_video(
    path: Path, seconds: float = 3, audio: str | None = "aac", video: str | None = "libx264"
) -> Path:
    """Write a short test-pattern clip; ``audio``/``video`` pick encoders or None to omit."""
    args = ["ffmpeg", "-v", "error", "-y"]
    if video:
        args += ["-f", "lavfi", "-i", f"testsrc2=size=160x120:rate=30:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    if video:
        args += ["-c:v", video, "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", audio]
    subprocess.run([*args, str(path)], check=True)
    return path


class _QuietHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/expired":
            self.send_error(403)
            return
        super().do_GET()

    def log_message(self, *args):
        pass


class MediaServer:
    """Serves ``root`` over HTTP; ``/expired`` always answers 403."""

    def __init__(self, root: Path) -> None:
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(_QuietHandler, directory=str(root))
        )
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
