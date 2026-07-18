"""
unicorn_engine.py
Atlas Unicorn Engine v1
"""


class UnicornEngine:
    """ICT/SMC kurallarıyla Unicorn setup tespiti yapar."""

    SUPPORTED_TIMEFRAMES = ("15m", "1h", "4h", "1d")

    def detect(self, timeframe_payload):
        """Çoklu zaman diliminde unicorn setup üretir."""
        by_timeframe = {}
        setups = []

        for timeframe in self.SUPPORTED_TIMEFRAMES:
            payload = timeframe_payload.get(timeframe)
            if not payload:
                continue

            tf_result = self._detect_for_timeframe(timeframe, payload)
            by_timeframe[timeframe] = tf_result
            setups.extend(tf_result["setups"])

        valid_setups = [item for item in setups if item["valid"]]
        best = max(valid_setups, key=lambda item: item["confidence"], default=None)

        return {
            "active": best is not None,
            "direction": best["direction"] if best else "NONE",
            "confidence": best["confidence"] if best else 0,
            "best": best,
            "setups": setups,
            "timeframes": by_timeframe,
            "supported_timeframes": list(self.SUPPORTED_TIMEFRAMES),
        }

    def _detect_for_timeframe(self, timeframe, payload):
        """Tek zaman dilimi için bullish/bearish unicorn setup'larını üretir."""
        breakers = payload.get("breaker", [])
        fvgs = payload.get("fvg", [])

        bullish = self._build_direction_setups("BULLISH", timeframe, breakers, fvgs, payload)
        bearish = self._build_direction_setups("BEARISH", timeframe, breakers, fvgs, payload)

        all_setups = bullish + bearish
        best = max(all_setups, key=lambda item: item["confidence"], default=None)

        return {
            "timeframe": timeframe,
            "setups": all_setups,
            "bullish": bullish,
            "bearish": bearish,
            "best": best,
        }

    def _build_direction_setups(self, direction, timeframe, breakers, fvgs, payload):
        """Breaker ve FVG kesişimlerinden yön bazlı unicorn setup listesi üretir."""
        direction_breakers = [item for item in breakers if item.get("type") == direction]
        direction_fvgs = [item for item in fvgs if item.get("type") == direction and not item.get("filled")]

        setups = []

        for breaker in direction_breakers:
            for fvg in direction_fvgs:
                overlap = self._intersection(breaker, fvg)
                if overlap is None:
                    continue

                validation = self._validate_context(direction, payload)
                confidence = self._confidence_score(
                    direction=direction,
                    timeframe=timeframe,
                    breaker=breaker,
                    fvg=fvg,
                    validation=validation,
                    overlap=overlap,
                )
                levels = self._trade_levels(direction, overlap)

                setups.append(
                    {
                        "pattern": "UNICORN",
                        "direction": direction,
                        "timeframe": timeframe,
                        "zone": overlap,
                        "breaker": breaker,
                        "fvg": fvg,
                        "validation": validation,
                        "confidence": confidence,
                        "valid": confidence >= 60,
                        "entry": levels["entry"],
                        "stop_loss": levels["stop_loss"],
                        "tp1": levels["tp1"],
                        "tp2": levels["tp2"],
                        "tp3": levels["tp3"],
                    }
                )

        return setups

    def _intersection(self, breaker, fvg):
        """Breaker block ile FVG bölgesinin kesişimini döndürür."""
        breaker_low = min(breaker["low"], breaker["high"])
        breaker_high = max(breaker["low"], breaker["high"])
        fvg_low = min(fvg["from"], fvg["to"])
        fvg_high = max(fvg["from"], fvg["to"])

        zone_low = max(breaker_low, fvg_low)
        zone_high = min(breaker_high, fvg_high)

        if zone_low >= zone_high:
            return None

        return {
            "low": zone_low,
            "high": zone_high,
            "size": zone_high - zone_low,
        }

    def _validate_context(self, direction, payload):
        """Unicorn setup için gerekli doğrulama sinyallerini toplar."""
        structure = payload.get("structure", [])
        market_phase = payload.get("market_phase", {})
        liquidity_sweep = payload.get("liquidity_sweep", {})
        smt = payload.get("smt", {})
        orderblocks = payload.get("orderblocks", [])
        eqh_eql = payload.get("eqh_eql", {})
        inducement = payload.get("inducement", {})
        ote = payload.get("ote", {})

        has_bos = any(item.get("bos") and item.get("direction") == direction for item in structure)
        has_choch = any(item.get("choch") and item.get("direction") == direction for item in structure)

        phase_name = market_phase.get("phase", "Ranging")
        phase_ok = phase_name in ["Expansion", "Trending", "Reversal", "Accumulation", "Distribution"]

        sweep_ok = False
        if direction == "BULLISH":
            sweep_ok = bool(liquidity_sweep.get("sell_side"))
        else:
            sweep_ok = bool(liquidity_sweep.get("buy_side"))

        smt_ok = smt.get("active") and smt.get("direction") == direction
        orderblock_ok = bool(orderblocks)
        eq_ok = bool(eqh_eql.get("active"))
        inducement_ok = bool(inducement.get("active"))
        ote_ok = bool(ote.get("valid"))

        return {
            "bos": has_bos,
            "choch": has_choch,
            "market_phase": phase_ok,
            "liquidity_sweep": sweep_ok,
            "smt": smt_ok,
            "orderblock": orderblock_ok,
            "eqh_eql": eq_ok,
            "inducement": inducement_ok,
            "ote": ote_ok,
            "phase_name": phase_name,
        }

    def _confidence_score(self, direction, timeframe, breaker, fvg, validation, overlap):
        """Unicorn setup için 0-100 arası güven puanı hesaplar."""
        timeframe_bonus = {
            "15m": 0,
            "1h": 6,
            "4h": 10,
            "1d": 14,
        }.get(timeframe, 0)

        score = 35 + timeframe_bonus
        score += min(15, int(breaker.get("strength", 0) / 8))
        score += min(15, int(fvg.get("strength", 0) / 8))
        score += min(8, int(overlap.get("size", 0) * 10_000))

        if validation["bos"]:
            score += 8
        if validation["choch"]:
            score += 8
        if validation["market_phase"]:
            score += 8
        if validation["liquidity_sweep"]:
            score += 8
        if validation["smt"]:
            score += 8
        if validation["orderblock"]:
            score += 3
        if validation["eqh_eql"]:
            score += 3
        if validation["inducement"]:
            score += 4
        if validation["ote"]:
            score += 5

        if direction == "BULLISH" and validation["phase_name"] == "Distribution":
            score -= 6
        if direction == "BEARISH" and validation["phase_name"] == "Accumulation":
            score -= 6

        return max(0, min(100, score))

    def _trade_levels(self, direction, overlap):
        """Unicorn bölgesine göre otomatik entry/SL/TP seviyeleri üretir."""
        zone_low = overlap["low"]
        zone_high = overlap["high"]
        zone_size = max(overlap["size"], 1e-8)
        entry = (zone_low + zone_high) / 2
        buffer_size = max(zone_size * 0.25, zone_size * 0.05)

        if direction == "BULLISH":
            stop_loss = zone_low - buffer_size
            risk = max(entry - stop_loss, 1e-8)
            tp1 = entry + (risk * 1.5)
            tp2 = entry + (risk * 2.5)
            tp3 = entry + (risk * 4.0)
        else:
            stop_loss = zone_high + buffer_size
            risk = max(stop_loss - entry, 1e-8)
            tp1 = entry - (risk * 1.5)
            tp2 = entry - (risk * 2.5)
            tp3 = entry - (risk * 4.0)

        return {
            "entry": round(entry, 8),
            "stop_loss": round(stop_loss, 8),
            "tp1": round(tp1, 8),
            "tp2": round(tp2, 8),
            "tp3": round(tp3, 8),
        }
