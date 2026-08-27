"""FastAPI application entry point.

Run locally with:
    uvicorn app.main:app --reload

Then open http://localhost:8000/docs for interactive Swagger UI.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.engine import InvalidOrderError, OrderNotFoundError
from app.routes import book, orders

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("orderbook.api")

app = FastAPI(
    title="Order Book Matching Engine",
    description=(
        "A single-instrument limit order book with price-time priority "
        "matching. Core matching logic runs in a C++ engine, bridged to "
        "Python via pybind11. See README for architecture and scope notes."
    ),
    version="1.0.0",
)

app.include_router(orders.router)
app.include_router(book.router)


@app.exception_handler(OrderNotFoundError)
async def order_not_found_handler(request: Request, exc: OrderNotFoundError) -> JSONResponse:
    logger.info("order not found: %s", exc.order_id)
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(InvalidOrderError)
async def invalid_order_handler(request: Request, exc: InvalidOrderError) -> JSONResponse:
    logger.info("invalid order rejected: %s", exc)
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Anything else is unexpected (should not happen if validation + the two
    # handlers above are correct) -- log full detail server-side, return a
    # generic message to the client per the spec's error-handling section.
    logger.exception("unhandled exception while processing %s %s", request.method, request.url)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Simple liveness check, useful for CI/Docker healthchecks."""
    return {"status": "ok"}
