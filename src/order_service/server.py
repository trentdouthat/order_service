"""
order_service.server - Minimal Zero-Dependency Production Daemon
Exposes HTTP health and validation endpoints for systemd management.
"""

import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from order_service.validator import validate_limit_order

PORT = 8080


class OrderServiceHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, data: dict):
        """Helper to send standardized JSON response with a clean trailing newline."""
        body = (json.dumps(data) + "\n").encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        """Liveness / Readiness probe for release health gates."""
        if self.path == "/healthz" or self.path == "/":
            payload = {
                "status": "HEALTHY",
                "service": "order_service",
                "version": "0.3.0",
            }
            self._send_json(200, payload)
        else:
            self.send_response(404)
            self.end_headers()

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

                result = validate_limit_order(symbol, price, quantity)
                status_code = 200 if result["valid"] else 400
                self._send_json(status_code, result)
            except Exception as e:
                self._send_json(400, {"error": str(e)})
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Standardized syslog/systemd logging output."""
        sys.stdout.write(f"[order_service] {self.address_string()} - {format % args}\n")
        sys.stdout.flush()


def run(host: str = "0.0.0.0", port: int = PORT):
    server_address = (host, port)
    httpd = HTTPServer(server_address, OrderServiceHandler)
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