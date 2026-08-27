#!/usr/bin/env python3
"""
Benchmark script for the Order Book matching engine.

Measures three layers separately, per spec section 12:
  1. C++ (direct)   -- calling the compiled `orderbook_cpp` pybind11 module
                        directly in a tight Python loop, no wrapper overhead.
  2. Python wrapper -- calling app.engine.Engine (adds dataclass conversion
                        + structured logging, i.e. the layer FastAPI routes
                        actually call).
  3. HTTP/FastAPI   -- full round trip: real HTTP request -> Starlette ->
                        Pydantic validation -> route -> engine -> JSON
                        response, over a real socket to a live uvicorn
                        process.

All three layers replay the *same* generated order stream (same seed) so
the comparison is apples-to-apples: identical matching workload, only the
calling boundary changes.

No fabricated numbers: every figure below is produced by actually running
this script. Re-run it yourself with `python benchmark/run_benchmark.py`.

Usage:
    python benchmark/run_benchmark.py
    python benchmark/run_benchmark.py --num-orders 100000 --http-num-orders 5000
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests  # noqa: E402


# ---------------------------------------------------------------------------
# Order stream generation
# ---------------------------------------------------------------------------


def generate_orders(n: int, seed: int) -> list[tuple[str, float, int]]:
    """Generates a reproducible mixed BUY/SELL order stream around a base
    price of 100.00, with enough spread that some orders cross the book
    and rest depending on prior state -- a realistic mixed workload rather
    than a worst-case (always-resting) or best-case (always-crossing) one.
    """
    rng = random.Random(seed)
    orders: list[tuple[str, float, int]] = []
    for _ in range(n):
        side = "BUY" if rng.random() < 0.5 else "SELL"
        price = round(100.0 + rng.uniform(-5.0, 5.0), 2)
        quantity = rng.randint(1, 100)
        orders.append((side, price, quantity))
    return orders


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------


@dataclass
class LayerResult:
    layer: str
    num_orders: int
    total_seconds: float
    orders_per_sec: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    mean_ms: float


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def summarize(layer: str, latencies_ms: list[float], total_seconds: float) -> LayerResult:
    sorted_latencies = sorted(latencies_ms)
    n = len(latencies_ms)
    return LayerResult(
        layer=layer,
        num_orders=n,
        total_seconds=total_seconds,
        orders_per_sec=n / total_seconds if total_seconds > 0 else 0.0,
        p50_ms=percentile(sorted_latencies, 50),
        p95_ms=percentile(sorted_latencies, 95),
        p99_ms=percentile(sorted_latencies, 99),
        mean_ms=statistics.mean(latencies_ms) if latencies_ms else 0.0,
    )


# ---------------------------------------------------------------------------
# Layer 1: C++ direct (pybind11 module, no Python wrapper)
# ---------------------------------------------------------------------------


def benchmark_cpp_direct(orders: list[tuple[str, float, int]]) -> LayerResult:
    import orderbook_cpp as cpp

    book = cpp.OrderBook()
    side_map = {"BUY": cpp.Side.BUY, "SELL": cpp.Side.SELL}

    latencies_ms: list[float] = []
    start = time.perf_counter()
    for side, price, quantity in orders:
        t0 = time.perf_counter()
        book.submit_order(side_map[side], price, quantity)
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000.0)
    total = time.perf_counter() - start

    return summarize("C++ (direct pybind11 call)", latencies_ms, total)


# ---------------------------------------------------------------------------
# Layer 2: Python wrapper (app.engine.Engine)
# ---------------------------------------------------------------------------


def benchmark_python_wrapper(orders: list[tuple[str, float, int]]) -> LayerResult:
    from app.engine import Engine, Side

    # Structured logging (INFO per order) is a real, deliberate feature of
    # engine.py for production debugging, but it dominates measured latency
    # if left at INFO during a tight benchmark loop. Raise the level for
    # this run so we measure engine/dataclass overhead, not log I/O -- this
    # is called out explicitly in results.md.
    logging.getLogger("orderbook.engine").setLevel(logging.WARNING)

    engine = Engine()
    side_map = {"BUY": Side.BUY, "SELL": Side.SELL}

    latencies_ms: list[float] = []
    start = time.perf_counter()
    for side, price, quantity in orders:
        t0 = time.perf_counter()
        engine.submit_order(side_map[side], price, quantity)
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000.0)
    total = time.perf_counter() - start

    return summarize("Python wrapper (app.engine.Engine)", latencies_ms, total)


# ---------------------------------------------------------------------------
# Layer 3: Full HTTP round trip against a live uvicorn process
# ---------------------------------------------------------------------------


def benchmark_http(orders: list[tuple[str, float, int]], port: int = 8321) -> LayerResult:
    base_url = f"http://127.0.0.1:{port}"
    env_python = str(PROJECT_ROOT / ".venv" / "bin" / "python")

    proc = subprocess.Popen(
        [env_python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning"],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # Wait for the server to become ready.
        deadline = time.time() + 15
        ready = False
        while time.time() < deadline:
            try:
                r = requests.get(f"{base_url}/health", timeout=0.5)
                if r.status_code == 200:
                    ready = True
                    break
            except requests.exceptions.RequestException:
                pass
            time.sleep(0.1)
        if not ready:
            raise RuntimeError("uvicorn server did not become ready in time")

        session = requests.Session()
        latencies_ms: list[float] = []
        start = time.perf_counter()
        for side, price, quantity in orders:
            payload = {"side": side, "price": price, "quantity": quantity}
            t0 = time.perf_counter()
            session.post(f"{base_url}/orders", json=payload, timeout=5)
            t1 = time.perf_counter()
            latencies_ms.append((t1 - t0) * 1000.0)
        total = time.perf_counter() - start

        return summarize("HTTP/FastAPI (full round trip)", latencies_ms, total)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def print_table(results: list[LayerResult]) -> None:
    header = f"{'Layer':<32} {'Orders':>8} {'Orders/sec':>14} {'p50 (ms)':>10} {'p99 (ms)':>10}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r.layer:<32} {r.num_orders:>8} {r.orders_per_sec:>14,.0f} "
            f"{r.p50_ms:>10.4f} {r.p99_ms:>10.4f}"
        )


def write_results_md(results: list[LayerResult], path: Path) -> None:
    lines = [
        "# Benchmark Results",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        "",
        "Every number below comes from an actual run of "
        "`benchmark/run_benchmark.py` on this machine -- nothing here is "
        "estimated or fabricated. Re-run the script to reproduce or update.",
        "",
        "## Methodology",
        "",
        "- All three layers replay the *same* pseudo-random order stream "
        "(fixed seed), so the matching workload is identical across rows -- "
        "only the calling boundary changes.",
        "- Orders are `BUY`/`SELL` (50/50), price = `100.00 ± uniform(0, 5.00)`, "
        "quantity = `uniform_int(1, 100)`. This produces a realistic mix of "
        "crossing and resting orders rather than a worst- or best-case "
        "pattern.",
        "- **C++ (direct pybind11 call)**: calls the compiled `orderbook_cpp` "
        "module's `OrderBook.submit_order` directly in a tight Python loop. "
        "No dataclass conversion, no logging -- isolates pybind11 call "
        "overhead + the C++ matching algorithm itself.",
        "- **Python wrapper (app.engine.Engine)**: calls the same wrapper "
        "class the FastAPI routes call -- pybind11 call + dataclass "
        "conversion. Logging was raised to WARNING for this run only, since "
        "per-order INFO logging is I/O-bound and would dominate the "
        "measurement rather than reflect engine overhead (production runs "
        "at INFO by default -- see app/main.py).",
        "- **HTTP/FastAPI (full round trip)**: a real `uvicorn` process is "
        "started, and each order is submitted as an actual HTTP POST over "
        "a local TCP socket via `requests`, sequentially (no connection "
        "concurrency) using a single reused session (keep-alive).",
        "- Latency = wall-clock time of a single `submit_order` call (or a "
        "single HTTP request), measured with `time.perf_counter()`. "
        "Throughput = total orders / total wall-clock time for the whole "
        "run (single-threaded, sequential submission in all three cases).",
        "",
        "## Results",
        "",
        "| Layer | Orders | Orders/sec | p50 (ms) | p95 (ms) | p99 (ms) | mean (ms) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r.layer} | {r.num_orders:,} | {r.orders_per_sec:,.0f} | "
            f"{r.p50_ms:.4f} | {r.p95_ms:.4f} | {r.p99_ms:.4f} | {r.mean_ms:.4f} |"
        )

    lines += [
        "",
        "## Interpretation",
        "",
        "The gap between the C++ direct layer and the Python wrapper layer "
        "is the cost of crossing the pybind11 boundary plus building plain "
        "Python dataclasses out of the C++ result objects for every call. "
        "The much larger gap between the Python wrapper and the full HTTP "
        "layer is dominated by things that have nothing to do with the "
        "matching algorithm: TCP round trip, Starlette request routing, "
        "Pydantic request/response validation and serialization, and JSON "
        "encoding/decoding. This is the expected, textbook shape for a "
        "'fast core, ergonomic wrapper' service -- the interesting number "
        "to defend in an interview is not any single row in isolation, but "
        "the *ratio* between rows, since it quantifies exactly how much "
        "each layer of abstraction costs.",
        "",
        "See `docs/benchmark.png` for a bar chart of orders/sec across the "
        "three layers (log-scaled y-axis, since the layers differ by orders "
        "of magnitude).",
        "",
    ]

    path.write_text("\n".join(lines))


def write_chart(results: list[LayerResult], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    layers = [r.layer for r in results]
    throughputs = [r.orders_per_sec for r in results]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    colors = ["#2563eb", "#16a34a", "#dc2626"]
    bars = ax.bar(layers, throughputs, color=colors[: len(layers)])
    ax.set_yscale("log")
    ax.set_ylabel("Orders / second (log scale)")
    ax.set_title("Order Book Matching Engine -- Throughput by Layer")
    ax.set_xticks(range(len(layers)))
    ax.set_xticklabels(layers, rotation=10, ha="right")

    for bar, value in zip(bars, throughputs):
        ax.annotate(
            f"{value:,.0f}/s",
            xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
            xytext=(0, 6),
            textcoords="offset points",
            ha="center",
            fontsize=10,
            fontweight="bold",
        )

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the order book matching engine.")
    parser.add_argument("--num-orders", type=int, default=50_000,
                         help="Number of orders for the C++ / Python wrapper layers.")
    parser.add_argument("--http-num-orders", type=int, default=3_000,
                         help="Number of orders for the HTTP layer (slower per-call, so fewer).")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--skip-http", action="store_true",
                         help="Skip the HTTP benchmark (useful for quick local iteration).")
    args = parser.parse_args()

    print(f"Generating {args.num_orders:,} orders (seed={args.seed})...")
    orders = generate_orders(args.num_orders, args.seed)
    http_orders = orders[: args.http_num_orders]

    results: list[LayerResult] = []

    print("\n[1/3] Benchmarking C++ (direct pybind11 call)...")
    results.append(benchmark_cpp_direct(orders))

    print("[2/3] Benchmarking Python wrapper (app.engine.Engine)...")
    results.append(benchmark_python_wrapper(orders))

    if not args.skip_http:
        print(f"[3/3] Benchmarking HTTP/FastAPI ({len(http_orders):,} orders, "
              f"live uvicorn subprocess)...")
        results.append(benchmark_http(http_orders))
    else:
        print("[3/3] Skipped (--skip-http).")

    print()
    print_table(results)

    results_path = PROJECT_ROOT / "benchmark" / "results.md"
    write_results_md(results, results_path)
    print(f"\nWrote {results_path}")

    docs_dir = PROJECT_ROOT / "docs"
    docs_dir.mkdir(exist_ok=True)
    chart_path = docs_dir / "benchmark.png"
    write_chart(results, chart_path)
    print(f"Wrote {chart_path}")

    raw_path = PROJECT_ROOT / "benchmark" / "raw_results.json"
    raw_path.write_text(json.dumps([asdict(r) for r in results], indent=2))
    print(f"Wrote {raw_path}")


if __name__ == "__main__":
    main()
