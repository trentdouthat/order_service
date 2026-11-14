import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from order_service.server import OrderServiceHandler


@pytest.fixture
def live_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), OrderServiceHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


def _get_json(url: str):
    with urllib.request.urlopen(url, timeout=2) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def test_healthz_endpoint(live_server):
    status, body = _get_json(f"{live_server}/healthz")
    assert status == 200
    assert body["status"] == "HEALTHY"
    assert "pid" in body
    assert body["uptime_seconds"] >= 0


def test_readyz_endpoint(live_server):
    status, body = _get_json(f"{live_server}/readyz")
    assert status == 200
    assert body["status"] == "READY"
    assert body["checks"]["matching_engine_import"] == "ok"
    assert body["checks"]["validator_self_test"] == "ok"


def test_metrics_tracks_validations(live_server):
    req = urllib.request.Request(
        f"{live_server}/validate",
        data=json.dumps({"symbol": "AAPL", "price": 150.0, "quantity": 5}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2) as resp:
        assert resp.status == 200

    status, body = _get_json(f"{live_server}/metrics")
    assert status == 200
    telemetry = body["telemetry"]
    assert telemetry["requests_total"] >= 2
    assert telemetry["validations_passed"] >= 1
    assert telemetry["validation_latency_us"]["last"] > 0