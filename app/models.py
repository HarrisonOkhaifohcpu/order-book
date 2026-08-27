"""Pydantic request/response schemas for the Order Book API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.engine import OrderStatus, Side


class OrderCreateRequest(BaseModel):
    """POST /orders request body."""

    side: Side
    price: float = Field(..., gt=0, description="Limit price, must be positive")
    quantity: int = Field(..., gt=0, description="Order quantity, must be a positive integer")

    model_config = {
        "json_schema_extra": {
            "examples": [{"side": "BUY", "price": 101.50, "quantity": 100}]
        }
    }


class FillResponse(BaseModel):
    price: float
    quantity: int
    matched_order_id: int


class OrderCreateResponse(BaseModel):
    """POST /orders response body."""

    order_id: int
    status: OrderStatus
    filled_quantity: int
    remaining_quantity: int
    fills: list[FillResponse] = Field(default_factory=list)


class CancelOrderResponse(BaseModel):
    """DELETE /orders/{order_id} response body."""

    order_id: int
    status: str = "CANCELLED"


class DepthLevelResponse(BaseModel):
    price: float
    quantity: int


class BookDepthResponse(BaseModel):
    """GET /book response body."""

    bids: list[DepthLevelResponse] = Field(default_factory=list)
    asks: list[DepthLevelResponse] = Field(default_factory=list)


class TradeResponse(BaseModel):
    """One entry in the GET /trades response list."""

    trade_id: int
    price: float
    quantity: int
    buy_order_id: int
    sell_order_id: int
    timestamp_ms: int


class ErrorResponse(BaseModel):
    """Standard error body used by exception handlers."""

    detail: str
