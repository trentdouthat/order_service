from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from http.server import ThreadingHTTPServer
import json
import threading
import urllib.error
import urllib.request

import psycopg
import pytest

from order_service.db import InsufficientFundsError, execute_order, get_order, init_schema
from order_service.server import OrderServiceHandler

TEST_DB_URL = "postgresql://postgres:labpass@localhost:5432/orders_test_db"


def _get_balance(owner: str = "TRENT") -> Decimal:
    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT balance FROM accounts WHERE owner = %s;", (owner,))
            return cur.fetchone()[0]


@pytest.fixture(autouse=True)
def clean_test_db(monkeypatch):
    """Reset orders and seed TRENT with $1,000.00 before each test."""
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    init_schema(TEST_DB_URL)
    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE orders, accounts RESTART IDENTITY;")
            cur.execute(
                "INSERT INTO accounts (owner, balance) VALUES ('TRENT', 1000.00);"
            )
    yield


def test_atomic_buy_debits_balance_and_creates_order():
    created = execute_order("msft", "buy", Decimal("200.00"), 3)
    assert created["order_id"] == 1
    assert _get_balance("TRENT") == Decimal("400.00")

    fetched = get_order(1)
    assert fetched is not None
    assert fetched["symbol"] == "MSFT"


def test_insufficient_funds_rolls_back_completely():
    with pytest.raises(InsufficientFundsError):
        execute_order("NVDA", "BUY", Decimal("600.00"), 2)  # $1,200 > $1,000

    assert _get_balance("TRENT") == Decimal("1000.00")
    assert get_order(1) is None


def test_concurrent_http_orders_prevent_overdraw():
    server = ThreadingHTTPServer(("127.0.0.1", 0), OrderServiceHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"

    def submit_buy() -> int:
        req = urllib.request.Request(
            f"{base_url}/orders",
            data=json.dumps(
                {"symbol": "CBOE", "side": "BUY", "price": 200.0, "quantity": 3}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = sorted(pool.map(lambda _: submit_buy(), range(2)), key=lambda r: r[0])

        statuses = [r[0] for r in results]
        assert statuses == [201, 422], f"Unexpected responses: {results}"
        assert _get_balance("TRENT") == Decimal("400.00")
        assert get_order(1) is not None
        assert get_order(2) is None
    finally:
        server.shutdown()
        server.server_close()