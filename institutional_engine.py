"""
institutional_engine.py
Atlas Institutional Analysis Engine
"""

from __future__ import annotations

from math import fabs
from typing import Any

from core.analysis_utils import clamp, normalize_direction


class InstitutionalAnalysisEngine:
    """VWAP, CVD, regime, flow ve kurumsal filtreleri tek yerde toplar."""

    SUPPORTED_TIMEFRAMES = ("15m", "1h", "4h", "1d")

    def analyze(self, data):
        candles = self._select_candles(data)
        if len(candles) < 10:
            return self._empty()

        close_prices = [self._price(candle, "close") for candle in candles]
        volumes = [max(self._price(candle, "volume") or 0.0, 0.0) for candle in candles]
        highs = [self._price(candle, "high") for candle in candles]
        lows = [self._price(candle, "low") for candle in candles]

        vwap_value = self._vwap(candles)
        anchor_index = self._anchor_index(data, candles)
        anchored_vwap_value = self._vwap(candles[anchor_index:]) if anchor_index < len(candles) else vwap_value

        cvd = self._cumulative_volume_delta(candles)
        volume_delta = self._volume_delta(candles)
        volatility = self._volatility(candles)
        heatmap = self._liquidity_heatmap(candles)
        liquidity_voids = self._liquidity_voids(heatmap)
        stop_hunt = self._stop_hunt(candles, heatmap)
        market_maker = self._market_maker_model(candles, vwap_value, anchored_vwap_value, cvd, stop_hunt)
        regime = self._market_regime(candles, vwap_value, anchored_vwap_value, cvd, volatility)
        open_interest = self._open_interest(data, close_prices)
        funding_rate = self._funding_rate(data, close_prices)
        breadth = self._market_breadth(data, close_prices)
        multi_asset = self._multi_asset_confirmation(data)
        macro_filter = self._macro_filter(data, regime)
        news_filter = self._news_filter(data, regime)
        execution_quality = self._execution_quality(candles, vwap_value, stop_hunt, regime)
        portfolio_risk = self._portfolio_risk(data, volatility, regime, breadth, open_interest)
        adaptive_position_sizing = self._adaptive_position_sizing(execution_quality, portfolio_risk, regime, stop_hunt)
        institutional_flow = self._institutional_flow(cvd, open_interest, funding_rate, breadth, multi_asset, market_maker)
        session_statistics = self._session_statistics(candles, volatility)
        trade_analytics = self._trade_analytics(candles, vwap_value, regime, execution_quality)

        ai_confidence = self._ai_confidence(
            regime=regime,
            market_maker=market_maker,
            stop_hunt=stop_hunt,
            execution_quality=execution_quality,
            institutional_flow=institutional_flow,
            news_filter=news_filter,
            macro_filter=macro_filter,
            multi_asset=multi_asset,
        )

        ai_trade_quality = self._ai_trade_quality(execution_quality, portfolio_risk, adaptive_position_sizing, trade_analytics)
        direction = institutional_flow["direction"]

        return {
            "active": True,
            "direction": direction,
            "confidence": ai_confidence,
            "score": ai_confidence,
            "vwap": vwap_value,
            "anchored_vwap": anchored_vwap_value,
            "cvd": cvd,
            "volume_delta": volume_delta,
            "open_interest": open_interest,
            "funding_rate": funding_rate,
            "market_breadth": breadth,
            "market_maker_model": market_maker,
            "market_regime": regime,
            "liquidity_heatmap": heatmap,
            "liquidity_voids": liquidity_voids,
            "stop_hunt": stop_hunt,
            "execution_quality": execution_quality,
            "portfolio_risk": portfolio_risk,
            "adaptive_position_sizing": adaptive_position_sizing,
            "macro_filter": macro_filter,
            "news_filter": news_filter,
            "multi_asset_confirmation": multi_asset,
            "institutional_flow": institutional_flow,
            "session_statistics": session_statistics,
            "volatility": volatility,
            "trade_analytics": trade_analytics,
            "ai_confidence": ai_confidence,
            "ai_trade_quality": ai_trade_quality,
            "adaptive_signal_weighting": self._adaptive_signal_weighting(ai_confidence, regime, stop_hunt, news_filter, macro_filter),
            "dynamic_engine_weighting": self._dynamic_engine_weighting(regime, ai_confidence, execution_quality, portfolio_risk),
            "best": {
                "direction": direction,
                "confidence": ai_confidence,
                "regime": regime["name"],
                "execution_quality": execution_quality["score"],
            },
        }

    def detect(self, data):
        return self.analyze(data)

    def _select_candles(self, data):
        for timeframe in self.SUPPORTED_TIMEFRAMES:
            candles = data.get(timeframe)
            if candles:
                return candles
        for value in data.values():
            if isinstance(value, list) and value and hasattr(value[0], "high"):
                return value
        return []

    def _price(self, candle, key):
        if isinstance(candle, dict):
            return float(candle[key])
        return float(getattr(candle, key))

    def _vwap(self, candles):
        total_volume = sum(max(self._price(candle, "volume"), 0.0) for candle in candles)
        if total_volume <= 0:
            return None

        weighted_price = sum(
            ((self._price(candle, "high") + self._price(candle, "low") + self._price(candle, "close")) / 3.0)
            * max(self._price(candle, "volume"), 0.0)
            for candle in candles
        )
        return weighted_price / total_volume

    def _anchor_index(self, data, candles):
        anchor_index = data.get("vwap_anchor_index")
        if isinstance(anchor_index, int) and 0 <= anchor_index < len(candles):
            return anchor_index

        window = max(len(candles) // 3, 10)
        return max(len(candles) - window, 0)

    def _cumulative_volume_delta(self, candles):
        deltas = []
        cumulative = 0.0
        for candle in candles:
            direction = 1.0 if self._price(candle, "close") >= self._price(candle, "open") else -1.0
            delta = direction * max(self._price(candle, "volume"), 0.0)
            cumulative += delta
            deltas.append(delta)

        total_volume = max(sum(abs(value) for value in deltas), 1e-9)
        delta_value = deltas[-1] if deltas else 0.0
        return {
            "value": round(cumulative, 8),
            "delta": round(delta_value, 8),
            "delta_pct": round((delta_value / total_volume) * 100, 2),
            "direction": "LONG" if cumulative > 0 else "SHORT" if cumulative < 0 else "NONE",
            "slope": round((deltas[-1] - deltas[0]) if len(deltas) > 1 else delta_value, 8),
        }

    def _volume_delta(self, candles):
        bullish = 0.0
        bearish = 0.0
        for candle in candles:
            volume = max(self._price(candle, "volume"), 0.0)
            if self._price(candle, "close") >= self._price(candle, "open"):
                bullish += volume
            else:
                bearish += volume

        net = bullish - bearish
        total = max(bullish + bearish, 1e-9)
        imbalance = net / total

        return {
            "bullish": round(bullish, 8),
            "bearish": round(bearish, 8),
            "net": round(net, 8),
            "imbalance": round(imbalance, 4),
            "direction": "LONG" if net > 0 else "SHORT" if net < 0 else "NONE",
        }

    def _volatility(self, candles):
        ranges = [max(self._price(candle, "high") - self._price(candle, "low"), 1e-9) for candle in candles[-14:]]
        avg_range = sum(ranges) / len(ranges)
        last_close = max(self._price(candles[-1], "close"), 1e-9)
        atr_pct = (avg_range / last_close) * 100

        if atr_pct >= 2.2:
            state = "HIGH"
        elif atr_pct <= 0.6:
            state = "LOW"
        else:
            state = "NORMAL"

        return {
            "atr": round(avg_range, 8),
            "atr_pct": round(atr_pct, 4),
            "state": state,
        }

    def _liquidity_heatmap(self, candles, bins=18):
        low = min(self._price(candle, "low") for candle in candles)
        high = max(self._price(candle, "high") for candle in candles)
        if high <= low:
            return {"bins": [], "high_nodes": [], "low_nodes": []}

        step = (high - low) / bins
        heat = [0.0 for _ in range(bins)]

        for candle in candles:
            candle_low = self._price(candle, "low")
            candle_high = self._price(candle, "high")
            volume = max(self._price(candle, "volume"), 0.0)
            start = max(0, min(bins - 1, int((candle_low - low) / step)))
            end = max(0, min(bins - 1, int((candle_high - low) / step)))
            span = max(end - start + 1, 1)
            for index in range(start, end + 1):
                heat[index] += volume / span

        ordered = list(enumerate(heat))
        ordered.sort(key=lambda item: item[1], reverse=True)
        high_nodes = [
            {"price": round(low + (index + 0.5) * step, 8), "density": round(density, 8)}
            for index, density in ordered[:3]
        ]
        low_nodes = [
            {"price": round(low + (index + 0.5) * step, 8), "density": round(density, 8)}
            for index, density in sorted(ordered, key=lambda item: item[1])[:3]
        ]

        return {
            "bins": [{"price": round(low + (index + 0.5) * step, 8), "density": round(density, 8)} for index, density in ordered],
            "high_nodes": high_nodes,
            "low_nodes": low_nodes,
        }

    def _liquidity_voids(self, heatmap):
        bins = heatmap.get("bins") or []
        if not bins:
            return []

        densities = [item["density"] for item in bins]
        average = sum(densities) / len(densities)
        threshold = average * 0.45

        voids = []
        for item in bins:
            if item["density"] <= threshold:
                voids.append({"price": item["price"], "density": item["density"]})
        return voids[:6]

    def _stop_hunt(self, candles, heatmap):
        if len(candles) < 4:
            return {"active": False, "direction": "NONE", "confidence": 0}

        last = candles[-1]
        prev = candles[-2]
        prior_window = candles[-8:-1] if len(candles) >= 8 else candles[:-1]
        if not prior_window:
            prior_window = candles[:-1]

        prior_high = max(self._price(candle, "high") for candle in prior_window)
        prior_low = min(self._price(candle, "low") for candle in prior_window)

        swept_high = self._price(last, "high") > prior_high and self._price(last, "close") < prior_high
        swept_low = self._price(last, "low") < prior_low and self._price(last, "close") > prior_low

        direction = "NONE"
        confidence = 0
        if swept_high:
            direction = "SHORT"
            confidence = 70 + self._hunt_bonus(last, heatmap, prior_high)
        elif swept_low:
            direction = "LONG"
            confidence = 70 + self._hunt_bonus(last, heatmap, prior_low)

        return {
            "active": direction != "NONE",
            "direction": direction,
            "confidence": int(clamp(confidence, 0, 100)),
            "swept_high": prior_high if swept_high else None,
            "swept_low": prior_low if swept_low else None,
            "confirmed_by_reclaim": (self._price(last, "close") - self._price(prev, "close")) != 0,
        }

    def _hunt_bonus(self, last, heatmap, level):
        nodes = heatmap.get("high_nodes") or []
        if not nodes:
            return 0
        nearest = min(nodes, key=lambda item: fabs(item["price"] - level), default=None)
        if nearest is None:
            return 0
        proximity = 1.0 - min(fabs(nearest["price"] - level) / max(level, 1e-9), 1.0)
        return int(proximity * 10)

    def _market_maker_model(self, candles, vwap_value, anchored_vwap_value, cvd, stop_hunt):
        current = self._price(candles[-1], "close")
        above_vwap = vwap_value is not None and current > vwap_value
        above_anchor = anchored_vwap_value is not None and current > anchored_vwap_value

        if stop_hunt["active"] and stop_hunt["direction"] == "LONG":
            phase = "ACCUMULATION"
        elif stop_hunt["active"] and stop_hunt["direction"] == "SHORT":
            phase = "DISTRIBUTION"
        elif above_vwap and above_anchor and cvd["direction"] == "LONG":
            phase = "MARKUP"
        elif not above_vwap and not above_anchor and cvd["direction"] == "SHORT":
            phase = "MARKDOWN"
        else:
            phase = "BALANCE"

        direction = "LONG" if phase in ["ACCUMULATION", "MARKUP"] else "SHORT" if phase in ["DISTRIBUTION", "MARKDOWN"] else "NONE"
        confidence = 55
        if phase in ["ACCUMULATION", "DISTRIBUTION"]:
            confidence += 15
        if cvd["direction"] == direction and direction != "NONE":
            confidence += 10

        return {
            "phase": phase,
            "direction": direction,
            "confidence": int(clamp(confidence)),
        }

    def _market_regime(self, candles, vwap_value, anchored_vwap_value, cvd, volatility):
        current = self._price(candles[-1], "close")
        slope = current - self._price(candles[0], "close")
        vwap_bias = 0.0
        if vwap_value:
            vwap_bias += current - vwap_value
        if anchored_vwap_value:
            vwap_bias += current - anchored_vwap_value

        if volatility["state"] == "HIGH" and fabs(slope) > fabs(vwap_bias):
            name = "EXPANSION"
        elif volatility["state"] == "LOW" and fabs(vwap_bias) < self._price(candles[-1], "close") * 0.005:
            name = "RANGING"
        elif fabs(vwap_bias) / max(current, 1e-9) < 0.003:
            name = "MEAN_REVERSION"
        elif cvd["direction"] == "LONG" and current >= (vwap_value or current):
            name = "TRENDING_UP"
        elif cvd["direction"] == "SHORT" and current <= (vwap_value or current):
            name = "TRENDING_DOWN"
        else:
            name = "RANGING"

        confidence = 55
        if name.startswith("TRENDING"):
            confidence += 15
        if name == "EXPANSION":
            confidence += 20
        if name == "RANGING":
            confidence += 5

        return {
            "name": name,
            "confidence": int(clamp(confidence)),
            "volatility": volatility["state"],
            "trend_bias": "LONG" if name in ["TRENDING_UP", "EXPANSION"] else "SHORT" if name in ["TRENDING_DOWN"] else "NONE",
        }

    def _open_interest(self, data, close_prices):
        series = data.get("open_interest") or data.get("openInterest")
        if series is None:
            return {"active": False, "value": None, "trend": "NONE", "delta_pct": 0}

        values = self._series_values(series)
        if not values:
            return {"active": False, "value": None, "trend": "NONE", "delta_pct": 0}

        delta = values[-1] - values[0]
        delta_pct = (delta / max(values[0], 1e-9)) * 100
        trend = "LONG" if delta > 0 and close_prices[-1] >= close_prices[0] else "SHORT" if delta < 0 and close_prices[-1] <= close_prices[0] else "NONE"

        return {"active": True, "value": round(values[-1], 8), "trend": trend, "delta_pct": round(delta_pct, 4)}

    def _funding_rate(self, data, close_prices):
        series = data.get("funding_rate") or data.get("fundingRate")
        if series is None:
            return {"active": False, "value": None, "bias": "NONE", "confidence": 0}

        values = self._series_values(series)
        if not values:
            return {"active": False, "value": None, "bias": "NONE", "confidence": 0}

        value = values[-1]
        if value >= 0.01:
            bias = "SHORT"
        elif value <= -0.01:
            bias = "LONG"
        else:
            bias = "NONE"

        confidence = min(100, int(abs(value) * 1000) + 45)
        return {"active": True, "value": round(value, 8), "bias": bias, "confidence": confidence, "price_alignment": "LONG" if close_prices[-1] >= close_prices[0] else "SHORT"}

    def _market_breadth(self, data, close_prices):
        breadth = data.get("market_breadth") or {}
        advancers = breadth.get("advancers")
        decliners = breadth.get("decliners")

        if advancers is None or decliners is None:
            return {"active": False, "advancers": 0, "decliners": 0, "ratio": 0, "bias": "NONE"}

        ratio = advancers / max(decliners, 1)
        bias = "LONG" if ratio >= 1.15 and close_prices[-1] >= close_prices[0] else "SHORT" if ratio <= 0.87 else "NONE"

        return {"active": True, "advancers": advancers, "decliners": decliners, "ratio": round(ratio, 4), "bias": bias}

    def _multi_asset_confirmation(self, data):
        peers = data.get("peer_assets") or data.get("related_assets") or {}
        if not peers:
            return {"active": False, "direction": "NONE", "confidence": 0, "aligned": 0, "total": 0}

        aligned = 0
        total = 0
        for _, payload in peers.items():
            candles = payload if isinstance(payload, list) else payload.get("candles") or []
            if len(candles) < 3:
                continue
            total += 1
            first = self._price(candles[0], "close")
            last = self._price(candles[-1], "close")
            if last >= first:
                aligned += 1

        if total == 0:
            return {"active": False, "direction": "NONE", "confidence": 0, "aligned": 0, "total": 0}

        direction = "LONG" if aligned >= (total / 2) else "SHORT"
        confidence = int((aligned / total) * 100)
        return {"active": True, "direction": direction, "confidence": confidence, "aligned": aligned, "total": total}

    def _macro_filter(self, data, regime):
        macro = data.get("macro") or {}
        if not macro:
            return {"active": False, "bias": "NONE", "confidence": 0}

        bias = normalize_direction(macro.get("bias") or macro.get("direction"), default="NONE")
        confidence = int(clamp(macro.get("confidence", 50)))
        if regime["name"] == "EXPANSION" and bias == "LONG":
            confidence += 10
        elif regime["name"] == "EXPANSION" and bias == "SHORT":
            confidence += 10

        return {"active": True, "bias": bias, "confidence": int(clamp(confidence))}

    def _news_filter(self, data, regime):
        news = data.get("news") or {}
        if not news:
            return {"active": False, "bias": "NONE", "confidence": 0}

        severity = int(news.get("severity", 0))
        bias = normalize_direction(news.get("bias") or news.get("direction"), default="NONE")
        confidence = 100 - min(100, severity * 12)
        if regime["name"] == "EXPANSION" and severity >= 3:
            confidence -= 10

        return {"active": True, "bias": bias, "confidence": int(clamp(confidence))}

    def _execution_quality(self, candles, vwap_value, stop_hunt, regime):
        last = candles[-1]
        candle_range = max(self._price(last, "high") - self._price(last, "low"), 1e-9)
        body = fabs(self._price(last, "close") - self._price(last, "open"))
        body_ratio = body / candle_range
        distance = fabs(self._price(last, "close") - (vwap_value or self._price(last, "close"))) / max(self._price(last, "close"), 1e-9)

        score = 55 + int(body_ratio * 25)
        score -= int(distance * 1000)
        if stop_hunt["active"]:
            score += 8
        if regime["name"] == "EXPANSION":
            score += 8
        elif regime["name"] == "RANGING":
            score -= 6

        score = int(clamp(score))
        if score >= 80:
            grade = "A"
        elif score >= 60:
            grade = "B"
        elif score >= 40:
            grade = "C"
        else:
            grade = "D"

        return {"score": score, "grade": grade, "slippage_proxy": round(distance, 6), "body_ratio": round(body_ratio, 4)}

    def _portfolio_risk(self, data, volatility, regime, breadth, open_interest):
        positions = data.get("positions") or []
        correlation_risk = data.get("correlation_risk") or 0.0
        exposure = 0.0
        for position in positions:
            exposure += abs(position.get("size", 0.0)) * abs(position.get("leverage", 1.0))

        exposure_score = int(clamp(exposure * 10, 0, 100))
        risk_score = 100 - exposure_score
        if volatility["state"] == "HIGH":
            risk_score -= 10
        if regime["name"] == "RANGING":
            risk_score -= 5
        if breadth.get("bias") in ["LONG", "SHORT"] and breadth.get("bias") == open_interest.get("trend"):
            risk_score += 5

        risk_score -= int(correlation_risk * 20)
        risk_score = int(clamp(risk_score))

        return {"exposure_score": exposure_score, "correlation_risk": round(correlation_risk, 4), "score": risk_score, "allowed": risk_score >= 45}

    def _adaptive_position_sizing(self, execution_quality, portfolio_risk, regime, stop_hunt):
        factor = 1.0
        factor += (execution_quality["score"] - 50) / 250
        factor += (portfolio_risk["score"] - 50) / 400
        if regime["name"] in ["EXPANSION", "TRENDING_UP", "TRENDING_DOWN"]:
            factor += 0.05
        if stop_hunt["active"]:
            factor += 0.03
        factor = clamp(factor, 0.7, 1.3)
        return {"factor": round(factor, 4), "size_multiplier": round(factor, 4)}

    def _institutional_flow(self, cvd, open_interest, funding_rate, breadth, multi_asset, market_maker):
        score = 50
        if cvd["direction"] == "LONG":
            score += 12
        elif cvd["direction"] == "SHORT":
            score += 12

        if open_interest.get("trend") in ["LONG", "SHORT"]:
            score += 8
        if funding_rate.get("bias") in ["LONG", "SHORT"]:
            score += 6
        if breadth.get("bias") in ["LONG", "SHORT"]:
            score += 6
        if multi_asset.get("active"):
            score += min(10, int(multi_asset.get("confidence", 0) / 10))
        if market_maker.get("direction") in ["LONG", "SHORT"]:
            score += 8

        direction_votes = [cvd["direction"], open_interest.get("trend"), funding_rate.get("bias"), breadth.get("bias"), market_maker.get("direction")]
        long_votes = sum(1 for vote in direction_votes if vote == "LONG")
        short_votes = sum(1 for vote in direction_votes if vote == "SHORT")
        direction = "LONG" if long_votes > short_votes else "SHORT" if short_votes > long_votes else "NONE"

        return {"direction": direction, "confidence": int(clamp(score)), "long_votes": long_votes, "short_votes": short_votes}

    def _session_statistics(self, candles, volatility):
        hour = self._session_hour(candles[-1])
        if 7 <= hour < 13:
            session = "LONDON"
        elif 13 <= hour < 21:
            session = "NEW_YORK"
        elif 0 <= hour < 7:
            session = "ASIA"
        else:
            session = "OTHER"

        return {"session": session, "hour": hour, "volatility": volatility["state"]}

    def _trade_analytics(self, candles, vwap_value, regime, execution_quality):
        current = self._price(candles[-1], "close")
        if vwap_value is None:
            distance_pct = 0.0
        else:
            distance_pct = fabs(current - vwap_value) / max(current, 1e-9) * 100

        momentum = fabs(current - self._price(candles[0], "close")) / max(self._price(candles[0], "close"), 1e-9) * 100
        setup_quality = clamp(50 + momentum - distance_pct + execution_quality["score"] / 3)

        return {"setup_quality": int(setup_quality), "momentum_pct": round(momentum, 4), "distance_from_vwap_pct": round(distance_pct, 4), "regime": regime["name"]}

    def _ai_confidence(self, regime, market_maker, stop_hunt, execution_quality, institutional_flow, news_filter, macro_filter, multi_asset):
        score = 40
        score += min(20, market_maker["confidence"] // 4)
        score += min(15, execution_quality["score"] // 8)
        score += min(10, institutional_flow["confidence"] // 10)
        if stop_hunt["active"]:
            score += 6
        if regime["name"] == "EXPANSION":
            score += 10
        elif regime["name"] == "RANGING":
            score -= 5
        if news_filter.get("active") and news_filter.get("confidence", 100) < 50:
            score -= 8
        if macro_filter.get("active") and macro_filter.get("confidence", 100) < 50:
            score -= 6
        if multi_asset.get("active"):
            score += min(8, multi_asset.get("confidence", 0) // 12)
        return int(clamp(score))

    def _ai_trade_quality(self, execution_quality, portfolio_risk, adaptive_position_sizing, trade_analytics):
        score = (execution_quality["score"] * 0.4) + (portfolio_risk["score"] * 0.3) + (trade_analytics["setup_quality"] * 0.2) + (adaptive_position_sizing["factor"] * 10)
        return int(clamp(score))

    def _adaptive_signal_weighting(self, ai_confidence, regime, stop_hunt, news_filter, macro_filter):
        weight = ai_confidence / 100
        if regime["name"] == "EXPANSION":
            weight += 0.1
        if stop_hunt["active"]:
            weight += 0.05
        if news_filter.get("active") and news_filter.get("confidence", 100) < 50:
            weight -= 0.12
        if macro_filter.get("active") and macro_filter.get("confidence", 100) < 50:
            weight -= 0.08
        return round(clamp(weight, 0.0, 1.5), 4)

    def _dynamic_engine_weighting(self, regime, ai_confidence, execution_quality, portfolio_risk):
        base = {
            "signal": 0.30,
            "confluence": 0.30,
            "risk": 0.20,
            "institutional": 0.20,
        }
        regime_bonus = 0.05 if regime["name"] == "EXPANSION" else -0.03 if regime["name"] == "RANGING" else 0.0
        confidence_bonus = (ai_confidence - 50) / 1000
        execution_bonus = (execution_quality["score"] - 50) / 1000
        risk_bonus = (portfolio_risk["score"] - 50) / 1000

        base["institutional"] = round(clamp(base["institutional"] + regime_bonus + confidence_bonus, 0.05, 0.40), 4)
        base["risk"] = round(clamp(base["risk"] + risk_bonus, 0.10, 0.35), 4)
        base["signal"] = round(clamp(base["signal"] + execution_bonus, 0.15, 0.40), 4)
        base["confluence"] = round(clamp(1.0 - (base["signal"] + base["risk"] + base["institutional"]), 0.10, 0.40), 4)
        return base

    def _series_values(self, series):
        if isinstance(series, (int, float)):
            return [float(series)]
        if isinstance(series, dict):
            values = series.get("values") or series.get("series") or series.get("data")
            if isinstance(values, list):
                return [float(item) for item in values if isinstance(item, (int, float))]
            if isinstance(series.get("value"), (int, float)):
                return [float(series["value"])]
            return []
        if isinstance(series, list):
            values = []
            for item in series:
                if isinstance(item, (int, float)):
                    values.append(float(item))
                elif isinstance(item, dict):
                    if isinstance(item.get("value"), (int, float)):
                        values.append(float(item["value"]))
                    elif isinstance(item.get("close"), (int, float)):
                        values.append(float(item["close"]))
            return values
        return []

    def _session_hour(self, candle):
        timestamp = self._price(candle, "time")
        if timestamp <= 0:
            return 0
        return int((timestamp // 3_600_000) % 24)

    def _empty(self):
        return {
            "active": False,
            "direction": "NONE",
            "confidence": 0,
            "score": 0,
            "vwap": None,
            "anchored_vwap": None,
            "cvd": {"value": 0, "delta": 0, "delta_pct": 0, "direction": "NONE", "slope": 0},
            "volume_delta": {"bullish": 0, "bearish": 0, "net": 0, "imbalance": 0, "direction": "NONE"},
            "open_interest": {"active": False, "value": None, "trend": "NONE", "delta_pct": 0},
            "funding_rate": {"active": False, "value": None, "bias": "NONE", "confidence": 0},
            "market_breadth": {"active": False, "advancers": 0, "decliners": 0, "ratio": 0, "bias": "NONE"},
            "market_maker_model": {"phase": "BALANCE", "direction": "NONE", "confidence": 0},
            "market_regime": {"name": "UNKNOWN", "confidence": 0, "volatility": "NORMAL", "trend_bias": "NONE"},
            "liquidity_heatmap": {"bins": [], "high_nodes": [], "low_nodes": []},
            "liquidity_voids": [],
            "stop_hunt": {"active": False, "direction": "NONE", "confidence": 0},
            "execution_quality": {"score": 0, "grade": "D", "slippage_proxy": 0, "body_ratio": 0},
            "portfolio_risk": {"exposure_score": 0, "correlation_risk": 0, "score": 100, "allowed": True},
            "adaptive_position_sizing": {"factor": 1.0, "size_multiplier": 1.0},
            "macro_filter": {"active": False, "bias": "NONE", "confidence": 0},
            "news_filter": {"active": False, "bias": "NONE", "confidence": 0},
            "multi_asset_confirmation": {"active": False, "direction": "NONE", "confidence": 0, "aligned": 0, "total": 0},
            "institutional_flow": {"direction": "NONE", "confidence": 0, "long_votes": 0, "short_votes": 0},
            "session_statistics": {"session": "OTHER", "hour": 0, "volatility": "NORMAL"},
            "volatility": {"atr": 0, "atr_pct": 0, "state": "NORMAL"},
            "trade_analytics": {"setup_quality": 0, "momentum_pct": 0, "distance_from_vwap_pct": 0, "regime": "UNKNOWN"},
            "ai_confidence": 0,
            "ai_trade_quality": 0,
            "adaptive_signal_weighting": 0.0,
            "dynamic_engine_weighting": {"signal": 0.3, "confluence": 0.3, "risk": 0.2, "institutional": 0.2},
            "best": None,
        }
