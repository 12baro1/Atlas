"""
smt_engine.py
Atlas SMT Divergence Engine v1
"""


class SMTDivergenceEngine:
    """Swing pivotlar kullanarak SMT divergence tespiti yapar."""

    SUPPORTED_TIMEFRAMES = ("15m", "1h", "4h", "1d")

    def detect(
        self,
        primary_symbol,
        primary_timeframes,
        smt_universe,
        selected_symbols=None,
        timeframes=None,
        pivot_left=2,
        pivot_right=2,
        max_time_delta_bars=6,
    ):
        """Primary sembol için SMT divergence listesini döndürür."""
        selected = set(selected_symbols or [])
        requested_tfs = timeframes or self.SUPPORTED_TIMEFRAMES
        normalized_tfs = [self._normalize_timeframe(tf) for tf in requested_tfs]

        comparison_symbols = self._resolve_comparison_symbols(
            primary_symbol=primary_symbol,
            smt_universe=smt_universe,
            selected_symbols=selected,
        )

        divergences = []

        for timeframe in normalized_tfs:
            primary_candles = self._get_timeframe_candles(primary_timeframes, timeframe)
            if not primary_candles:
                continue

            primary_pivots = self._confirmed_pivots(primary_candles, pivot_left, pivot_right)
            if len(primary_pivots["highs"]) < 2 and len(primary_pivots["lows"]) < 2:
                continue

            for symbol in comparison_symbols:
                compare_data = smt_universe.get(symbol, {})
                compare_candles = self._get_timeframe_candles(compare_data, timeframe)
                if not compare_candles:
                    continue

                compare_pivots = self._confirmed_pivots(compare_candles, pivot_left, pivot_right)

                bearish = self._detect_bearish(
                    primary_symbol=primary_symbol,
                    compare_symbol=symbol,
                    timeframe=timeframe,
                    primary_highs=primary_pivots["highs"],
                    compare_highs=compare_pivots["highs"],
                    max_time_delta_bars=max_time_delta_bars,
                )
                if bearish is not None:
                    divergences.append(bearish)

                bullish = self._detect_bullish(
                    primary_symbol=primary_symbol,
                    compare_symbol=symbol,
                    timeframe=timeframe,
                    primary_lows=primary_pivots["lows"],
                    compare_lows=compare_pivots["lows"],
                    max_time_delta_bars=max_time_delta_bars,
                )
                if bullish is not None:
                    divergences.append(bullish)

        bullish_divs = [item for item in divergences if item["type"] == "BULLISH"]
        bearish_divs = [item for item in divergences if item["type"] == "BEARISH"]

        best = None
        if divergences:
            best = max(divergences, key=lambda item: item["confidence"])

        return {
            "active": best is not None,
            "direction": best["type"] if best else "NONE",
            "confidence": best["confidence"] if best else 0,
            "best": best,
            "bullish": bullish_divs,
            "bearish": bearish_divs,
            "divergences": divergences,
            "timeframes": normalized_tfs,
            "symbols": comparison_symbols,
            "non_repaint": True,
            "pivot_mode": "confirmed",
        }

    def _resolve_comparison_symbols(self, primary_symbol, smt_universe, selected_symbols):
        """BTC/ETH öncelikli olacak şekilde karşılaştırma sembollerini seçer."""
        symbols = list(smt_universe.keys())

        priority = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
        resolved = []

        for symbol in priority:
            if symbol in symbols and symbol != primary_symbol:
                resolved.append(symbol)

        for symbol in symbols:
            if symbol == primary_symbol or symbol in resolved:
                continue

            if selected_symbols and symbol not in selected_symbols:
                continue

            resolved.append(symbol)

        return resolved

    def _detect_bearish(
        self,
        primary_symbol,
        compare_symbol,
        timeframe,
        primary_highs,
        compare_highs,
        max_time_delta_bars,
    ):
        """Swing high pivotlarıyla bearish SMT divergence tespiti yapar."""
        if len(primary_highs) < 2 or len(compare_highs) < 2:
            return None

        p_prev, p_last = primary_highs[-2], primary_highs[-1]
        c_prev, c_last = compare_highs[-2], compare_highs[-1]

        if not self._aligned(p_last, c_last, max_time_delta_bars):
            return None

        primary_hh = p_last["price"] > p_prev["price"]
        compare_hh = c_last["price"] > c_prev["price"]

        if primary_hh == compare_hh:
            return None

        confidence = self._confidence_score(
            timeframe=timeframe,
            primary_prev=p_prev,
            primary_last=p_last,
            compare_prev=c_prev,
            compare_last=c_last,
            bullish=False,
        )

        return {
            "type": "BEARISH",
            "timeframe": timeframe,
            "primary_symbol": primary_symbol,
            "compare_symbol": compare_symbol,
            "primary": {
                "prev": p_prev,
                "last": p_last,
                "trend": "HH" if primary_hh else "LH",
            },
            "comparison": {
                "prev": c_prev,
                "last": c_last,
                "trend": "HH" if compare_hh else "LH",
            },
            "confidence": confidence,
            "reason": "Swing high mismatch between correlated symbols",
            "non_repaint": True,
        }

    def _detect_bullish(
        self,
        primary_symbol,
        compare_symbol,
        timeframe,
        primary_lows,
        compare_lows,
        max_time_delta_bars,
    ):
        """Swing low pivotlarıyla bullish SMT divergence tespiti yapar."""
        if len(primary_lows) < 2 or len(compare_lows) < 2:
            return None

        p_prev, p_last = primary_lows[-2], primary_lows[-1]
        c_prev, c_last = compare_lows[-2], compare_lows[-1]

        if not self._aligned(p_last, c_last, max_time_delta_bars):
            return None

        primary_ll = p_last["price"] < p_prev["price"]
        compare_ll = c_last["price"] < c_prev["price"]

        if primary_ll == compare_ll:
            return None

        confidence = self._confidence_score(
            timeframe=timeframe,
            primary_prev=p_prev,
            primary_last=p_last,
            compare_prev=c_prev,
            compare_last=c_last,
            bullish=True,
        )

        return {
            "type": "BULLISH",
            "timeframe": timeframe,
            "primary_symbol": primary_symbol,
            "compare_symbol": compare_symbol,
            "primary": {
                "prev": p_prev,
                "last": p_last,
                "trend": "LL" if primary_ll else "HL",
            },
            "comparison": {
                "prev": c_prev,
                "last": c_last,
                "trend": "LL" if compare_ll else "HL",
            },
            "confidence": confidence,
            "reason": "Swing low mismatch between correlated symbols",
            "non_repaint": True,
        }

    def _confirmed_pivots(self, candles, left, right):
        """Sadece doğrulanmış (right bar tamamlanmış) pivotları üretir."""
        highs = []
        lows = []

        start = left
        end = len(candles) - right
        if end <= start:
            return {"highs": highs, "lows": lows}

        for index in range(start, end):
            center = candles[index]
            is_high = True
            is_low = True

            for check in range(index - left, index + right + 1):
                if check == index:
                    continue

                current = candles[check]
                if current.high >= center.high:
                    is_high = False
                if current.low <= center.low:
                    is_low = False

                if not is_high and not is_low:
                    break

            if is_high:
                highs.append(
                    {
                        "index": index,
                        "time": center.time,
                        "price": center.high,
                        "kind": "HIGH",
                    }
                )

            if is_low:
                lows.append(
                    {
                        "index": index,
                        "time": center.time,
                        "price": center.low,
                        "kind": "LOW",
                    }
                )

        return {
            "highs": highs,
            "lows": lows,
        }

    def _get_timeframe_candles(self, source, timeframe):
        """1H/1h gibi farklı gösterimleri normalize ederek veri döndürür."""
        if not source:
            return None

        if timeframe in source:
            return source[timeframe]

        alias = "1H" if timeframe == "1h" else timeframe.upper()
        return source.get(alias)

    def _normalize_timeframe(self, timeframe):
        text = str(timeframe).lower()
        return "1h" if text == "1h" else text

    def _aligned(self, primary_pivot, compare_pivot, max_time_delta_bars):
        """Pivot zamanları birbirine makul yakınsa True döndürür."""
        return abs(primary_pivot["index"] - compare_pivot["index"]) <= max_time_delta_bars

    def _confidence_score(
        self,
        timeframe,
        primary_prev,
        primary_last,
        compare_prev,
        compare_last,
        bullish,
    ):
        """SMT için 0-100 arası güven puanı üretir."""
        timeframe_bonus = {
            "15m": 5,
            "1h": 10,
            "4h": 15,
            "1d": 20,
        }.get(timeframe, 0)

        if bullish:
            primary_delta = abs(primary_last["price"] - primary_prev["price"])
            compare_delta = abs(compare_last["price"] - compare_prev["price"])
        else:
            primary_delta = abs(primary_last["price"] - primary_prev["price"])
            compare_delta = abs(compare_last["price"] - compare_prev["price"])

        max_delta = max(primary_delta, compare_delta, 1e-9)
        divergence_ratio = abs(primary_delta - compare_delta) / max_delta

        recency_penalty = min(abs(primary_last["index"] - compare_last["index"]) * 2, 20)
        confidence = 55 + timeframe_bonus + int(divergence_ratio * 25) - recency_penalty

        return max(0, min(100, confidence))
