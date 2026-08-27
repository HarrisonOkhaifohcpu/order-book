"""The 9 core matching-logic test cases required by the spec (section 14),
exercised through app.engine.Engine (the Python wrapper around the C++
core). These mirror the standalone C++ smoke tests in
cpp/tests/test_order_book.cpp but run through the actual pybind11 boundary
that the FastAPI service uses in production.
"""

from __future__ import annotations

import pytest

from app.engine import Engine, InvalidOrderError, OrderNotFoundError, OrderStatus, Side


def test_1_single_order_rests_on_empty_book(engine: Engine) -> None:
    result = engine.submit_order(Side.BUY, 100.0, 50)

    assert result.status == OrderStatus.RESTING
    assert result.filled_quantity == 0
    assert result.remaining_quantity == 50
    assert result.fills == []

    depth = engine.get_depth()
    assert len(depth.bids) == 1
    assert depth.bids[0].price == 100.0
    assert depth.bids[0].quantity == 50
    assert depth.asks == []


def test_2_full_match_at_resting_price(engine: Engine) -> None:
    resting = engine.submit_order(Side.BUY, 100.0, 50)  # rests, order_id=1

    incoming = engine.submit_order(Side.SELL, 99.0, 50)  # crosses fully

    assert incoming.status == OrderStatus.FILLED
    assert incoming.filled_quantity == 50
    assert incoming.remaining_quantity == 0
    assert len(incoming.fills) == 1
    # Match happens at the RESTING order's price (100.0), not the
    # incoming sell's limit price (99.0) -- price-time priority rule.
    assert incoming.fills[0].price == 100.0
    assert incoming.fills[0].quantity == 50
    assert incoming.fills[0].matched_order_id == resting.order_id

    depth = engine.get_depth()
    assert depth.bids == []
    assert depth.asks == []


def test_3_partial_match_remainder_rests(engine: Engine) -> None:
    engine.submit_order(Side.SELL, 100.0, 30)  # resting, only 30 available

    incoming = engine.submit_order(Side.BUY, 100.0, 50)

    assert incoming.status == OrderStatus.PARTIAL
    assert incoming.filled_quantity == 30
    assert incoming.remaining_quantity == 20
    assert len(incoming.fills) == 1

    depth = engine.get_depth()
    assert depth.asks == []
    assert len(depth.bids) == 1
    assert depth.bids[0].quantity == 20


def test_4_matches_across_multiple_price_levels(engine: Engine) -> None:
    engine.submit_order(Side.SELL, 100.0, 10)
    engine.submit_order(Side.SELL, 101.0, 10)
    engine.submit_order(Side.SELL, 102.0, 10)

    # Buy walks all three levels and rests 5 extra.
    incoming = engine.submit_order(Side.BUY, 102.0, 35)

    assert incoming.status == OrderStatus.PARTIAL
    assert incoming.filled_quantity == 30
    assert incoming.remaining_quantity == 5
    assert len(incoming.fills) == 3
    assert [f.price for f in incoming.fills] == [100.0, 101.0, 102.0]

    depth = engine.get_depth()
    assert depth.asks == []
    assert len(depth.bids) == 1
    assert depth.bids[0].quantity == 5


def test_5_price_time_priority_first_submitted_fills_first(engine: Engine) -> None:
    first = engine.submit_order(Side.BUY, 100.0, 10)   # order_id=1
    second = engine.submit_order(Side.BUY, 100.0, 10)  # order_id=2, same price

    incoming = engine.submit_order(Side.SELL, 100.0, 10)

    assert incoming.status == OrderStatus.FILLED
    assert len(incoming.fills) == 1
    # The earlier order (first) must be matched before the later one.
    assert incoming.fills[0].matched_order_id == first.order_id
    assert incoming.fills[0].matched_order_id != second.order_id

    depth = engine.get_depth()
    # second order (10 qty) should still be resting.
    assert len(depth.bids) == 1
    assert depth.bids[0].quantity == 10


def test_6_cancel_resting_order_removes_from_depth(engine: Engine) -> None:
    submitted = engine.submit_order(Side.BUY, 100.0, 10)
    assert len(engine.get_depth().bids) == 1

    engine.cancel_order(submitted.order_id)

    depth = engine.get_depth()
    assert depth.bids == []


def test_7_cancel_nonexistent_order_raises(engine: Engine) -> None:
    with pytest.raises(OrderNotFoundError):
        engine.cancel_order(999999)


@pytest.mark.parametrize(
    "side,price,quantity",
    [
        (Side.BUY, 100.0, 0),    # zero quantity
        (Side.BUY, 100.0, -5),   # negative quantity
        (Side.SELL, 0.0, 10),    # zero price
        (Side.SELL, -1.0, 10),   # negative price
    ],
)
def test_8_zero_or_negative_price_or_quantity_rejected(
    engine: Engine, side: Side, price: float, quantity: int
) -> None:
    with pytest.raises(InvalidOrderError):
        engine.submit_order(side, price, quantity)


def test_9_depth_aggregates_multiple_orders_at_same_price(engine: Engine) -> None:
    engine.submit_order(Side.BUY, 100.0, 10)
    engine.submit_order(Side.BUY, 100.0, 15)
    engine.submit_order(Side.BUY, 100.0, 5)

    depth = engine.get_depth()

    assert len(depth.bids) == 1
    assert depth.bids[0].price == 100.0
    assert depth.bids[0].quantity == 30  # 10 + 15 + 5


# --- A couple of extra edge cases from spec section 20, worth covering ---


def test_cancel_called_twice_second_call_raises(engine: Engine) -> None:
    submitted = engine.submit_order(Side.BUY, 100.0, 10)
    engine.cancel_order(submitted.order_id)

    with pytest.raises(OrderNotFoundError):
        engine.cancel_order(submitted.order_id)


def test_large_order_sweeps_book_and_rests_remainder(engine: Engine) -> None:
    engine.submit_order(Side.SELL, 100.0, 10)
    engine.submit_order(Side.SELL, 101.0, 10)

    incoming = engine.submit_order(Side.BUY, 101.0, 1000)

    assert incoming.status == OrderStatus.PARTIAL
    assert incoming.filled_quantity == 20
    assert incoming.remaining_quantity == 980

    depth = engine.get_depth()
    assert depth.asks == []
    assert depth.bids[0].quantity == 980


def test_empty_book_depth_returns_empty_lists_not_error(engine: Engine) -> None:
    depth = engine.get_depth()
    assert depth.bids == []
    assert depth.asks == []


def test_self_crossing_is_allowed_not_a_bug(engine: Engine) -> None:
    """Per spec section 20: there is no user/account concept, so an
    incoming order matching a previously-resting order is not prevented
    even in the degenerate case of 'the same caller' submitting both."""
    engine.submit_order(Side.BUY, 100.0, 10)
    result = engine.submit_order(Side.SELL, 100.0, 10)

    assert result.status == OrderStatus.FILLED
    assert len(result.fills) == 1
