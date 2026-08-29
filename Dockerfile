# syntax=docker/dockerfile:1
#
# Order Book Matching Engine — single-file Docker build (no docker-compose).
#
# Multi-stage build:
#   1. "builder" stage compiles the C++ core + pybind11 bindings into an
#      installable wheel (orderbook_cpp), using the same setup.py / pyproject.toml
#      used for local `pip install -e .` / CI.
#   2. Final stage is a slim runtime image: installs Python dependencies from
#      requirements.txt, installs the prebuilt orderbook_cpp wheel, copies in
#      the FastAPI app source, and runs it with uvicorn.
#
# Build:  docker build -t order-book .
# Run:    docker run --rm -p 8000:8000 order-book
# Then:   curl http://localhost:8000/health

# ---------------------------------------------------------------------------
# Stage 1: build the orderbook_cpp pybind11 extension as a wheel
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

# g++ / make etc. needed to compile the C++ extension. cmake is NOT required
# here — setup.py builds the pybind11 extension directly via
# Pybind11Extension/setuptools, the CMake build is only used for the
# standalone C++ smoke tests (not part of the runtime image).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Only copy what's needed to build the extension (keeps the build cache
# stable if app/ or tests/ change without touching the C++ sources).
COPY pyproject.toml setup.py ./
COPY cpp ./cpp

RUN pip install --no-cache-dir --upgrade pip wheel \
    && pip wheel --no-cache-dir --no-deps -w /build/dist .

# ---------------------------------------------------------------------------
# Stage 2: runtime image
# ---------------------------------------------------------------------------
FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies (FastAPI, uvicorn, pydantic, plus the
# test/benchmark deps declared in requirements.txt — kept as the single
# source of dependencies shared with local dev and CI).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install the prebuilt orderbook_cpp wheel from the builder stage.
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -rf /tmp/*.whl

# Application source.
COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
