import os
from decimal import Decimal
import psycopg
from psycopg.rows import dict_row

DEFAULT_DB_URL = "postgresql://postgres:labpass@localhost:5432/orders_db"


class InsufficientFundsError(ValueError):
    """Raised when an account balance cannot cover the total order notional."""


def get_db_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DB_URL)


def ping_db(db_url: str | None = None) -> None:
    """Verify PostgreSQL connectivity with a minimal round-trip query."""
    with psycopg.connect(db_url or get_db_url(), connect_timeout=2) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")


def init_schema(db_url: str | None = None) -> None:
    """Create or migrate accounts and orders tables idempotently."""
    with psycopg.connect(db_url or get_db_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id SERIAL PRIMARY KEY,
                    owner VARCHAR(32) NOT NULL UNIQUE,
                    balance NUMERIC(12, 2) NOT NULL CHECK (balance >= 0)
                );

                CREATE TABLE IF NOT EXISTS orders (
                    order_id SERIAL PRIMARY KEY,
                    owner VARCHAR(32) NOT NULL DEFAULT 'TRENT',
                    symbol VARCHAR(16) NOT NULL,
                    side VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
                    price NUMERIC(10, 2) NOT NULL CHECK (price > 0),
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                ALTER TABLE orders
                ADD COLUMN IF NOT EXISTS owner VARCHAR(32) NOT NULL DEFAULT 'TRENT';
                """
            )

def execute_order(
    symbol: str,
    side: str,
    price: Decimal,
    quantity: int,
    owner: str = "TRENT",
    db_url: str | None = None,
) -> dict:
    """Atomically lock the account row, verify/debit cash on BUY, and insert the order."""
    normalized_side = side.upper()
    normalized_symbol = symbol.upper()
    normalized_owner = owner.upper()
    notional = (price * Decimal(quantity)).quantize(Decimal("0.01"))

    with psycopg.connect(db_url or get_db_url()) as conn:
        with conn.transaction():
            with conn.cursor(row_factory=dict_row) as cur:
                # 1. Pessimistic row lock: serializes concurrent orders for this owner
                cur.execute(
                    """
                    SELECT account_id, balance
                    FROM accounts
                    WHERE owner = %s
                    FOR UPDATE;
                    """,
                    (normalized_owner,),
                )
                account = cur.fetchone()
                if account is None:
                    raise ValueError(f"Unknown account owner: {normalized_owner}")

                # 2. Check-then-act safely under the row lock
                if normalized_side == "BUY":
                    if account["balance"] < notional:
                        raise InsufficientFundsError(
                            f"Insufficient funds: need {notional}, available {account['balance']}"
                        )
                    cur.execute(
                        """
                        UPDATE accounts
                        SET balance = balance - %s
                        WHERE account_id = %s;
                        """,
                        (notional, account["account_id"]),
                    )

                # 3. Persist the order inside the exact same transaction
                cur.execute(
                    """
                    INSERT INTO orders (owner, symbol, side, price, quantity)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING order_id, owner, symbol, side, price, quantity, created_at;
                    """,
                    (normalized_owner, normalized_symbol, normalized_side, price, quantity),
                )
                row = cur.fetchone()
                if row is None:
                    raise RuntimeError("INSERT ... RETURNING produced no row")
                return row


def get_order(order_id: int, db_url: str | None = None) -> dict | None:
    """Fetch a single order by primary key."""
    with psycopg.connect(db_url or get_db_url()) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT order_id, owner, symbol, side, price, quantity, created_at
                FROM orders
                WHERE order_id = %s;
                """,
                (order_id,),
            )
            return cur.fetchone()