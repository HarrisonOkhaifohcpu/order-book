"""
Build script for the `orderbook_cpp` pybind11 extension module.

This compiles the same C++ sources used by the standalone CMake build
(cpp/src/order_book.cpp) together with the pybind11 bindings
(cpp/bindings/bindings.cpp) into a single importable Python extension.

Usage:
    pip install .        # build + install
    pip install -e .     # editable install (rebuilds in place)
"""

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

ext_modules = [
    Pybind11Extension(
        "orderbook_cpp",
        sources=[
            "cpp/src/order_book.cpp",
            "cpp/bindings/bindings.cpp",
        ],
        include_dirs=["cpp/include"],
        cxx_std=17,
    ),
]

setup(
    name="orderbook_cpp",
    version="1.0.0",
    description="C++ limit order book matching engine (pybind11 extension)",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
    python_requires=">=3.9",
)
