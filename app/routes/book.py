"""Routes for reading book depth and trade history (read-only, no matching)."""

from __future__ import annotations

from fastapi import APIRouter

from app.engine import engine
from app.models import BookDepthResponse, DepthLevelResponse, TradeResponse

router = APIRouter(tags=["book"])


@router.get("/book", response_model=BookDepthResponse)
def get_book_depth() -> BookDepthResponse:
    """Current resting orders aggregated by price level.
    Empty book returns empty arrays, not an error."""
    depth = engine.get_depth()
    return BookDepthResponse(
        bids=[DepthLevelResponse(price=lvl.price, quantity=lvl.quantity) for lvl in depth.bids],
        asks=[DepthLevelResponse(price=lvl.price, quantity=lvl.quantity) for lvl in depth.asks],
    )


@router.get("/trades", response_model=list[TradeResponse])
def get_trades() -> list[TradeResponse]:
    """Executed trades, most recent first."""
    trades = engine.get_trades()
    return [
        TradeResponse(
            trade_id=t.trade_id,
            price=t.price,
            quantity=t.quantity,
            buy_order_id=t.buy_order_id,
            sell_order_id=t.sell_order_id,
            timestamp_ms=t.timestamp_ms,
        )
        for t in trades
    ]
