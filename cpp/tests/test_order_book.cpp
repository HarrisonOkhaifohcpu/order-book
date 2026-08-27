// Simple check-based smoke tests for the OrderBook core.
// No external test framework dependency (Catch2 not required) -- keeps the
// C++ build minimal. Run the compiled binary; it exits non-zero on failure
// and prints "ALL TESTS PASSED" on success.
//
// NOTE: we deliberately do NOT use the standard library's assert() here.
// assert() compiles to a no-op when NDEBUG is defined (which CMake sets in
// Release builds), so a test suite built entirely on assert() would silently
// pass without checking anything in Release mode. CHECK() below always
// evaluates its condition, in every build configuration.

#include "order_book.hpp"

#include <cmath>
#include <cstdlib>
#include <iostream>

#define CHECK(cond)                                                          \
    do {                                                                     \
        if (!(cond)) {                                                       \
            std::cerr << "CHECK FAILED: " #cond " at " << __FILE__ << ":"    \
                      << __LINE__ << "\n";                                   \
            std::exit(1);                                                    \
        }                                                                    \
    } while (0)

using namespace orderbook;

namespace {

bool approx_equal(double a, double b, double eps = 1e-9) {
    return std::fabs(a - b) < eps;
}

void test_single_order_rests_on_empty_book() {
    OrderBook book;
    auto result = book.submit_order(Side::BUY, 100.0, 50);

    CHECK(result.status == OrderStatus::RESTING);
    CHECK(result.filled_quantity == 0);
    CHECK(result.remaining_quantity == 50);
    CHECK(result.fills.empty());

    auto depth = book.get_depth();
    CHECK(depth.bids.size() == 1);
    CHECK(approx_equal(depth.bids[0].price, 100.0));
    CHECK(depth.bids[0].quantity == 50);
    CHECK(depth.asks.empty());

    std::cout << "test_single_order_rests_on_empty_book PASSED\n";
}

void test_full_match_at_resting_price() {
    OrderBook book;
    book.submit_order(Side::BUY, 100.0, 50); // resting order id=1

    auto result = book.submit_order(Side::SELL, 99.0, 50); // crosses

    CHECK(result.status == OrderStatus::FILLED);
    CHECK(result.filled_quantity == 50);
    CHECK(result.remaining_quantity == 0);
    CHECK(result.fills.size() == 1);
    // Match occurs at the RESTING order's price (100.0), not the incoming
    // sell's limit price (99.0).
    CHECK(approx_equal(result.fills[0].price, 100.0));
    CHECK(result.fills[0].quantity == 50);
    CHECK(result.fills[0].matched_order_id == 1);

    auto depth = book.get_depth();
    CHECK(depth.bids.empty());
    CHECK(depth.asks.empty());

    auto trades = book.get_trades();
    CHECK(trades.size() == 1);
    CHECK(approx_equal(trades[0].price, 100.0));
    CHECK(trades[0].buy_order_id == 1);
    CHECK(trades[0].sell_order_id == 2);

    std::cout << "test_full_match_at_resting_price PASSED\n";
}

void test_partial_match_remainder_rests() {
    OrderBook book;
    book.submit_order(Side::SELL, 100.0, 30); // resting id=1

    auto result = book.submit_order(Side::BUY, 100.0, 50); // only 30 available

    CHECK(result.status == OrderStatus::PARTIAL);
    CHECK(result.filled_quantity == 30);
    CHECK(result.remaining_quantity == 20);
    CHECK(result.fills.size() == 1);

    auto depth = book.get_depth();
    CHECK(depth.asks.empty());
    CHECK(depth.bids.size() == 1);
    CHECK(depth.bids[0].quantity == 20);

    std::cout << "test_partial_match_remainder_rests PASSED\n";
}

void test_walks_multiple_price_levels() {
    OrderBook book;
    book.submit_order(Side::SELL, 100.0, 10); // id=1
    book.submit_order(Side::SELL, 101.0, 10); // id=2
    book.submit_order(Side::SELL, 102.0, 10); // id=3

    // Buy enough to sweep all three levels plus rest 5 extra.
    auto result = book.submit_order(Side::BUY, 102.0, 35);

    CHECK(result.status == OrderStatus::PARTIAL);
    CHECK(result.filled_quantity == 30);
    CHECK(result.remaining_quantity == 5);
    CHECK(result.fills.size() == 3);
    CHECK(approx_equal(result.fills[0].price, 100.0));
    CHECK(approx_equal(result.fills[1].price, 101.0));
    CHECK(approx_equal(result.fills[2].price, 102.0));

    auto depth = book.get_depth();
    CHECK(depth.asks.empty());
    CHECK(depth.bids.size() == 1);
    CHECK(depth.bids[0].quantity == 5);

    std::cout << "test_walks_multiple_price_levels PASSED\n";
}

void test_price_time_priority() {
    OrderBook book;
    book.submit_order(Side::BUY, 100.0, 10); // id=1, first in queue
    book.submit_order(Side::BUY, 100.0, 10); // id=2, second in queue

    auto result = book.submit_order(Side::SELL, 100.0, 10);

    CHECK(result.status == OrderStatus::FILLED);
    CHECK(result.fills.size() == 1);
    // The FIRST submitted buy order (id=1) should be matched first.
    CHECK(result.fills[0].matched_order_id == 1);

    auto depth = book.get_depth();
    CHECK(depth.bids.size() == 1);
    CHECK(depth.bids[0].quantity == 10); // order id=2 still resting

    std::cout << "test_price_time_priority PASSED\n";
}

void test_cancel_removes_from_depth() {
    OrderBook book;
    auto submitted = book.submit_order(Side::BUY, 100.0, 10);
    CHECK(book.resting_order_count() == 1);

    book.cancel_order(submitted.order_id);
    CHECK(book.resting_order_count() == 0);

    auto depth = book.get_depth();
    CHECK(depth.bids.empty());

    std::cout << "test_cancel_removes_from_depth PASSED\n";
}

void test_cancel_unknown_order_throws() {
    OrderBook book;
    bool threw = false;
    try {
        book.cancel_order(9999);
    } catch (const OrderNotFoundError&) {
        threw = true;
    }
    CHECK(threw);

    std::cout << "test_cancel_unknown_order_throws PASSED\n";
}

void test_cancel_twice_throws_second_time() {
    OrderBook book;
    auto submitted = book.submit_order(Side::BUY, 100.0, 10);
    book.cancel_order(submitted.order_id);

    bool threw = false;
    try {
        book.cancel_order(submitted.order_id);
    } catch (const OrderNotFoundError&) {
        threw = true;
    }
    CHECK(threw);

    std::cout << "test_cancel_twice_throws_second_time PASSED\n";
}

void test_invalid_order_rejected() {
    OrderBook book;

    bool threw_zero_qty = false;
    try {
        book.submit_order(Side::BUY, 100.0, 0);
    } catch (const InvalidOrderError&) {
        threw_zero_qty = true;
    }
    CHECK(threw_zero_qty);

    bool threw_neg_price = false;
    try {
        book.submit_order(Side::BUY, -5.0, 10);
    } catch (const InvalidOrderError&) {
        threw_neg_price = true;
    }
    CHECK(threw_neg_price);

    bool threw_zero_price = false;
    try {
        book.submit_order(Side::SELL, 0.0, 10);
    } catch (const InvalidOrderError&) {
        threw_zero_price = true;
    }
    CHECK(threw_zero_price);

    std::cout << "test_invalid_order_rejected PASSED\n";
}

void test_depth_aggregates_same_price() {
    OrderBook book;
    book.submit_order(Side::BUY, 100.0, 10);
    book.submit_order(Side::BUY, 100.0, 15);
    book.submit_order(Side::BUY, 100.0, 5);

    auto depth = book.get_depth();
    CHECK(depth.bids.size() == 1);
    CHECK(depth.bids[0].quantity == 30);

    std::cout << "test_depth_aggregates_same_price PASSED\n";
}

void test_empty_book_depth() {
    OrderBook book;
    auto depth = book.get_depth();
    CHECK(depth.bids.empty());
    CHECK(depth.asks.empty());

    std::cout << "test_empty_book_depth PASSED\n";
}

} // namespace

int main() {
    test_single_order_rests_on_empty_book();
    test_full_match_at_resting_price();
    test_partial_match_remainder_rests();
    test_walks_multiple_price_levels();
    test_price_time_priority();
    test_cancel_removes_from_depth();
    test_cancel_unknown_order_throws();
    test_cancel_twice_throws_second_time();
    test_invalid_order_rejected();
    test_depth_aggregates_same_price();
    test_empty_book_depth();

    std::cout << "\nALL TESTS PASSED\n";
    return 0;
}
