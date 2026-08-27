"""Basic API tests for POST /orders and DELETE /orders/{id}, hit via
FastAPI's TestClient (in-process, no real network -- see spec section 14)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_submit_order_rests_on_empty_book(client: TestClient) -> None:
    response = client.post("/orders", json={"side": "BUY", "price": 100.0, "quantity": 50})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "RESTING"
    assert body["filled_quantity"] == 0
    assert body["remaining_quantity"] == 50
    assert body["fills"] == []
    assert isinstance(body["order_id"], int)


def test_submit_order_crosses_and_fills(client: TestClient) -> None:
    client.post("/orders", json={"side": "BUY", "price": 100.0, "quantity": 50})
    response = client.post("/orders", json={"side": "SELL", "price": 99.0, "quantity": 30})

    assert response.status_code == 200
    body = response.json()
    # The incoming SELL order (qty 30) is smaller than the resting BUY (qty
    # 50), so the incoming order itself fills completely -- status reflects
    # the INCOMING order, not the resting one (which is left PARTIALly
    # filled with 20 remaining, verifiable via GET /book).
    assert body["status"] == "FILLED"
    assert body["filled_quantity"] == 30
    assert body["remaining_quantity"] == 0
    assert len(body["fills"]) == 1
    assert body["fills"][0]["price"] == 100.0


def test_cancel_resting_order_succeeds(client: TestClient) -> None:
    submit_response = client.post("/orders", json={"side": "BUY", "price": 100.0, "quantity": 10})
    order_id = submit_response.json()["order_id"]

    cancel_response = client.delete(f"/orders/{order_id}")

    assert cancel_response.status_code == 200
    assert cancel_response.json() == {"order_id": order_id, "status": "CANCELLED"}


def test_cancel_unknown_order_returns_404(client: TestClient) -> None:
    response = client.delete("/orders/999999")

    assert response.status_code == 404
    assert "detail" in response.json()


def test_cancel_already_cancelled_order_returns_404(client: TestClient) -> None:
    submit_response = client.post("/orders", json={"side": "SELL", "price": 50.0, "quantity": 5})
    order_id = submit_response.json()["order_id"]
    client.delete(f"/orders/{order_id}")

    second_cancel = client.delete(f"/orders/{order_id}")

    assert second_cancel.status_code == 404


def test_cancel_already_filled_order_returns_404(client: TestClient) -> None:
    submit_response = client.post("/orders", json={"side": "BUY", "price": 100.0, "quantity": 10})
    order_id = submit_response.json()["order_id"]
    # Fully fill it.
    client.post("/orders", json={"side": "SELL", "price": 100.0, "quantity": 10})

    response = client.delete(f"/orders/{order_id}")

    assert response.status_code == 404


def test_submit_order_zero_quantity_returns_422(client: TestClient) -> None:
    response = client.post("/orders", json={"side": "BUY", "price": 100.0, "quantity": 0})
    assert response.status_code == 422


def test_submit_order_negative_price_returns_422(client: TestClient) -> None:
    response = client.post("/orders", json={"side": "BUY", "price": -5.0, "quantity": 10})
    assert response.status_code == 422


def test_submit_order_missing_field_returns_422(client: TestClient) -> None:
    response = client.post("/orders", json={"side": "BUY", "price": 100.0})
    assert response.status_code == 422


def test_submit_order_invalid_side_returns_422(client: TestClient) -> None:
    response = client.post("/orders", json={"side": "HOLD", "price": 100.0, "quantity": 10})
    assert response.status_code == 422
