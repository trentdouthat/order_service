import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request


def _get_free_port() -> int:
    """Ask the OS kernel for an ephemeral unused TCP port so tests never collide with port 8080."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_healthz(port: int, timeout: float = 5.0) -> None:
    """Poll /healthz until the child daemon accepts connections."""
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/healthz"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(0.05)
    raise TimeoutError(f"Server did not become healthy on port {port} within {timeout}s")


def test_sigterm_graceful_shutdown():
    """Verify SIGTERM triggers clean socket closure, log output, and exit code 0."""
    port = _get_free_port()

    # Launch the daemon directly via sys.executable (avoids wrapper PIDs from `uv run`)
    code = f"from order_service.server import run; run(host='127.0.0.1', port={port})"
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        _wait_for_healthz(port)

        # Send SIGTERM just like `systemctl stop` or `systemctl restart`
        proc.send_signal(signal.SIGTERM)
        stdout, _ = proc.communicate(timeout=5.0)

        assert proc.returncode == 0
        assert "Received SIGTERM, draining active requests..." in stdout
        assert "Socket closed and daemon exited cleanly." in stdout

        # Confirm the TCP port is actually released back to the OS
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as check_sock:
            check_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            check_sock.bind(("127.0.0.1", port))
    finally:
        # Safety net: ensure no orphan child process survives if an assertion fails
        if proc.poll() is None:
            proc.kill()
            proc.wait()