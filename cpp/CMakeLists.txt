cmake_minimum_required(VERSION 3.15)
project(order_book_engine CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

add_compile_options(-Wall -Wextra)

# ---------------------------------------------------------------------------
# Core static library (matching engine, no Python dependency)
# ---------------------------------------------------------------------------
add_library(order_book_core STATIC
    src/order_book.cpp
)
target_include_directories(order_book_core PUBLIC include)
# Required so this static lib can be linked into the pybind11 shared module.
set_target_properties(order_book_core PROPERTIES POSITION_INDEPENDENT_CODE ON)

# ---------------------------------------------------------------------------
# Standalone C++ smoke test executable
# ---------------------------------------------------------------------------
add_executable(test_order_book tests/test_order_book.cpp)
target_link_libraries(test_order_book PRIVATE order_book_core)

# ---------------------------------------------------------------------------
# Optional: pybind11 Python extension module
# Enable with: cmake -DBUILD_PYBIND=ON ..
# ---------------------------------------------------------------------------
option(BUILD_PYBIND "Build the pybind11 Python extension module" OFF)

if(BUILD_PYBIND)
    find_package(pybind11 REQUIRED)
    pybind11_add_module(orderbook_cpp bindings/bindings.cpp)
    target_link_libraries(orderbook_cpp PRIVATE order_book_core)
endif()
