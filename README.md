# Order Book Matching Engine

A single-instrument limit order book with price-time priority matching.
The performance-critical matching logic is implemented in **C++17**,
bridged to Python via **pybind11**, and exposed over HTTP through a
**FastAPI** service. Fully unit-tested (C++ and Python), CI'd with
**GitHub Actions**, and benchmarked across three layers (C++, Python
wrapper, HTTP) with real, reproducible numbers.

This mirrors -- in miniature -- how real exchange/broker infrastructure is
built: hot path in a systems language, orchestration and API in a
higher-level language.

## Architecture

```
Client → FastAPI (validation) → Python engine wrapper → C++ matching core (pybind11)
       ← JSON response        ← fill/status data      ← match result
```

- **`cpp/`** -- C++17 `OrderBook` core: price-time priority matching,
  partial fills, cancel, depth aggregation, trade history. In-memory only
  (`std::map<price, std::deque<Order>>` per side). Has its own standalone
  smoke-test binary and CMake build, independent of Python.
- **`cpp/bindings/bindings.cpp`** -- pybind11 bindings exposing `OrderBook`
  to Python as the `orderbook_cpp` extension module (built via
  `setup.py`/`pyproject.toml`, installable with `pip install -e .`).
- **`app/engine.py`** -- thin Python wrapper: converts pybind11 objects to
  plain dataclasses, re-raises C++ exceptions as Python exceptions, adds
  structured logging. No matching logic here -- it all lives in C++.
- **`app/`** -- FastAPI app. Routes are intentionally thin (validate via
  Pydantic, call the engine, serialize the result) -- "fat model, thin
  controller."
- **`tests/`** -- pytest suite: engine-level matching edge cases + API
  tests via `TestClient`.
- **`benchmark/`** -- standalone script measuring throughput/latency at
  three layers.

**No database, no auth, no caching, no background jobs.** Single process,
in-memory state that resets on restart -- this is a deliberate scope
decision (see "Out of Scope" below), not an oversight.

## API

Interactive Swagger docs are available at `/docs` once the service is
running.

| Method | Path | Description |
|---|---|---|
| `POST` | `/orders` | Submit a limit order (`side`, `price`, `quantity`) |
| `DELETE` | `/orders/{order_id}` | Cancel a resting order |
| `GET` | `/book` | Aggregated book depth (bids desc, asks asc) |
| `GET` | `/trades` | Executed trades, most recent first |
| `GET` | `/health` | Liveness check |

**Example: `POST /orders`**
```json
// Request
{"side": "BUY", "price": 101.50, "quantity": 100}

// Response
{
  "order_id": 1,
  "status": "RESTING",
  "filled_quantity": 0,
  "remaining_quantity": 100,
  "fills": []
}
```

Order and trade IDs are simple incrementing integers, unique for the
lifetime of the running process (starting at 1) -- per project scope,
there's no persistence/auth/multi-user concept, so this is sufficient and
easy to reason about in tests.

**Error handling:** invalid input (non-positive price/quantity, wrong
type) → `422` via Pydantic validation. Cancelling an unknown / already
cancelled / already fully filled order → `404`. Unexpected engine
exceptions → `500`, logged server-side with a stack trace, generic message
to the client.

## Running locally

```bash
# 1. Create a virtualenv and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Build the C++ -> Python extension (pybind11)
pip install -e .

# 3. Run the API
uvicorn app.main:app --reload

# 4. Open http://localhost:8000/docs
```

**Standalone C++ tests** (proves the core in isolation, no Python involved):
```bash
cd cpp
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target test_order_book
./build/test_order_book
```

**Python test suite:**
```bash
pytest
```

**Benchmark:**
```bash
python benchmark/run_benchmark.py
```

## Running with Docker

A single `Dockerfile` (no docker-compose) builds the C++/pybind11 extension
inside the image and runs the API with uvicorn. It's a two-stage build: a
`builder` stage compiles `orderbook_cpp` into a wheel, and the final slim
runtime image installs `requirements.txt` + the prebuilt wheel and copies in
`app/`.

```bash
# Build the image (compiles the C++ extension inside the container)
docker build -t order-book .

# Run it, mapping the API to localhost:8000
docker run --rm -p 8000:8000 order-book

# In another terminal:
curl http://localhost:8000/health
# -> {"status":"ok"}
```

This was built and verified locally: `docker build` completes the C++
compile + wheel build + Python dependency install, and `docker run` starts
uvicorn and serves real traffic -- confirmed with a full `POST /orders` ->
`GET /book` -> `GET /trades` round trip against the running container, not
just a health check.

> **Note:** in some sandboxed/CI environments without working default bridge
> networking, `docker build`/`docker run` may need `--network=host` (e.g.
> `docker build --network=host -t order-book .`). This is an environment
> quirk, not something the Dockerfile itself requires.

## Testing Strategy

- **C++ smoke tests** (`cpp/tests/test_order_book.cpp`): 11 assert-style
  checks (using a custom `CHECK` macro that stays active in Release
  builds, unlike `assert()` which is compiled out under `NDEBUG`) covering
  matching, partial fills, price-time priority, cancel, and validation --
  run directly against the C++ core, no Python involved.
- **Python matching edge cases** (`tests/test_matching_edge_cases.py`):
  the 9 required cases from the project spec (single order rests, full
  match at resting price, partial match, multi-level walk, price-time
  priority, cancel removes from depth, cancel unknown 404s, zero/negative
  price or quantity rejected, depth aggregation), plus a few extras
  (self-crossing allowed, large sweep with remainder, double-cancel) --
  run through `app.engine.Engine`, i.e. across the real pybind11 boundary
  the API uses.
- **API tests** (`tests/test_orders.py`, `tests/test_api.py`): hit the
  FastAPI app via `TestClient`, asserting status codes and response
  shapes, including the full end-to-end user journey from the spec.
- **32 tests total**, all passing. Each test gets a fresh, isolated engine
  instance (see `tests/conftest.py`) -- no state leaks between tests.

## CI

`.github/workflows/ci.yml` runs on every push/PR to `main`:
1. Installs system build tools (`cmake`, `build-essential`) and Python deps.
2. Builds and runs the standalone C++ smoke-test binary via CMake.
3. Builds and installs the pybind11 extension (`pip install -e .`) and
   verifies it imports.
4. Runs the full `pytest` suite.

The build fails if any step fails -- this is the actual CI deliverable
called out in the project brief: simple, single-stage, does its job.

## Performance

This is the point of the project. `benchmark/run_benchmark.py` measures
three layers separately, replaying the *same* generated order stream at
each layer so the comparison is apples-to-apples:

1. **C++ (direct)** -- calling the compiled `orderbook_cpp` module
   directly in a tight loop. Isolates pybind11 call overhead + the
   matching algorithm itself.
2. **Python wrapper** -- calling `app.engine.Engine`, the same object the
   FastAPI routes call. Adds dataclass conversion.
3. **HTTP/FastAPI** -- a real `uvicorn` process, real HTTP POSTs over a
   local TCP socket. Adds Starlette routing, Pydantic validation, JSON
   (de)serialization, and the network round trip.

| Layer | Orders | Orders/sec | p50 (ms) | p95 (ms) | p99 (ms) | mean (ms) |
|---|---:|---:|---:|---:|---:|---:|
| C++ (direct pybind11 call) | 50,000 | 770,372 | 0.0010 | -- | 0.0030 | -- |
| Python wrapper (app.engine.Engine) | 50,000 | 150,143 | 0.0051 | -- | 0.0138 | -- |
| HTTP/FastAPI (full round trip) | 3,000 | 263 | 3.8298 | -- | 5.2914 | -- |

*(Full table with p95/mean, methodology, and interpretation:
[`benchmark/results.md`](benchmark/results.md). Chart:
[`docs/benchmark.png`](docs/benchmark.png). Numbers are from a real run on
this sandbox's hardware -- re-run the script yourself to reproduce; they
are not tuned or fabricated, and will vary by machine.)*

**Reading the numbers:** the ~5x drop from C++ to the Python wrapper is
the cost of crossing the pybind11 boundary and building Python dataclasses
per call. The much larger drop to the HTTP layer (~570x vs. the Python
wrapper) is dominated by things that have nothing to do with the matching
algorithm itself -- TCP round trip, Starlette routing, Pydantic
validation/serialization. That contrast is the actual interesting result:
it shows precisely what each layer of abstraction costs, which is a more
useful number to defend in an interview than any single row alone.

**What would change at scale:** shard by instrument (one `OrderBook` per
symbol), run one thread per instrument instead of sharing a single process
(real exchanges avoid locking this way), replace REST with a binary
protocol for the hot path, add a write-ahead log for crash recovery.

## In Scope / Out of Scope

**In scope:** single instrument, limit orders only, in-memory storage,
single process, REST API, price-time priority matching, partial fills.

**Out of scope (deliberate, not oversights):** multiple simultaneous
instruments, market orders, stop orders, persistence to disk/DB,
authentication, multi-user accounts, distributed/multi-node matching,
order book replay/recovery, FIX protocol support, self-crossing
prevention (no user/account concept exists, so an order can legitimately
match a previously-resting order from "the same caller").

## Future Expansion

Multiple instruments (multiple `OrderBook` instances keyed by symbol),
market orders, order modification (cancel-replace), persistence (trades to
SQLite/Postgres), WebSocket depth streaming instead of polling,
multi-threading with per-instrument locks.

## Tech Stack

C++17 · pybind11 · Python 3.11+ · FastAPI · Pydantic · pytest ·
GitHub Actions · matplotlib (benchmark chart)

## Status

- ✅ C++ core + standalone tests
- ✅ pybind11 bridge (real, not the documented fallback -- built and
  verified importable in under 2 minutes)
- ✅ FastAPI service wired to the C++ engine
- ✅ 32 passing tests (engine-level + API-level)
- ✅ GitHub Actions CI (verified locally against a clean venv before commit)
- ✅ Benchmark script + real results + chart
- ✅ Dockerfile (single file, no docker-compose -- builds the C++/pybind11
  extension inside the image; `docker build` + `docker run` verified with a
  real `POST /orders` -> `GET /book` -> `GET /trades` round trip, not just a
  health check)
- ⏳ Optional HTML depth viewer (explicitly out of scope for the initial
  build per project priorities)
