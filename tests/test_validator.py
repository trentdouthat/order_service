"""
test_validator.py
Senior QA test harness exposing validation flaws and verifying fixes.
"""
import pytest
from order_service import validate_limit_order

# 1. Happy Path Validations
@pytest.mark.parametrize("symbol,price,quantity", [
    ("SPY", 510.50, 100),
    ("C", 62.10, 1),
    ("GOOGL", 175.25, 100000),
])
def test_valid_orders(symbol, price, quantity):
    res = validate_limit_order(symbol, price, quantity)
    assert res["valid"] is True
    assert len(res["errors"]) == 0

# 2. Symbol Edge Cases & Invalidation (Exposing Bug 1)
@pytest.mark.parametrize("bad_symbol,reason", [
    ("", "Empty string"),
    ("TOOLONG1", "More than 5 characters"),
    ("spy", "Lowercase letters not permitted"),
    ("SPY ", "Trailing whitespace not permitted"),
    (" SPY", "Leading whitespace not permitted"),
    ("SP1", "Numeric digits not permitted"),
    ("C@OE", "Special characters not permitted"),
])
def test_symbol_rejections(bad_symbol, reason):
    res = validate_limit_order(bad_symbol, 100.0, 10)
    assert res["valid"] is False, f"Failed on reason: {reason}"
    assert any("symbol" in err.lower() for err in res["errors"])

# 3. Price Edge Cases
@pytest.mark.parametrize("bad_price,reason", [
       (0.0, "Zero price"),
       (-0.01, "Negative penny"),
       (-500.0, "Large negative price"),
       (float("nan"), "IEEE-754 Not-a-Number (NaN)"),
       (float("inf"), "IEEE-754 Positive Infinity"),
       (float("-inf"), "IEEE-754 Negative Infinity"),
   ])
def test_price_rejections(bad_price, reason):
    res = validate_limit_order("AAPL", bad_price, 50)
    assert res["valid"] is False, f"Failed on reason: {reason}"
    assert any("price" in err.lower() for err in res["errors"])

# 4. Quantity Edge Cases (Exposing Bug 3)
@pytest.mark.parametrize("bad_qty,reason", [
    (0, "Zero quantity"),
    (1.0, "Whole number with decimal point"),
    (-10, "Negative quantity"),
    (100001, "Exceeds max allowed size of 100,000"),
    (10.5, "Fractional shares are not permitted on exchange limit order entry")
])
def test_quantity_rejections(bad_qty, reason):
    res = validate_limit_order("AAPL", 150.0, bad_qty)
    assert res["valid"] is False, f"Failed on reason: {reason}"
    assert any("quantity" in err.lower() for err in res["errors"])

