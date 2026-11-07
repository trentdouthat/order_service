"""
validator.py (HARDENED PRODUCTION VERSION)
Bulletproof validation satisfying all exchange boundary constraints.
"""

import math

def validate_limit_order(symbol: str, price: float, quantity: int) -> dict:
    """
    Validates incoming limit order parameters against exchange business rules.
    Returns: {"valid": bool, "errors": list[str]}
    """
    errors = []

    # 1. Symbol Rule: Non-empty string, 1 to 5 chars, strictly uppercase A-Z only.
    if not isinstance(symbol, str):
        errors.append("Symbol must be a string")
    elif len(symbol) < 1 or len(symbol) > 5:
        errors.append("Invalid symbol length (must be 1-5 characters)")
    elif not symbol.isalpha() or not symbol.isupper():
        errors.append("Invalid symbol format (must be uppercase A-Z only, no spaces or symbols)")

    # 2. Price Rule: Must be float or int and strictly greater than 0.00
    if not isinstance(price, (int, float)) or isinstance(price, bool):
        errors.append("Price must be a valid numeric amount")
    elif math.isnan(price) or math.isinf(price):
        errors.append("Price must be a finite number (not NaN or Infinity)")
    elif price <= 0:
        errors.append("Price must be positive")

    # 3. Quantity Rule: Strict integer strictly between 1 and 100,000
    # Note: In Python, bool is a subclass of int (True == 1), so we explicitly block bool.
    if not isinstance(quantity, int) or isinstance(quantity, bool):
        errors.append("Quantity must be a whole integer (fractional shares not permitted)")
    elif quantity <= 0 or quantity > 100000:
        errors.append("Quantity out of bounds (must be between 1 and 100,000)")

    return {"valid": len(errors) == 0, "errors": errors}