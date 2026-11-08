"""
tests/test_matching_engine.py - Rigorous Exchange Verification Test Suite
Tests price-time priority, partial executions, book spreads, and deterministic state transitions.
"""

import pytest
import time
from order_service.matching_engine import (
    Order,
    OrderBook,
    OrderSide,
    OrderStatus,
)


@pytest.fixture
def book():
    """Provides a fresh, empty order book for IBM stock."""
    return OrderBook(symbol="IBM")


def test_empty_book_state(book):
    """An empty book has no best bid, best ask, or spread."""
    assert book.best_bid is None
    assert book.best_ask is None
    assert book.spread is None


def test_resting_order_placement(book):
    """Orders that do not cross the spread simply rest on the book."""
    bid = Order("ORD-1", "IBM", OrderSide.BUY, price=150.00, quantity=100)
    ask = Order("ORD-2", "IBM", OrderSide.SELL, price=155.00, quantity=100)

    trades_bid, _ = book.process_order(bid)
    assert len(trades_bid) == 0
    assert book.best_bid == 150.00

    trades_ask, _ = book.process_order(ask)
    assert len(trades_ask) == 0
    assert book.best_ask == 155.00
    assert book.spread == 5.00


def test_exact_match_execution(book):
    """A resting sell order is matched completely by an incoming buy order."""
    seller = Order("SELL-1", "IBM", OrderSide.SELL, price=100.00, quantity=50)
    book.process_order(seller)

    buyer = Order("BUY-1", "IBM", OrderSide.BUY, price=100.00, quantity=50)
    trades, processed_buy = book.process_order(buyer)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.price == 100.00
    assert trade.quantity == 50
    assert trade.buyer_order_id == "BUY-1"
    assert trade.seller_order_id == "SELL-1"

    # Both orders must be FILLED and removed from active book
    assert processed_buy.status == OrderStatus.FILLED
    assert book.best_ask is None
    assert book.best_bid is None


def test_partial_fill_and_resting_remainder(book):
    """
    Scenario:
    1. Seller rests 40 shares @ $200.
    2. Buyer submits 100 shares @ $200.
    3. 40 shares execute immediately; 60 shares remain as resting bid @ $200.
    """
    seller = Order("SELL-1", "IBM", OrderSide.SELL, price=200.00, quantity=40)
    book.process_order(seller)

    buyer = Order("BUY-1", "IBM", OrderSide.BUY, price=200.00, quantity=100)
    trades, processed_buy = book.process_order(buyer)

    assert len(trades) == 1
    assert trades[0].quantity == 40
    assert processed_buy.status == OrderStatus.PARTIALLY_FILLED
    assert processed_buy.remaining_qty == 60

    # Book check: Ask is gone, remaining 60 shares of Bid are resting
    assert book.best_ask is None
    assert book.best_bid == 200.00
    assert book.bids[0].remaining_qty == 60


def test_price_priority_lowest_ask_matches_first(book):
    """
    Price Priority Rule:
    If Seller A asks $105 and Seller B asks $101, an incoming buyer willing to pay $110
    MUST match Seller B first (best available price).
    """
    ask_expensive = Order("ASK-EXP", "IBM", OrderSide.SELL, price=105.00, quantity=50)
    ask_cheap = Order("ASK-CHP", "IBM", OrderSide.SELL, price=101.00, quantity=50)

    book.process_order(ask_expensive)
    book.process_order(ask_cheap)

    # Buyer enters with limit $110 for 50 shares
    buyer = Order("BUYER", "IBM", OrderSide.BUY, price=110.00, quantity=50)
    trades, _ = book.process_order(buyer)

    assert len(trades) == 1
    assert trades[0].seller_order_id == "ASK-CHP"
    assert trades[0].price == 101.00  # Price improvement: executed at resting ask price!

    # Expensive ask should still be resting untouched
    assert book.best_ask == 105.00


def test_time_priority_fifo_at_identical_price(book):
    """
    Time Priority Rule:
    If two sellers ask the exact same price, the one who entered the book first
    MUST be matched first.
    """
    ask1 = Order("SELLER-1", "IBM", OrderSide.SELL, price=50.00, quantity=25, timestamp=100.0)
    ask2 = Order("SELLER-2", "IBM", OrderSide.SELL, price=50.00, quantity=25, timestamp=105.0)

    book.process_order(ask1)
    book.process_order(ask2)

    # Buyer only buys 25 shares
    buyer = Order("BUY-1", "IBM", OrderSide.BUY, price=50.00, quantity=25)
    trades, _ = book.process_order(buyer)

    assert len(trades) == 1
    assert trades[0].seller_order_id == "SELLER-1"  # First in, first out

    # SELLER-2 should still be resting on the book
    assert len(book.asks) == 1
    assert book.asks[0].order_id == "SELLER-2"


def test_order_cancellation(book):
    """Verifies orders can be cleanly cancelled and pulled from the book."""
    bid = Order("BID-99", "IBM", OrderSide.BUY, price=75.00, quantity=100)
    book.process_order(bid)
    assert book.best_bid == 75.00

    cancelled = book.cancel_order("BID-99")
    assert cancelled is True
    assert book.best_bid is None

    # Cancelling again returns False
    assert book.cancel_order("BID-99") is False
