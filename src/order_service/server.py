"""
order_service.server - Minimal Zero-Dependency Production Daemon
Exposes HTTP health, readiness, metrics, and validation endpoints for systemd management.
"""

from importlib.metadata import PackageNotFoundError, version as pkg_version
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sys
import threading
import time

from order_service.validator import validate_limit_order

PORT = 8080
START_TIME = time.monotonic()
SYMLINK_PATH = "/opt/order_service/current"


def _get_version() -> str:
    try:
        return pkg_version("order_service")
    except PackageNotFoundError:
        return "0.4.0-dev"


class ServiceMetrics:
    """Thread-safe in-memory telemetry counters for daemon observability."""

    def __init__(self):
        self._lock = threading.Lock()
        self.requests_total = 0
        self.status_counts: dict[str, int] = {}
        self.validations_passed = 0
        self.validations_rejected = 0
        self.last_validation_us = 0.0
        self.max_validation_us = 0.0

    def record_response(self, status_code: int):
        code_key = str(status_code)
        with self._lock:
            self.requests_total += 1
            self.status_counts[code_key] = self.status_counts.get(code_key, 0) + 1

    def record_validation(self, valid: bool, duration_us: float):
        with self._lock:
            if valid:
                self.validations_passed += 1
            else:
                self.validations_rejected += 1
            self.last_validation_us = round(duration_us, 2)
            if duration_us > self.max_validation_us:
                self.max_validation_us = round(duration_us, 2)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "requests_total": self.requests_total,
                "responses_by_status": dict(self.status_counts),
                "validations_passed": self.validations_passed,
                "validations_rejected": self.validations_rejected,
                "validation_latency_us": {
                    "last": self.last_validation_us,
                    "max": self.max_validation_us,
                },
            }


METRICS = ServiceMetrics()


def _check_readiness() -> tuple[bool, dict]:
    """Verify internal modules, validator logic, and active symlink target."""
    checks = {}
    ready = True

    try:
        import order_service.matching_engine  # noqa: F401
        checks["matching_engine_import"] = "ok"
    except Exception as exc:
        checks["matching_engine_import"] = f"error: {exc}"
        ready = False

    try:
        probe = validate_limit_order("CBOE", 100.0, 10)
        if probe.get("valid") is True:
            checks["validator_self_test"] = "ok"
        else:
            checks["validator_self_test"] = "unexpected_result"
            ready = False
    except Exception as exc:
        checks["validator_self_test"] = f"error: {exc}"
        ready = False

    resolved_release = (
        os.path.realpath(SYMLINK_PATH) if os.path.exists(SYMLINK_PATH) else "local_dev"
    )

    payload = {
        "status": "READY" if ready else "NOT_READY",
        "service": "order_service",
        "version": _get_version(),
        "pid": os.getpid(),
        "active_release_path": resolved_release,
        "checks": checks,
    }
    return ready, payload


class OrderServiceHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, data: dict):
        """Helper to send standardized JSON response with a clean trailing newline."""
        METRICS.record_response(status_code)
        body = (json.dumps(data) + "\n").encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status_code: int):
        METRICS.record_response(status_code)
        self.send_response(status_code)
        self.end_headers()

    def do_GET(self):
        """Liveness, readiness, and telemetry probes for release health gates."""
        if self.path in ("/healthz", "/"):
            payload = {
                "status": "HEALTHY",
                "service": "order_service",
                "version": _get_version(),
                "pid": os.getpid(),
                "uptime_seconds": round(time.monotonic() - START_TIME, 2),
            }
            self._send_json(200, payload)

        elif self.path == "/readyz":
            is_ready, payload = _check_readiness()
            self._send_json(200 if is_ready else 503, payload)

        elif self.path == "/metrics":
            payload = {
                "service": "order_service",
                "version": _get_version(),
                "pid": os.getpid(),
                "uptime_seconds": round(time.monotonic() - START_TIME, 2),
                "telemetry": METRICS.snapshot(),
            }
            self._send_json(200, payload)

        else:
            self._send_empty(404)

    def do_POST(self):
        """Validate order payloads submitted via HTTP POST."""
        if self.path == "/validate":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
                symbol = data.get("symbol")
                price = data.get("price")
                quantity = data.get("quantity")

                t0 = time.perf_counter()
                result = validate_limit_order(symbol, price, quantity)
                duration_us = (time.perf_counter() - t0) * 1_000_000

                is_valid = bool(result["valid"])
                METRICS.record_validation(is_valid, duration_us)

                status_code = 200 if is_valid else 400
                self._send_json(status_code, result)
            except Exception as exc:
                METRICS.record_validation(False, 0.0)
                self._send_json(400, {"error": str(exc)})
        else:
            self._send_empty(404)

    def log_message(self, format, *args):
        """Standardized syslog/systemd logging output."""
        sys.stdout.write(f"[order_service] {self.address_string()} - {format % args}\n")
        sys.stdout.flush()


def run(host: str = "0.0.0.0", port: int = PORT):
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, OrderServiceHandler)
    print(f"[+] order_service daemon listening on {host}:{port}")
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[+] Daemon shutting down cleanly...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    run()