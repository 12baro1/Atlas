"""Bybit public order-book analysis for Atlas entry validation.

This module is deliberately conservative: missing/stale book data is neutral,
and displayed liquidity is never treated as guaranteed execution.
"""
import math
import time


class OrderBookEngine:
    def analyze(self, snapshot, direction=None, now_ms=None):
        empty = {
            "active": False, "source": "bybit_orderbook", "direction": direction or "NONE",
            "imbalance": 0.0, "bid_notional": 0.0, "ask_notional": 0.0,
            "spread_pct": None, "best_bid": None, "best_ask": None,
            "supportive": False, "opposing": False, "market_entry_allowed": True,
            "reason": "Order book verisi yok; nötr kabul edildi.",
        }
        if not isinstance(snapshot, dict):
            return empty
        try:
            bids = snapshot.get("bids") or []
            asks = snapshot.get("asks") or []
            timestamp = snapshot.get("timestamp")
            if timestamp is not None and now_ms is not None and abs(float(now_ms) - float(timestamp)) > 15000:
                empty["reason"] = "Order book verisi eski; teyit kullanılmadı."
                return empty
            def levels(items):
                parsed = []
                for item in items[:50]:
                    price, qty = float(item[0]), float(item[1])
                    if math.isfinite(price) and math.isfinite(qty) and price > 0 and qty > 0:
                        parsed.append((price, qty))
                return parsed
            bids, asks = levels(bids), levels(asks)
            if not bids or not asks:
                return empty
            best_bid = max(price for price, _ in bids)
            best_ask = min(price for price, _ in asks)
            if best_ask <= best_bid:
                empty["reason"] = "Geçersiz/crossed order book; teyit kullanılmadı."
                return empty
            bid_notional = sum(price * qty for price, qty in bids)
            ask_notional = sum(price * qty for price, qty in asks)
            total = bid_notional + ask_notional
            imbalance = (bid_notional - ask_notional) / total if total else 0.0
            spread_pct = ((best_ask - best_bid) / ((best_ask + best_bid) / 2.0)) * 100.0
            side = str(direction or "NONE").upper()
            supportive = (imbalance >= 0.18 if side == "LONG" else imbalance <= -0.18 if side == "SHORT" else False)
            opposing = (imbalance <= -0.30 if side == "LONG" else imbalance >= 0.30 if side == "SHORT" else False)
            # A wide spread makes a market entry unsafe; do not fabricate a price.
            market_allowed = spread_pct <= 0.08 and not opposing
            return {
                "active": True, "source": "bybit_orderbook", "direction": side,
                "imbalance": round(imbalance, 4), "bid_notional": round(bid_notional, 2),
                "ask_notional": round(ask_notional, 2), "spread_pct": round(spread_pct, 5),
                "best_bid": best_bid, "best_ask": best_ask, "supportive": supportive,
                "opposing": opposing, "market_entry_allowed": market_allowed,
                "reason": ("Alış tarafı destekli" if supportive and side == "LONG" else
                           "Satış tarafı destekli" if supportive and side == "SHORT" else
                           "Yönün karşısında güçlü emir yoğunluğu" if opposing else
                           "Order book belirgin yön teyidi vermiyor"),
            }
        except (TypeError, ValueError, IndexError, OverflowError):
            return empty
