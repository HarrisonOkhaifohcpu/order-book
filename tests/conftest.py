"""Shared pytest fixtures.

Both the engine-level tests and the API tests need a *fresh* order book per
test case (no leakage of order ids / resting orders between tests). The
FastAPI app wires routes to a module-level singleton (`app.engine.engine`)
so that a single process shares one book across requests in production;
for tests we monkeypatch that singleton (and the reference each route
module imported it under) with a brand-new Engine before every test.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.engine as engine_module
import app.routes.book as book_routes
import app.routes.orders as orders_routes
from app.engine import Engine
from app.main import app as fastapi_app


@pytest.fixture()
def engine() -> Engine:
    """A fresh, isolated Engine instance for pure engine-level unit tests."""
    return Engine()


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A TestClient backed by a fresh Engine, isolated per test."""
    fresh_engine = Engine()
    monkeypatch.setattr(engine_module, "engine", fresh_engine)
    monkeypatch.setattr(orders_routes, "engine", fresh_engine)
    monkeypatch.setattr(book_routes, "engine", fresh_engine)
    return TestClient(fastapi_app)
