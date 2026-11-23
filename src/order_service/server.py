"""
order_service.server - Production Daemon with PostgreSQL Persistence
Exposes HTTP health, readiness, metrics, validation, and order persistence endpoints.
"""

from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version as pkg_version
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import signal
import sys
import threading
import time
from order_service.db import InsufficientFundsError, execute_order, get_order, init_schema, ping_db
from order_service.validator import validate_limit_order

PORT = 8080
START_TIME = time.monotonic()
SYMLINK_PATH = "/opt/order_service/current"
SHUTDOWN_EVENT = threading.Event()


def _get_version() -> str:
    try:
        return pkg_version("order_service")
    except PackageNotFoundError:
        return "0.4.0-dev"


def _serialize_order(row: dict) -> dict:
    """Convert PostgreSQL Decimal and datetime fields into JSON-safe values."""
    return {
        "order_id": row["order_id"],
        "owner": row["owner"],
        "symbol": row["symbol"],
        "side": row["side"],
        "price": str(row["price"]),
        "quantity": row["quantity"],
        "created_at": row["created_at"].isoformat(),
    }


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
    """Verify internal modules, validator logic, database connectivity, and symlink target."""
    checks = {}
    ready = True

    if SHUTDOWN_EVENT.is_set():
        checks["shutdown_state"] = "shutting_down"
        ready = False
    else:
        checks["shutdown_state"] = "accepting_traffic"

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

    if os.environ.get("DATABASE_URL"):
        try:
            ping_db()
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc}"
            ready = False
    else:
        checks["database"] = "not_configured"

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

    def _read_json_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        return json.loads(body.decode("utf-8"))

    def do_GET(self):
        """Liveness, readiness, telemetry, and order lookup endpoints."""
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

        elif self.path.startswith("/orders/"):
            raw_id = self.path.removeprefix("/orders/")
            if not raw_id.isdigit():
                self._send_json(400, {"error": "order_id must be a positive integer"})
                return
            try:
                row = get_order(int(raw_id))
            except Exception as exc:
                self._send_json(503, {"error": f"database error: {exc}"})
                return

            if row is None:
                self._send_json(404, {"error": f"order {raw_id} not found"})
            else:
                self._send_json(200, _serialize_order(row))

        else:
            self._send_empty(404)

    def do_POST(self):
        """Validate or persist limit orders submitted via HTTP POST."""
        if self.path == "/validate":
            try:
                data = self._read_json_body()
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

        elif self.path == "/orders":
            try:
                data = self._read_json_body()
                symbol = data.get("symbol")
                side = data.get("side", "BUY")
                price = data.get("price")
                quantity = data.get("quantity")
                owner = data.get("owner", "TRENT")

                t0 = time.perf_counter()
                result = validate_limit_order(symbol, price, quantity)
                duration_us = (time.perf_counter() - t0) * 1_000_000

                errors = list(result["errors"])
                if not isinstance(side, str) or side not in ("BUY", "SELL"):
                    errors.append("Invalid side (must be 'BUY' or 'SELL')")

                if errors:
                    METRICS.record_validation(False, duration_us)
                    self._send_json(400, {"valid": False, "errors": errors})
                    return

                METRICS.record_validation(True, duration_us)
                created = execute_order(
                    symbol, side, Decimal(str(price)), quantity, owner=owner
                )
                self._send_json(201, _serialize_order(created))
            except InsufficientFundsError as exc:
                self._send_json(422, {"error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
        else:
            self._send_empty(404)

    def log_message(self, format, *args):
        """Standardized syslog/systemd logging output."""
        sys.stdout.write(f"[order_service] {self.address_string()} {format % args}\n")
        sys.stdout.flush()


def run(host: str = "0.0.0.0", port: int = PORT):
    if os.environ.get("DATABASE_URL"):
        init_schema()

    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, OrderServiceHandler)

    def _handle_shutdown_signal(signum, _frame):
        sig_name = signal.Signals(signum).name
        SHUTDOWN_EVENT.set()
        print(f"\n[+] Received {sig_name}, draining active requests...")
        sys.stdout.flush()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)

    print(f"[+] order_service daemon listening on {host}:{port}")
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        print("[+] Socket closed and daemon exited cleanly.")
        sys.stdout.flush()


if __name__ == "__main__":
    run()