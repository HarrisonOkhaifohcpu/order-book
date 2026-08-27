#include "order_book.hpp"

#include <chrono>

namespace orderbook {

const char* to_string(Side side) {
    switch (side) {
        case Side::BUY:  return "BUY";
        case Side::SELL: return "SELL";
    }
    return "UNKNOWN";
}

const char* to_string(OrderStatus status) {
    switch (status) {
        case OrderStatus::FILLED:  return "FILLED";
        case OrderStatus::PARTIAL: return "PARTIAL";
        case OrderStatus::RESTING: return "RESTING";
    }
    return "UNKNOWN";
}

int64_t OrderBook::now_ms() {
    using namespace std::chrono;
    return duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
}

SubmitResult OrderBook::submit_order(Side side, double price, int64_t quantity) {
    if (price <= 0.0) {
        throw InvalidOrderError("price must be positive");
    }
    if (quantity <= 0) {
        throw InvalidOrderError("quantity must be positive");
    }

    const int64_t incoming_id = next_order_id_++;
    int64_t remaining = quantity;
    std::vector<Fill> fills;

    if (side == Side::BUY) {
        // Match against asks while the best ask is at or below our price.
        while (remaining > 0 && !asks_.empty()) {
            auto level_it = asks_.begin(); // lowest price = best ask
            const double level_price = level_it->first;
            if (level_price > price) {
                break; // best ask too expensive, no more crosses possible
            }
            std::deque<Order>& queue = level_it->second;

            while (remaining > 0 && !queue.empty()) {
                Order& resting = queue.front(); // oldest first = time priority
                const int64_t trade_qty = std::min(remaining, resting.remaining_quantity);

                // Trade executes at the resting order's price.
                Trade trade;
                trade.trade_id = next_trade_id_++;
                trade.price = level_price;
                trade.quantity = trade_qty;
                trade.buy_order_id = incoming_id;
                trade.sell_order_id = resting.id;
                trade.timestamp_ms = now_ms();
                trades_.push_back(trade);

                fills.push_back(Fill{level_price, trade_qty, resting.id});

                remaining -= trade_qty;
                resting.remaining_quantity -= trade_qty;

                if (resting.remaining_quantity == 0) {
                    order_index_.erase(resting.id);
                    queue.pop_front();
                }
            }

            if (queue.empty()) {
                asks_.erase(level_it);
            }
        }
    } else { // SELL
        // Match against bids while the best bid is at or above our price.
        while (remaining > 0 && !bids_.empty()) {
            auto level_it = bids_.begin(); // highest price = best bid (map uses greater<>)
            const double level_price = level_it->first;
            if (level_price < price) {
                break; // best bid too cheap, no more crosses possible
            }
            std::deque<Order>& queue = level_it->second;

            while (remaining > 0 && !queue.empty()) {
                Order& resting = queue.front();
                const int64_t trade_qty = std::min(remaining, resting.remaining_quantity);

                Trade trade;
                trade.trade_id = next_trade_id_++;
                trade.price = level_price;
                trade.quantity = trade_qty;
                trade.buy_order_id = resting.id;
                trade.sell_order_id = incoming_id;
                trade.timestamp_ms = now_ms();
                trades_.push_back(trade);

                fills.push_back(Fill{level_price, trade_qty, resting.id});

                remaining -= trade_qty;
                resting.remaining_quantity -= trade_qty;

                if (resting.remaining_quantity == 0) {
                    order_index_.erase(resting.id);
                    queue.pop_front();
                }
            }

            if (queue.empty()) {
                bids_.erase(level_it);
            }
        }
    }

    SubmitResult result;
    result.order_id = incoming_id;
    result.filled_quantity = quantity - remaining;
    result.remaining_quantity = remaining;
    result.fills = std::move(fills);

    if (remaining == 0) {
        result.status = OrderStatus::FILLED;
    } else if (remaining < quantity) {
        result.status = OrderStatus::PARTIAL;
        // Rest the remainder on the book.
        Order resting_order;
        resting_order.id = incoming_id;
        resting_order.side = side;
        resting_order.price = price;
        resting_order.quantity = quantity;
        resting_order.remaining_quantity = remaining;
        resting_order.sequence = next_sequence_++;

        if (side == Side::BUY) {
            bids_[price].push_back(resting_order);
        } else {
            asks_[price].push_back(resting_order);
        }
        order_index_[incoming_id] = OrderLocation{side, price};
    } else {
        // Nothing matched at all -- fully rests.
        result.status = OrderStatus::RESTING;
        Order resting_order;
        resting_order.id = incoming_id;
        resting_order.side = side;
        resting_order.price = price;
        resting_order.quantity = quantity;
        resting_order.remaining_quantity = remaining;
        resting_order.sequence = next_sequence_++;

        if (side == Side::BUY) {
            bids_[price].push_back(resting_order);
        } else {
            asks_[price].push_back(resting_order);
        }
        order_index_[incoming_id] = OrderLocation{side, price};
    }

    return result;
}

void OrderBook::cancel_order(int64_t order_id) {
    auto it = order_index_.find(order_id);
    if (it == order_index_.end()) {
        throw OrderNotFoundError(order_id);
    }

    const OrderLocation loc = it->second;

    if (loc.side == Side::BUY) {
        auto level_it = bids_.find(loc.price);
        if (level_it != bids_.end()) {
            auto& queue = level_it->second;
            for (auto qit = queue.begin(); qit != queue.end(); ++qit) {
                if (qit->id == order_id) {
                    queue.erase(qit);
                    break;
                }
            }
            if (queue.empty()) {
                bids_.erase(level_it);
            }
        }
    } else {
        auto level_it = asks_.find(loc.price);
        if (level_it != asks_.end()) {
            auto& queue = level_it->second;
            for (auto qit = queue.begin(); qit != queue.end(); ++qit) {
                if (qit->id == order_id) {
                    queue.erase(qit);
                    break;
                }
            }
            if (queue.empty()) {
                asks_.erase(level_it);
            }
        }
    }

    order_index_.erase(it);
}

BookDepth OrderBook::get_depth() const {
    BookDepth depth;

    for (const auto& [price, queue] : bids_) {
        int64_t total = 0;
        for (const auto& order : queue) {
            total += order.remaining_quantity;
        }
        depth.bids.push_back(DepthLevel{price, total});
    }

    for (const auto& [price, queue] : asks_) {
        int64_t total = 0;
        for (const auto& order : queue) {
            total += order.remaining_quantity;
        }
        depth.asks.push_back(DepthLevel{price, total});
    }

    return depth;
}

std::vector<Trade> OrderBook::get_trades() const {
    // Most recent first.
    std::vector<Trade> result(trades_.rbegin(), trades_.rend());
    return result;
}

} // namespace orderbook
