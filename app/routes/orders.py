"""Routes for submitting and cancelling orders.

Kept thin per the spec's "fat model / thin controller" pattern: all
matching logic lives in the C++ engine (via app.engine), routes only
validate input (via Pydantic) and translate engine results to responses.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.engine import InvalidOrderError, OrderNotFoundError, engine
from app.models import (
    CancelOrderResponse,
    FillResponse,
    OrderCreateRequest,
    OrderCreateResponse,
)

router = APIRouter(tags=["orders"])


@router.post("/orders", response_model=OrderCreateResponse)
def submit_order(order: OrderCreateRequest) -> OrderCreateResponse:
    """Submit a new limit order. Matches immediately against the opposite
    side of the book (price-time priority); any remainder rests."""
    # InvalidOrderError is defensive here -- Pydantic's gt=0 constraints on
    # OrderCreateRequest already reject non-positive price/quantity with a
    # 422 before this handler runs. The registered exception handler in
    # main.py still covers this path in case validation rules ever diverge
    # from the engine's own invariants.
    result = engine.submit_order(order.side, order.price, order.quantity)
    return OrderCreateResponse(
        order_id=result.order_id,
        status=result.status,
        filled_quantity=result.filled_quantity,
        remaining_quantity=result.remaining_quantity,
        fills=[
            FillResponse(price=f.price, quantity=f.quantity, matched_order_id=f.matched_order_id)
            for f in result.fills
        ],
    )


@router.delete("/orders/{order_id}", response_model=CancelOrderResponse)
def cancel_order(order_id: int) -> CancelOrderResponse:
    """Cancel a resting order. Raises 404 (via registered exception handler)
    if the order id is unknown, already cancelled, or already fully filled."""
    engine.cancel_order(order_id)  # raises OrderNotFoundError -> 404
    return CancelOrderResponse(order_id=order_id, status="CANCELLED")


__all__ = ["router", "InvalidOrderError", "OrderNotFoundError"]
