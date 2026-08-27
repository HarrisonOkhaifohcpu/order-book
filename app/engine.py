"""
Thin Python wrapper around the compiled C++ matching engine
(`orderbook_cpp`, built from cpp/ via pybind11 -- see setup.py).

This module is the seam between the FastAPI layer and the C++ core: routes
never touch `orderbook_cpp` directly. It translates the pybind11 objects
into plain Python dataclasses (clean, JSON-serializable, no C++ leakage)
and re-raises the C++ exceptions as engine-level Python exceptions so the
API layer doesn't need to know pybind11 exists.

Business logic itself (matching, price-time priority, etc.) lives entirely
in the C++ core (cpp/src/order_book.cpp) -- this file is intentionally thin.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

import orderbook_cpp as _cpp

logger = logging.getLogger("orderbook.engine")


# ---------------------------------------------------------------------------
# Engine-level exceptions (API layer catches these, never pybind11 types)
# ---------------------------------------------------------------------------


class OrderNotFoundError(Exception):
    """Raised when cancelling an order id that is unknown, already
    cancelled, or already fully filled."""

    def __init__(self, order_id: int):
        self.order_id = order_id
        super().__init__(f"Order not found: {order_id}")


class InvalidOrderError(Exception):
    """Raised when an order fails basic validation (non-positive price/qty)."""


# ---------------------------------------------------------------------------
# Plain Python data types (mirror the C++ structs, safe to serialize)
# ---------------------------------------------------------------------------


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    RESTING = "RESTING"


@dataclass
class Fill:
    price: float
    quantity: int
    matched_order_id: int


@dataclass
class SubmitResult:
    order_id: int
    status: OrderStatus
    filled_quantity: int
    remaining_quantity: int
    fills: list[Fill] = field(default_factory=list)


@dataclass
class Trade:
    trade_id: int
    price: float
    quantity: int
    buy_order_id: int
    sell_order_id: int
    timestamp_ms: int


@dataclass
class DepthLevel:
    price: float
    quantity: int


@dataclass
class BookDepth:
    bids: list[DepthLevel] = field(default_factory=list)
    asks: list[DepthLevel] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Side/status <-> C++ enum conversion helpers
# ---------------------------------------------------------------------------

_SIDE_TO_CPP = {Side.BUY: _cpp.Side.BUY, Side.SELL: _cpp.Side.SELL}

_STATUS_FROM_CPP = {
    _cpp.OrderStatus.FILLED: OrderStatus.FILLED,
    _cpp.OrderStatus.PARTIAL: OrderStatus.PARTIAL,
    _cpp.OrderStatus.RESTING: OrderStatus.RESTING,
}


def _convert_submit_result(cpp_result) -> SubmitResult:
    return SubmitResult(
        order_id=cpp_result.order_id,
        status=_STATUS_FROM_CPP[cpp_result.status],
        filled_quantity=cpp_result.filled_quantity,
        remaining_quantity=cpp_result.remaining_quantity,
        fills=[
            Fill(price=f.price, quantity=f.quantity, matched_order_id=f.matched_order_id)
            for f in cpp_result.fills
        ],
    )


def _convert_trade(cpp_trade) -> Trade:
    return Trade(
        trade_id=cpp_trade.trade_id,
        price=cpp_trade.price,
        quantity=cpp_trade.quantity,
        buy_order_id=cpp_trade.buy_order_id,
        sell_order_id=cpp_trade.sell_order_id,
        timestamp_ms=cpp_trade.timestamp_ms,
    )


def _convert_depth(cpp_depth) -> BookDepth:
    return BookDepth(
        bids=[DepthLevel(price=lvl.price, quantity=lvl.quantity) for lvl in cpp_depth.bids],
        asks=[DepthLevel(price=lvl.price, quantity=lvl.quantity) for lvl in cpp_depth.asks],
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class Engine:
    """Wraps a single C++ OrderBook instance (single instrument, in-memory).

    Not thread-safe -- matches the C++ core's design and the real-exchange
    pattern of one thread per instrument (see README, Performance section).
    """

    def __init__(self) -> None:
        self._book = _cpp.OrderBook()

    def submit_order(self, side: Side, price: float, quantity: int) -> SubmitResult:
        try:
            cpp_result = self._book.submit_order(_SIDE_TO_CPP[side], price, quantity)
        except _cpp.InvalidOrderError as exc:
            raise InvalidOrderError(str(exc)) from exc

        result = _convert_submit_result(cpp_result)
        logger.info(
            "submit_order side=%s price=%s quantity=%s -> order_id=%s status=%s "
            "filled=%s remaining=%s fills=%s",
            side.value,
            price,
            quantity,
            result.order_id,
            result.status.value,
            result.filled_quantity,
            result.remaining_quantity,
            len(result.fills),
        )
        return result

    def cancel_order(self, order_id: int) -> None:
        try:
            self._book.cancel_order(order_id)
        except _cpp.OrderNotFoundError as exc:
            raise OrderNotFoundError(order_id) from exc
        logger.info("cancel_order order_id=%s -> cancelled", order_id)

    def get_depth(self) -> BookDepth:
        return _convert_depth(self._book.get_depth())

    def get_trades(self) -> list[Trade]:
        return [_convert_trade(t) for t in self._book.get_trades()]


# ---------------------------------------------------------------------------
# Module-level singleton engine, shared across all requests in this process.
# This matches the spec's "single instrument, single-process, in-memory"
# scope: state resets on restart, which is expected and documented.
# ---------------------------------------------------------------------------

engine = Engine()
