"""API-level tests for GET /book, GET /trades, and the general
request/response shape guarantees (empty states, health check)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_get_book_depth_empty_book_returns_empty_arrays(client: TestClient) -> None:
    response = client.get("/book")

    assert response.status_code == 200
    assert response.json() == {"bids": [], "asks": []}


def test_get_book_depth_reflects_resting_orders(client: TestClient) -> None:
    client.post("/orders", json={"side": "BUY", "price": 100.0, "quantity": 20})
    client.post("/orders", json={"side": "BUY", "price": 99.0, "quantity": 15})
    client.post("/orders", json={"side": "SELL", "price": 105.0, "quantity": 10})

    response = client.get("/book")
    body = response.json()

    # Bids sorted descending (best/highest first).
    assert body["bids"] == [
        {"price": 100.0, "quantity": 20},
        {"price": 99.0, "quantity": 15},
    ]
    # Asks sorted ascending (best/lowest first).
    assert body["asks"] == [{"price": 105.0, "quantity": 10}]


def test_get_trades_empty_when_no_matches(client: TestClient) -> None:
    response = client.get("/trades")

    assert response.status_code == 200
    assert response.json() == []


def test_get_trades_lists_executed_trade_most_recent_first(client: TestClient) -> None:
    client.post("/orders", json={"side": "BUY", "price": 100.0, "quantity": 10})
    client.post("/orders", json={"side": "SELL", "price": 99.0, "quantity": 10})  # trade 1
    client.post("/orders", json={"side": "BUY", "price": 105.0, "quantity": 5})
    client.post("/orders", json={"side": "SELL", "price": 104.0, "quantity": 5})  # trade 2

    response = client.get("/trades")
    trades = response.json()

    assert len(trades) == 2
    # Most recent first: trade 2 (price 105.0) should come before trade 1 (price 100.0).
    assert trades[0]["price"] == 105.0
    assert trades[1]["price"] == 100.0
    for trade in trades:
        assert set(trade.keys()) == {
            "trade_id",
            "price",
            "quantity",
            "buy_order_id",
            "sell_order_id",
            "timestamp_ms",
        }


def test_health_check(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_full_user_journey_from_spec_section_19(client: TestClient) -> None:
    """Mirrors the exact walkthrough in spec section 19."""
    # 1. BUY 100.00 x 50 -> rests (book was empty)
    r1 = client.post("/orders", json={"side": "BUY", "price": 100.00, "quantity": 50})
    assert r1.json()["status"] == "RESTING"
    buy_order_id = r1.json()["order_id"]

    # 2. SELL 99.00 x 30 -> crosses, matches 30 @ 100.00, buy now has 20 remaining resting
    r2 = client.post("/orders", json={"side": "SELL", "price": 99.00, "quantity": 30})
    assert r2.json()["status"] == "FILLED"
    assert r2.json()["fills"][0]["price"] == 100.00
    assert r2.json()["fills"][0]["matched_order_id"] == buy_order_id

    # 3. GET /book -> bid depth of 20 @ 100.00
    r3 = client.get("/book")
    assert r3.json()["bids"] == [{"price": 100.00, "quantity": 20}]

    # 4. GET /trades -> sees the one trade logged
    r4 = client.get("/trades")
    assert len(r4.json()) == 1
    assert r4.json()[0]["quantity"] == 30
