# Benchmark Results

Generated: 2026-08-27 16:27:32 UTC

Every number below comes from an actual run of `benchmark/run_benchmark.py` on this machine -- nothing here is estimated or fabricated. Re-run the script to reproduce or update.

## Methodology

- All three layers replay the *same* pseudo-random order stream (fixed seed), so the matching workload is identical across rows -- only the calling boundary changes.
- Orders are `BUY`/`SELL` (50/50), price = `100.00 ± uniform(0, 5.00)`, quantity = `uniform_int(1, 100)`. This produces a realistic mix of crossing and resting orders rather than a worst- or best-case pattern.
- **C++ (direct pybind11 call)**: calls the compiled `orderbook_cpp` module's `OrderBook.submit_order` directly in a tight Python loop. No dataclass conversion, no logging -- isolates pybind11 call overhead + the C++ matching algorithm itself.
- **Python wrapper (app.engine.Engine)**: calls the same wrapper class the FastAPI routes call -- pybind11 call + dataclass conversion. Logging was raised to WARNING for this run only, since per-order INFO logging is I/O-bound and would dominate the measurement rather than reflect engine overhead (production runs at INFO by default -- see app/main.py).
- **HTTP/FastAPI (full round trip)**: a real `uvicorn` process is started, and each order is submitted as an actual HTTP POST over a local TCP socket via `requests`, sequentially (no connection concurrency) using a single reused session (keep-alive).
- Latency = wall-clock time of a single `submit_order` call (or a single HTTP request), measured with `time.perf_counter()`. Throughput = total orders / total wall-clock time for the whole run (single-threaded, sequential submission in all three cases).

## Results

| Layer | Orders | Orders/sec | p50 (ms) | p95 (ms) | p99 (ms) | mean (ms) |
|---|---:|---:|---:|---:|---:|---:|
| C++ (direct pybind11 call) | 50,000 | 770,372 | 0.0010 | 0.0014 | 0.0030 | 0.0011 |
| Python wrapper (app.engine.Engine) | 50,000 | 150,143 | 0.0051 | 0.0102 | 0.0138 | 0.0065 |
| HTTP/FastAPI (full round trip) | 3,000 | 263 | 3.8298 | 4.5600 | 5.2914 | 3.8002 |

## Interpretation

The gap between the C++ direct layer and the Python wrapper layer is the cost of crossing the pybind11 boundary plus building plain Python dataclasses out of the C++ result objects for every call. The much larger gap between the Python wrapper and the full HTTP layer is dominated by things that have nothing to do with the matching algorithm: TCP round trip, Starlette request routing, Pydantic request/response validation and serialization, and JSON encoding/decoding. This is the expected, textbook shape for a 'fast core, ergonomic wrapper' service -- the interesting number to defend in an interview is not any single row in isolation, but the *ratio* between rows, since it quantifies exactly how much each layer of abstraction costs.

See `docs/benchmark.png` for a bar chart of orders/sec across the three layers (log-scaled y-axis, since the layers differ by orders of magnitude).
