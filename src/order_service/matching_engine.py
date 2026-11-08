"""
order_service.matching_engine - Deterministic Price-Time Priority Matching Engine
Implements an in-memory Limit Order Book (LOB) with FIFO queueing per price level.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple
import itertools
import time


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


@dataclass
class Trade:
    """Represents a matched execution between two crossing orders."""
    trade_id: int
    symbol: str
    price: float
    quantity: int
    buyer_order_id: str
    seller_order_id: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class Order:
    order_id: str
    symbol: str
    side: OrderSide
    price: float
    quantity: int
    remaining_qty: int = field(init=False)
    status: OrderStatus = field(default=OrderStatus.NEW)
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        self.remaining_qty = self.quantity


class OrderBook:
    """
    In-memory Limit Order Book for a single trading symbol.
    Maintains Price-Time priority for Bids and Asks.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        # Bids: Buyers want high prices. Sorted descending by price, then ascending by time.
        self.bids: List[Order] = []
        # Asks: Sellers want low prices. Sorted ascending by price, then ascending by time.
        self.asks: List[Order] = []
        self._trade_counter = itertools.count(1)

    @property
    def best_bid(self) -> Optional[float]:
        """Returns the highest price a buyer is willing to pay."""
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        """Returns the lowest price a seller is willing to accept."""
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> Optional[float]:
        """Difference between lowest ask and highest bid."""
        if self.best_bid is not None and self.best_ask is not None:
            return round(self.best_ask - self.best_bid, 4)
        return None

    def process_order(self, order: Order) -> Tuple[List[Trade], Order]:
        """
        Processes an incoming order against resting orders on the book.
        Executes immediate matches (crossing spread), then rests any unfilled quantity.
        """
        trades: List[Trade] = []

        if order.side == OrderSide.BUY:
            trades = self._match_buy(order)
            if order.remaining_qty > 0 and order.status != OrderStatus.CANCELLED:
                self._insert_bid(order)
        elif order.side == OrderSide.SELL:
            trades = self._match_sell(order)
            if order.remaining_qty > 0 and order.status != OrderStatus.CANCELLED:
                self._insert_ask(order)

        return trades, order

    def _match_buy(self, buy_order: Order) -> List[Trade]:
        trades: List[Trade] = []
        # Buy matches if seller's ask is <= buyer's bid
        while self.asks and buy_order.remaining_qty > 0:
            best_ask = self.asks[0]
            if best_ask.price > buy_order.price:
                break  # Spread not crossed; no more matches possible

            # Trade execution price is determined by the RESTING order on the book
            match_price = best_ask.price
            match_qty = min(buy_order.remaining_qty, best_ask.remaining_qty)

            trade = Trade(
                trade_id=next(self._trade_counter),
                symbol=self.symbol,
                price=match_price,
                quantity=match_qty,
                buyer_order_id=buy_order.order_id,
                seller_order_id=best_ask.order_id,
            )
            trades.append(trade)

            # Deduct quantities
            buy_order.remaining_qty -= match_qty
            best_ask.remaining_qty -= match_qty

            # Update status for resting ask
            if best_ask.remaining_qty == 0:
                best_ask.status = OrderStatus.FILLED
                self.asks.pop(0)  # Remove filled order from head of queue
            else:
                best_ask.status = OrderStatus.PARTIALLY_FILLED

            # Update status for incoming buyer
            if buy_order.remaining_qty == 0:
                buy_order.status = OrderStatus.FILLED
            else:
                buy_order.status = OrderStatus.PARTIALLY_FILLED

        return trades

    def _match_sell(self, sell_order: Order) -> List[Trade]:
        trades: List[Trade] = []
        # Sell matches if buyer's bid is >= seller's ask
        while self.bids and sell_order.remaining_qty > 0:
            best_bid = self.bids[0]
            if best_bid.price < sell_order.price:
                break  # Spread not crossed

            match_price = best_bid.price
            match_qty = min(sell_order.remaining_qty, best_bid.remaining_qty)

            trade = Trade(
                trade_id=next(self._trade_counter),
                symbol=self.symbol,
                price=match_price,
                quantity=match_qty,
                buyer_order_id=best_bid.order_id,
                seller_order_id=sell_order.order_id,
            )
            trades.append(trade)

            sell_order.remaining_qty -= match_qty
            best_bid.remaining_qty -= match_qty

            if best_bid.remaining_qty == 0:
                best_bid.status = OrderStatus.FILLED
                self.bids.pop(0)
            else:
                best_bid.status = OrderStatus.PARTIALLY_FILLED

            if sell_order.remaining_qty == 0:
                sell_order.status = OrderStatus.FILLED
            else:
                sell_order.status = OrderStatus.PARTIALLY_FILLED

        return trades

    def _insert_bid(self, order: Order):
        """Insert bid preserving descending price, then ascending timestamp."""
        # Find insertion index
        idx = 0
        while idx < len(self.bids):
            # Highest price first
            if order.price > self.bids[idx].price:
                break
            elif order.price == self.bids[idx].price:
                # FIFO: new order goes behind existing orders at same price
                idx += 1
            else:
                idx += 1
        self.bids.insert(idx, order)

    def _insert_ask(self, order: Order):
        """Insert ask preserving ascending price, then ascending timestamp."""
        idx = 0
        while idx < len(self.asks):
            # Lowest price first
            if order.price < self.asks[idx].price:
                break
            elif order.price == self.asks[idx].price:
                idx += 1
            else:
                idx += 1
        self.asks.insert(idx, order)

    def cancel_order(self, order_id: str) -> bool:
        """Cancels a resting order and removes it from the book."""
        for i, order in enumerate(self.bids):
            if order.order_id == order_id:
                order.status = OrderStatus.CANCELLED
                self.bids.pop(i)
                return True
        for i, order in enumerate(self.asks):
            if order.order_id == order_id:
                order.status = OrderStatus.CANCELLED
                self.asks.pop(i)
                return True
        return False
