// pybind11 bindings exposing orderbook::OrderBook to Python as
// `orderbook_cpp.OrderBook`, with the supporting enums/structs mapped to
// plain Python-visible attributes.

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "order_book.hpp"

namespace py = pybind11;
using namespace orderbook;

PYBIND11_MODULE(orderbook_cpp, m) {
    m.doc() = "C++ limit order book matching engine (pybind11 bindings)";

    py::enum_<Side>(m, "Side")
        .value("BUY", Side::BUY)
        .value("SELL", Side::SELL);

    py::enum_<OrderStatus>(m, "OrderStatus")
        .value("FILLED", OrderStatus::FILLED)
        .value("PARTIAL", OrderStatus::PARTIAL)
        .value("RESTING", OrderStatus::RESTING);

    py::class_<Fill>(m, "Fill")
        .def_readonly("price", &Fill::price)
        .def_readonly("quantity", &Fill::quantity)
        .def_readonly("matched_order_id", &Fill::matched_order_id);

    py::class_<SubmitResult>(m, "SubmitResult")
        .def_readonly("order_id", &SubmitResult::order_id)
        .def_readonly("status", &SubmitResult::status)
        .def_readonly("filled_quantity", &SubmitResult::filled_quantity)
        .def_readonly("remaining_quantity", &SubmitResult::remaining_quantity)
        .def_readonly("fills", &SubmitResult::fills);

    py::class_<Trade>(m, "Trade")
        .def_readonly("trade_id", &Trade::trade_id)
        .def_readonly("price", &Trade::price)
        .def_readonly("quantity", &Trade::quantity)
        .def_readonly("buy_order_id", &Trade::buy_order_id)
        .def_readonly("sell_order_id", &Trade::sell_order_id)
        .def_readonly("timestamp_ms", &Trade::timestamp_ms);

    py::class_<DepthLevel>(m, "DepthLevel")
        .def_readonly("price", &DepthLevel::price)
        .def_readonly("quantity", &DepthLevel::quantity);

    py::class_<BookDepth>(m, "BookDepth")
        .def_readonly("bids", &BookDepth::bids)
        .def_readonly("asks", &BookDepth::asks);

    py::register_exception<OrderNotFoundError>(m, "OrderNotFoundError");
    py::register_exception<InvalidOrderError>(m, "InvalidOrderError");

    py::class_<OrderBook>(m, "OrderBook")
        .def(py::init<>())
        .def("submit_order", &OrderBook::submit_order,
             py::arg("side"), py::arg("price"), py::arg("quantity"),
             "Submit a new limit order; returns a SubmitResult.")
        .def("cancel_order", &OrderBook::cancel_order, py::arg("order_id"),
             "Cancel a resting order by id; raises OrderNotFoundError if unknown.")
        .def("get_depth", &OrderBook::get_depth,
             "Return the current aggregated book depth (bids desc, asks asc).")
        .def("get_trades", &OrderBook::get_trades,
             "Return executed trades, most recent first.")
        .def("resting_order_count", &OrderBook::resting_order_count,
             "Number of orders currently resting on the book (diagnostics).");
}
