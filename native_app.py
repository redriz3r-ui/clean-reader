"""Native macOS launcher for the bundled Clean Reader application."""

from __future__ import annotations

import multiprocessing
import socket
import sys
import threading
import time
from urllib.request import urlopen

import uvicorn
import webview

from app.main import app


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _start_server() -> tuple[uvicorn.Server, threading.Thread, int]:
    port = _available_port()
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )
    )
    server_thread = threading.Thread(target=server.run, name="clean-reader-server", daemon=True)
    server_thread.start()

    deadline = time.monotonic() + 10
    while not server.started and server_thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)

    if not server.started:
        raise RuntimeError("Clean Reader could not start its local service.")
    return server, server_thread, port


def main() -> None:
    multiprocessing.freeze_support()
    server, server_thread, port = _start_server()

    if "--smoke-test" in sys.argv:
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
                if response.status != 200 or b'"status":"ok"' not in response.read():
                    raise RuntimeError("Clean Reader health check failed.")
        finally:
            server.should_exit = True
            server_thread.join(timeout=5)
        return

    webview.create_window(
        "Clean Reader",
        f"http://127.0.0.1:{port}",
        width=1180,
        height=820,
        min_size=(680, 560),
        confirm_close=False,
        text_select=True,
    )
    try:
        webview.start(gui="cocoa", private_mode=False)
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)


if __name__ == "__main__":
    main()
