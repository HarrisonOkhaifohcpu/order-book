#pragma once

#include <cstdint>
#include <deque>
#include <map>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace orderbook {

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

enum class Side { BUY, SELL };

enum class OrderStatus { FILLED, PARTIAL, RESTING };

// ---------------------------------------------------------------------------
// Exceptions
// ---------------------------------------------------------------------------

// Thrown when a caller attempts to cancel an order that does not exist,
// was already cancelled, or has already been fully filled.
class OrderNotFoundError : public std::runtime_error {
public:
    explicit OrderNotFoundError(int64_t order_id)
        : std::runtime_error("Order not found: " + std::to_string(order_id)),
          order_id_(order_id) {}

    int64_t order_id() const { return order_id_; }

private:
    int64_t order_id_;
};

// Thrown when an order fails basic sanity checks (non-positive price/quantity).
class InvalidOrderError : public std::invalid_argument {
public:
    explicit InvalidOrderError(const std::string& message)
        : std::invalid_argument(message) {}
};

// ---------------------------------------------------------------------------
// Core data types
// ---------------------------------------------------------------------------

// A single resting/incoming order. `remaining_quantity` is mutated in place
// as it gets matched; `quantity` always records the original size.
struct Order {
    int64_t id = 0;
    Side side = Side::BUY;
    double price = 0.0;
    int64_t quantity = 0;           // original quantity submitted
    int64_t remaining_quantity = 0; // quantity still unfilled
    int64_t sequence = 0;           // monotonically increasing, breaks price ties (time priority)
};

// One match produced while processing an incoming order.
struct Fill {
    double price = 0.0;
    int64_t quantity = 0;
    int64_t matched_order_id = 0; // the resting order on the other side of the trade
};

// The result of submitting a single order to the engine.
struct SubmitResult {
    int64_t order_id = 0;
    OrderStatus status = OrderStatus::RESTING;
    int64_t filled_quantity = 0;
    int64_t remaining_quantity = 0;
    std::vector<Fill> fills;
};

// A fully executed trade, recorded in the engine's trade history.
struct Trade {
    int64_t trade_id = 0;
    double price = 0.0;
    int64_t quantity = 0;
    int64_t buy_order_id = 0;
    int64_t sell_order_id = 0;
    int64_t timestamp_ms = 0; // epoch milliseconds
};

// One aggregated price level in the book depth view.
struct DepthLevel {
    double price = 0.0;
    int64_t quantity = 0; // sum of remaining quantity across all orders at this price
};

// Full book snapshot: bids sorted best-first (descending), asks sorted
// best-first (ascending).
struct BookDepth {
    std::vector<DepthLevel> bids;
    std::vector<DepthLevel> asks;
};

// ---------------------------------------------------------------------------
// OrderBook
// ---------------------------------------------------------------------------
//
// A single-instrument, in-memory limit order book with price-time priority
// matching. Not thread-safe by design (real exchanges run one thread per
// instrument to avoid locking) -- see README for discussion.
class OrderBook {
public:
    OrderBook() = default;

    // Submits a new limit order. Attempts to match against the opposite
    // side of the book first (price-time priority); any unfilled remainder
    // rests on this order's own side. Throws InvalidOrderError if price or
    // quantity is not strictly positive.
    SubmitResult submit_order(Side side, double price, int64_t quantity);

    // Cancels a resting (unfilled or partially filled) order by id.
    // Throws OrderNotFoundError if the id is unknown, already cancelled,
    // or already fully filled.
    void cancel_order(int64_t order_id);

    // Returns the current aggregated book depth (bids desc, asks asc).
    BookDepth get_depth() const;

    // Returns all executed trades, most recent first.
    std::vector<Trade> get_trades() const;

    // Total number of orders currently resting on the book (both sides).
    // Exposed mainly for tests/diagnostics.
    size_t resting_order_count() const { return order_index_.size(); }

private:
    // Where a resting order lives: which side, and which price level.
    struct OrderLocation {
        Side side;
        double price;
    };

    // Price level containers.
    // Bids: best price = highest, so descending order.
    // Asks: best price = lowest, so ascending order (map default).
    std::map<double, std::deque<Order>, std::greater<double>> bids_;
    std::map<double, std::deque<Order>, std::less<double>> asks_;

    // order_id -> location, for O(1) lookup during cancel (the deque itself
    // is still scanned linearly to erase, which is fine at portfolio scale
    // and keeps the implementation simple/obviously correct).
    std::unordered_map<int64_t, OrderLocation> order_index_;

    // Trade history, insertion order (oldest first internally; reversed on read).
    std::vector<Trade> trades_;

    int64_t next_order_id_ = 1;
    int64_t next_trade_id_ = 1;
    int64_t next_sequence_ = 1;

    static int64_t now_ms();
};

// Converts Side to a short string, used for logging/debugging.
const char* to_string(Side side);
const char* to_string(OrderStatus status);

} // namespace orderbook
