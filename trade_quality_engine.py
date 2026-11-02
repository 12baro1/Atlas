"""Hard execution-quality gate that validates agreement between Atlas motors.

Scores remain diagnostic only. This gate checks whether the actual trade geometry
and the underlying SMC evidence agree before a signal can be executed.
"""


class TradeQualityEngine:
    """Validate the complete setup rather than trusting a weighted score."""

    def evaluate(
        self,
        entry,
        confirmation,
        mtf,
        trend,
        liquidity_sweep,
        ote,
        market_regime,
        dynamic_tp,
        risk,
        current_price=None,
        candles=None,
        minimum_rr=3.0,
        smt=None,
        unicorn=None,
        cisd=None,
        volume_profile=None,
        institutional=None,
        market_phase=None,
        setup_quality=None,
    ):
        entry = entry if isinstance(entry, dict) else {}
        confirmation = confirmation if isinstance(confirmation, dict) else {}
        mtf = mtf if isinstance(mtf, dict) else {}
        trend = trend if isinstance(trend, dict) else {}
        sweep = liquidity_sweep if isinstance(liquidity_sweep, dict) else {}
        ote = ote if isinstance(ote, dict) else {}
        regime = market_regime if isinstance(market_regime, dict) else {}
        targets = dynamic_tp if isinstance(dynamic_tp, dict) else {}
        risk = risk if isinstance(risk, dict) else {}
        blockers = []
        warnings = []

        direction = str(entry.get("direction", "NONE")).upper()
        if direction not in {"LONG", "SHORT"}:
            blockers.append("Trade direction is missing")
        if not entry.get("valid"):
            blockers.append(entry.get("reason") or "Entry is invalid")
        if not confirmation.get("confirmed"):
            blockers.append(confirmation.get("reason") or "15m confirmation missing")

        expected_mtf = direction
        if not mtf.get("valid") or str(mtf.get("entry", mtf.get("direction", ""))).upper() != expected_mtf:
            blockers.append("Multi-timeframe direction is not aligned")

        trend_direction = str(trend.get("trend", "NEUTRAL")).upper()
        expected_trend = "BULLISH" if direction == "LONG" else "BEARISH"
        if direction in {"LONG", "SHORT"} and trend_direction not in {expected_trend, "NEUTRAL", "RANGE", "NONE"}:
            blockers.append("Trend engine conflicts with the proposed direction")

        sweep_active = bool(sweep.get("is_sweep"))
        buy_side = bool(sweep.get("buy_side"))
        sell_side = bool(sweep.get("sell_side"))
        post = sweep.get("post_structure") if isinstance(sweep.get("post_structure"), dict) else {}
        expected_sweep = sell_side if direction == "LONG" else buy_side
        opposing_sweep = buy_side if direction == "LONG" else sell_side
        if sweep.get("ambiguous_sweep") or sweep.get("sweep_side") == "DUAL":
            blockers.append("Both-side liquidity sweep is ambiguous")
        elif sweep_active and opposing_sweep:
            blockers.append("Liquidity sweep direction conflicts with the trade")
        elif sweep_active and not expected_sweep:
            blockers.append("Sweep side does not support the proposed direction")
        if sweep_active and post.get("confirmed") and post.get("direction") != expected_trend:
            blockers.append("Post-sweep structure confirmation conflicts with the trade")

        regime_name = str(regime.get("regime", "UNKNOWN")).upper()
        bias = str(regime.get("directional_bias", "NEUTRAL")).upper()
        if regime.get("active"):
            if regime_name in {"TRENDING_UP", "TRENDING_DOWN"}:
                regime_bias = "BULLISH" if direction == "LONG" else "BEARISH"
                countertrend_reversal = bool(
                    sweep_active
                    and expected_sweep
                    and post.get("confirmed")
                    and post.get("direction") == expected_trend
                )
                if bias not in {"NEUTRAL", regime_bias} and not countertrend_reversal:
                    blockers.append("Proposed direction opposes the 4H market regime")
                if not (entry.get("ote_confluence") or ote.get("valid")):
                    blockers.append("4H OTE and executable POI do not overlap")
            elif regime_name == "RANGING":
                if not (sweep_active and expected_sweep and post.get("confirmed") and post.get("direction") == expected_trend):
                    blockers.append("Range trade requires an edge liquidity sweep and confirmed reversal")
            elif regime_name == "COMPRESSION":
                breakout_side = str(sweep.get("breakout_side", "")).upper()
                expected_breakout = "BUY_SIDE" if direction == "LONG" else "SELL_SIDE"
                if not sweep.get("is_breakout") or breakout_side != expected_breakout:
                    blockers.append("Compression trade requires a directional range breakout")
            elif regime_name == "TRANSITION":
                if not (sweep_active and expected_sweep and post.get("confirmed") and confirmation.get("confirmed")):
                    blockers.append("Transition regime requires sweep and structure confirmation")
            elif regime_name == "HIGH_VOLATILITY":
                if not risk.get("risk_setup_valid"):
                    blockers.append("High-volatility setup has invalid risk geometry")
        else:
            warnings.append("4H regime unavailable; other structural checks remain mandatory")

        # Optional specialist motors are not mandatory when inactive. When
        # active and sufficiently confident, however, they may not contradict
        # the proposed direction.
        for name, module in (
            ("SMT", smt),
            ("Unicorn", unicorn),
            ("CISD", cisd),
            ("Volume Profile", volume_profile),
            ("Institutional Flow", institutional),
        ):
            if not isinstance(module, dict) or not module.get("active"):
                continue
            try:
                confidence = float(module.get("confidence", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                confidence = 0.0
            module_direction = self._module_direction(module)
            if confidence >= 75 and module_direction in {"LONG", "SHORT"} and module_direction != direction:
                blockers.append(f"{name} high-confidence direction conflicts with the trade")

        phase = str((market_phase or {}).get("phase", "")).strip()
        if phase and phase.lower() == "manipulation":
            if not (sweep_active and expected_sweep and post.get("confirmed")):
                blockers.append("Market phase indicates manipulation without confirmed reversal")

        learning = (setup_quality or {}).get("learning") if isinstance(setup_quality, dict) else None
        if isinstance(learning, dict) and learning.get("matched"):
            try:
                sample_count = int(learning.get("sample_count", 0) or 0)
                expected_r = float(learning.get("expected_r"))
            except (TypeError, ValueError, OverflowError):
                sample_count, expected_r = 0, None
            if sample_count >= 20 and expected_r is not None and expected_r <= 0:
                blockers.append("Learning history shows non-positive expectancy for this setup")

        if not risk.get("risk_setup_valid"):
            blockers.append(risk.get("risk_setup_reason") or "Risk engine rejected the stop")
        if risk.get("stop_adjusted"):
            blockers.append("Stop was changed by risk sizing; original structure must be recalculated")

        tp_values = [targets.get("tp1"), targets.get("tp2"), targets.get("tp3")]
        if any(value is None for value in tp_values):
            blockers.append("Three valid structural targets are not available")
        if targets.get("synthetic_targets"):
            blockers.append("Synthetic RR target is not a market-structure target")
        sources = targets.get("sources") or []
        if sources and any(source != "market_structure" for source in sources):
            blockers.append("One or more targets are not sourced from market structure")

        try:
            entry_price = float(entry.get("entry"))
            stop = float(risk.get("stop_loss", entry.get("stop_loss")))
            current = float(current_price) if current_price is not None else None
            tp_prices = [float(value) for value in tp_values]
            risk_distance = abs(entry_price - stop)
        except (TypeError, ValueError, OverflowError):
            entry_price = stop = current = risk_distance = None
            tp_prices = []

        if direction in {"LONG", "SHORT"} and entry_price is not None and stop is not None:
            if (direction == "LONG" and stop >= entry_price) or (direction == "SHORT" and stop <= entry_price):
                blockers.append("Stop-loss is on the wrong side of entry")

        if len(tp_prices) == 3 and direction in {"LONG", "SHORT"}:
            ordered = all(
                tp_prices[i] < tp_prices[i + 1] for i in range(2)
            ) if direction == "LONG" else all(
                tp_prices[i] > tp_prices[i + 1] for i in range(2)
            )
            correctly_sided = all(
                price > entry_price for price in tp_prices
            ) if direction == "LONG" else all(
                price < entry_price for price in tp_prices
            )
            if not ordered or not correctly_sided:
                blockers.append("TP levels are not correctly ordered for the trade direction")
            if risk_distance and risk_distance > 0:
                final_rr = abs(tp_prices[-1] - entry_price) / risk_distance
                first_rr = abs(tp_prices[0] - entry_price) / risk_distance
                if first_rr < 0.8:
                    blockers.append("TP1 is too close relative to structural risk")
                if final_rr < float(minimum_rr):
                    blockers.append("Final structural target does not meet minimum RR")

        if entry.get("entry_type") not in {"LIMIT", "MARKET"}:
            blockers.append("No executable LIMIT or MARKET order type")

        atr = None
        try:
            if candles and len(candles) >= 15:
                from utils.atr import atr as calculate_atr
                atr = float(calculate_atr(candles, period=14))
        except (TypeError, ValueError, OverflowError):
            atr = None

        if regime_name == "HIGH_VOLATILITY" and atr and atr > 0 and risk_distance is not None:
            if risk_distance < atr * 0.5:
                blockers.append("High-volatility stop is tighter than 0.5 ATR")

        if current is not None and entry_price is not None and atr and atr > 0:
            distance = abs(current - entry_price)
            if entry.get("entry_type") == "LIMIT" and distance > atr * 2.0:
                blockers.append("LIMIT entry is more than 2 ATR away from market")
            if entry.get("entry_type") == "MARKET" and distance > atr * 0.35:
                blockers.append("MARKET entry is already too far from the calculated trigger")
            if len(tp_prices) == 3:
                tp1_reached = current >= tp_prices[0] if direction == "LONG" else current <= tp_prices[0]
                if tp1_reached and entry.get("entry_type") != "LIMIT":
                    blockers.append("TP1 has already been reached; market entry would be chasing")

        # Keep the blocker list stable and free of duplicate messages.
        blockers = list(dict.fromkeys(str(item) for item in blockers if item))
        return {
            "allowed": not blockers,
            "quality_passed": not blockers,
            "direction": direction,
            "regime": regime_name,
            "blockers": blockers,
            "warnings": warnings,
            "reason": "All execution-quality checks passed" if not blockers else "; ".join(blockers),
        }

    @staticmethod
    def _module_direction(module):
        if not isinstance(module, dict):
            return "NONE"
        value = module.get("direction") or module.get("signal") or module.get("trend")
        if not value and isinstance(module.get("best"), dict):
            best = module["best"]
            value = best.get("direction") or best.get("signal") or best.get("trend")
        value = str(value or "NONE").upper()
        if value in {"LONG", "BULLISH"}:
            return "LONG"
        if value in {"SHORT", "BEARISH"}:
            return "SHORT"
        return "NONE"

