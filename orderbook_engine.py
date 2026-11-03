"""Bybit public order-book analysis for Atlas entry validation.

Displayed liquidity is a snapshot, not proof of executed buying/selling.
"""
import math


class OrderBookEngine:
    MAX_LEVELS = 50
    DEPTH_BAND_PCT = 0.50
    MARKET_MAX_SPREAD_PCT = 0.08

    def _analyze_trade_flow(self, trades, now_ms=None, direction="NONE"):
        """Recent executed trades: taker buy/sell notional delta, not a cumulative CVD feed."""
        side = str(direction or "NONE").upper()
        result = {
            "trade_flow_active": False,
            "trade_count": 0,
            "buy_notional": 0.0,
            "sell_notional": 0.0,
            "trade_delta": None,
            "trade_flow_supportive": False,
            "trade_flow_opposing": False,
        }
        if not isinstance(trades, (list, tuple)):
            return result
        buy = sell = 0.0
        count = 0
        newest = None
        for trade in trades[-200:]:
            if not isinstance(trade, dict):
                continue
            try:
                price = float(trade.get("price"))
                amount = float(trade.get("amount"))
                timestamp = trade.get("timestamp")
                if not (math.isfinite(price) and math.isfinite(amount) and price > 0 and amount > 0):
                    continue
                if timestamp is not None and now_ms is not None:
                    age = float(now_ms) - float(timestamp)
                    if not math.isfinite(age) or age < -2000 or age > 30000:
                        continue
                notional = price * amount
                trade_side = str(trade.get("side") or "").lower()
                if trade_side == "buy":
                    buy += notional
                elif trade_side == "sell":
                    sell += notional
                else:
                    continue
                count += 1
                if timestamp is not None:
                    newest = max(newest or float(timestamp), float(timestamp))
            except (TypeError, ValueError, OverflowError):
                continue
        total = buy + sell
        if count == 0 or total <= 0 or not math.isfinite(total):
            return result
        delta = (buy - sell) / total
        result.update({
            "trade_flow_active": True,
            "trade_count": count,
            "buy_notional": round(buy, 2),
            "sell_notional": round(sell, 2),
            "trade_delta": round(delta, 4),
            "trade_flow_supportive": (delta >= 0.12 if side == "LONG" else delta <= -0.12 if side == "SHORT" else False),
            "trade_flow_opposing": (delta <= -0.20 if side == "LONG" else delta >= 0.20 if side == "SHORT" else False),
            "trade_flow_newest_timestamp": newest,
        })
        return result

    def analyze(self, snapshot, direction=None, now_ms=None, trades=None):
        side = str(direction or "NONE").upper()
        flow = self._analyze_trade_flow(trades, now_ms=now_ms, direction=side)
        empty = {
            "active": False, "source": "bybit_orderbook", "direction": side,
            "imbalance": 0.0, "bid_notional": 0.0, "ask_notional": 0.0,
            "spread_pct": None, "best_bid": None, "best_ask": None,
            "supportive": flow["trade_flow_supportive"],
            "opposing": flow["trade_flow_opposing"],
            "market_entry_allowed": not flow["trade_flow_opposing"],
            "limit_entry_candidate": None,
            "reason": "Order book verisi yok; trade-flow snapshot tek başına sınırlı teyit.",
        }
        empty.update(flow)
        if not isinstance(snapshot, dict):
            return empty
        try:
            timestamp = snapshot.get("timestamp")
            if timestamp is not None and now_ms is not None:
                age_ms = float(now_ms) - float(timestamp)
                if not math.isfinite(age_ms) or age_ms < -2000 or age_ms > 15000:
                    empty["reason"] = "Order book verisi eski/geçersiz; teyit kullanılmadı."
                    return empty

            def parse_levels(items, is_bid):
                parsed = []
                for item in (items or [])[:self.MAX_LEVELS]:
                    if not isinstance(item, (list, tuple)) or len(item) < 2:
                        continue
                    price, qty = float(item[0]), float(item[1])
                    if not (math.isfinite(price) and math.isfinite(qty) and price > 0 and qty > 0):
                        continue
                    parsed.append((price, qty))
                parsed.sort(key=lambda level: level[0], reverse=is_bid)
                return parsed

            bids = parse_levels(snapshot.get("bids"), True)
            asks = parse_levels(snapshot.get("asks"), False)
            if not bids or not asks:
                empty["reason"] = "Order book taraflarından biri boş; teyit kullanılmadı."
                return empty

            best_bid, best_ask = bids[0][0], asks[0][0]
            if best_ask <= best_bid:
                empty["reason"] = "Geçersiz/crossed order book; teyit kullanılmadı."
                return empty

            mid = (best_bid + best_ask) / 2.0
            band = self.DEPTH_BAND_PCT / 100.0
            # Yakın seviyeler daha ağır; uzak seviyeler toplamı domine edemez.
            def weighted_notional(levels):
                total = 0.0
                for price, qty in levels:
                    distance = abs(price - mid) / mid
                    if distance > band:
                        continue
                    proximity_weight = max(0.0, 1.0 - (distance / band))
                    total += price * qty * proximity_weight
                return total

            bid_notional = weighted_notional(bids)
            ask_notional = weighted_notional(asks)
            total = bid_notional + ask_notional
            if total <= 0 or not math.isfinite(total):
                empty["reason"] = "Yakın derinlikte geçerli hacim yok; teyit kullanılmadı."
                return empty

            imbalance = (bid_notional - ask_notional) / total
            spread_pct = ((best_ask - best_bid) / mid) * 100.0
            book_supportive = (imbalance >= 0.18 if side == "LONG" else
                               imbalance <= -0.18 if side == "SHORT" else False)
            book_opposing = (imbalance <= -0.30 if side == "LONG" else
                             imbalance >= 0.30 if side == "SHORT" else False)
            # A strong executed-flow imbalance can veto a setup; a displayed
            # book alone cannot claim that trades were actually executed.
            supportive = book_supportive and (flow["trade_flow_supportive"] if flow["trade_flow_active"] else True)
            opposing = book_opposing or flow["trade_flow_opposing"]
            market_allowed = spread_pct <= self.MARKET_MAX_SPREAD_PCT and not opposing

            result = {
                "active": True, "source": "bybit_orderbook", "direction": side,
                "imbalance": round(imbalance, 4),
                "bid_notional": round(bid_notional, 2),
                "ask_notional": round(ask_notional, 2),
                "spread_pct": round(spread_pct, 5),
                "best_bid": best_bid, "best_ask": best_ask,
                "supportive": supportive, "opposing": opposing,
                "book_supportive": book_supportive, "book_opposing": book_opposing,
                "market_entry_allowed": market_allowed,
                "limit_entry_candidate": best_bid if side == "LONG" else best_ask if side == "SHORT" else None,
                "reason": ("Gerçekleşen işlemler ve defter aynı yönü destekliyor" if supportive else
                           "Order book veya gerçekleşen işlemler yönün karşısında" if opposing else
                           "Order book / trade-flow belirgin yön teyidi vermiyor"),
            }
            result.update(flow)
            return result
        except (TypeError, ValueError, IndexError, OverflowError):
            empty["reason"] = "Order book verisi hatalı; teyit kullanılmadı."
            return empty
