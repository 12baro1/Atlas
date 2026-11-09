"""Hard execution-quality gate that validates agreement between Atlas motors.

Scores remain diagnostic only. This gate checks whether the actual trade geometry
and the underlying SMC evidence agree before a signal can be executed.
"""

from config import Config


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
            warnings.append(confirmation.get("reason") or "15m evidence unavailable; POI geometry remains primary")
        if confirmation.get("15m_conflict"):
            warnings.append("15m structure opposes the primary setup; retain as entry-placement evidence")

        expected_trend = "BULLISH" if direction == "LONG" else "BEARISH"
        sweep_active = bool(sweep.get("is_sweep"))
        buy_side = bool(sweep.get("buy_side"))
        sell_side = bool(sweep.get("sell_side"))
        post = sweep.get("post_structure") if isinstance(sweep.get("post_structure"), dict) else {}
        expected_sweep = sell_side if direction == "LONG" else buy_side
        opposing_sweep = buy_side if direction == "LONG" else sell_side

        expected_mtf = direction
        mtf_direction = str(mtf.get("entry", mtf.get("direction", ""))).upper()
        confirmed_countertrend_reversal = bool(
            entry.get("direction_source") == "CONFIRMED_SWEEP_REVERSAL"
            and mtf.get("valid")
            and sweep_active
            and expected_sweep
            and post.get("confirmed")
            and str(post.get("direction", "")).upper() == expected_trend
        )
        if not mtf.get("valid") or (
            mtf_direction != expected_mtf and not confirmed_countertrend_reversal
        ):
            blockers.append("Multi-timeframe direction is not aligned")

        trend_direction = str(trend.get("trend", "NEUTRAL")).upper()
        if direction in {"LONG", "SHORT"} and trend_direction not in {expected_trend, "NEUTRAL", "RANGE", "NONE"}:
            warnings.append("Trend conflict: entry optimizer must demand a deeper POI price")
        if sweep.get("ambiguous_sweep") or sweep.get("sweep_side") == "DUAL":
            warnings.append("Liquidity sweep is ambiguous; sweep evidence has reduced directional value")
        elif sweep_active and (opposing_sweep or not expected_sweep):
            warnings.append("Sweep evidence opposes the setup; use it to refine the POI entry")
        if sweep_active and post.get("confirmed") and post.get("direction") != expected_trend:
            warnings.append("Post-sweep structure conflicts with the setup")

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
                    warnings.append("Market regime opposes the primary MTF setup; POI entry must reflect this pressure")
                if not (entry.get("ote_confluence") or ote.get("valid")):
                    warnings.append("OTE confluence is absent; selected valid POI remains the entry anchor")
            elif regime_name == "RANGING":
                warnings.append("Ranging regime: sweep evidence informs entry placement, not a veto")
            elif regime_name == "COMPRESSION":
                breakout_side = str(sweep.get("breakout_side", "")).upper()
                expected_breakout = "BUY_SIDE" if direction == "LONG" else "SELL_SIDE"
                if not sweep.get("is_breakout") or breakout_side != expected_breakout:
                    warnings.append("Compression without aligned breakout; use a conservative POI LIMIT")
            elif regime_name == "TRANSITION":
                # A transition can be either a confirmed reversal or a
                # still-valid pullback continuation. Do not force a fresh
                # liquidity sweep on the continuation path: require aligned
                # MTF + trend, a real POI LIMIT and closed-15m confirmation.
                transition_reversal = bool(
                    sweep_active
                    and expected_sweep
                    and post.get("confirmed")
                    and post.get("direction") == expected_trend
                    and confirmation.get("confirmed")
                )
                transition_continuation = bool(
                    str(entry.get("entry_type") or "").upper() == "LIMIT"
                    and str(mtf.get("entry", mtf.get("direction", ""))).upper() == direction
                    and trend_direction == expected_trend
                    and entry.get("poi_source") in {"FVG", "ORDER_BLOCK"}
                    and isinstance(entry.get("poi_zone"), dict)
                    and confirmation.get("confirmed")
                )
                if not (transition_reversal or transition_continuation):
                    warnings.append("Transition regime lacks a clear reversal/continuation signature")
            elif regime_name == "HIGH_VOLATILITY":
                if not risk.get("risk_setup_valid"):
                    blockers.append("High-volatility setup has invalid risk geometry")
        else:
            warnings.append("4H regime unavailable; other structural checks remain mandatory")

        # Specialist motors are confluence evidence, not universal vetoes.
        # Their aggregate direction can come from a different timeframe/setup
        # than the proposed entry. Keep high-confidence disagreement visible,
        # but let execution-critical structure, entry, sweep, regime, risk and
        # target checks decide whether the trade is executable.
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
                warnings.append(f"{name} high-confidence direction conflicts with the trade")

        phase = str((market_phase or {}).get("phase", "")).strip()
        if phase and phase.lower() == "manipulation":
            if not (sweep_active and expected_sweep and post.get("confirmed")):
                if confirmation.get("confirmed") and isinstance(entry.get("poi_zone"), dict):
                    warnings.append("Manipulation phase: entry requires the optimized POI pullback and closed-15m confirmation")
                else:
                    warnings.append("Manipulation phase without confirmed reversal; favor a deeper POI entry")

        learning = (setup_quality or {}).get("learning") if isinstance(setup_quality, dict) else None
        if isinstance(learning, dict) and learning.get("matched"):
            try:
                sample_count = int(learning.get("sample_count", 0) or 0)
                expected_r = float(learning.get("expected_r"))
            except (TypeError, ValueError, OverflowError):
                sample_count, expected_r = 0, None
            if sample_count >= 20 and expected_r is not None and expected_r <= 0:
                warnings.append("Learning history is negative: require a more favorable optimized entry")

        if not risk.get("risk_setup_valid"):
            blockers.append(risk.get("risk_setup_reason") or "Risk engine rejected the stop")
        if risk.get("stop_adjusted"):
            blockers.append("Stop was changed by risk sizing; original structure must be recalculated")
        net_rr_value = risk.get("weighted_net_rr", risk.get("net_rr"))
        if net_rr_value is not None:
            try:
                net_rr_value = float(net_rr_value)
            except (TypeError, ValueError, OverflowError):
                net_rr_value = None
            minimum_net_rr = float(getattr(Config, "MINIMUM_NET_RR", 1.5))
            if net_rr_value is None:
                blockers.append("Cost-adjusted net RR is unavailable")
            elif net_rr_value < minimum_net_rr:
                blockers.append(
                    f"Cost-adjusted net RR {net_rr_value:.2f}R is below minimum {minimum_net_rr:.2f}R"
                )

        tp_values = [targets.get("tp1"), targets.get("tp2"), targets.get("tp3")]
        available_tp_values = [value for value in tp_values if value is not None]
        if not available_tp_values:
            blockers.append("At least one valid structural target is required")
        if targets.get("synthetic_targets"):
            blockers.append("Synthetic RR target is not a market-structure target")
        sources = targets.get("sources") or []
        if sources and any(source != "market_structure" for source in sources):
            blockers.append("One or more targets are not sourced from market structure")

        try:
            entry_price = float(entry.get("entry"))
            stop = float(risk.get("stop_loss", entry.get("stop_loss")))
            current = float(current_price) if current_price is not None else None
            tp_prices = [float(value) for value in available_tp_values]
            risk_distance = abs(entry_price - stop)
        except (TypeError, ValueError, OverflowError):
            entry_price = stop = current = risk_distance = None
            tp_prices = []

        if direction in {"LONG", "SHORT"} and entry_price is not None and stop is not None:
            if (direction == "LONG" and stop >= entry_price) or (direction == "SHORT" and stop <= entry_price):
                blockers.append("Stop-loss is on the wrong side of entry")
            risk_entry = risk.get("entry")
            try:
                if risk_entry is not None and abs(float(risk_entry) - entry_price) > max(abs(entry_price) * 1e-8, 1e-12):
                    blockers.append("Risk engine entry differs from the selected setup entry")
            except (TypeError, ValueError, OverflowError):
                blockers.append("Risk engine entry is invalid")

        if tp_prices and direction in {"LONG", "SHORT"}:
            ordered = all(
                tp_prices[i] < tp_prices[i + 1] for i in range(len(tp_prices) - 1)
            ) if direction == "LONG" else all(
                tp_prices[i] > tp_prices[i + 1] for i in range(len(tp_prices) - 1)
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
                if first_rr < float(getattr(Config, "MIN_TP1_RR", 0.80)):
                    blockers.append("TP1 is too close relative to structural risk")
                if final_rr < float(minimum_rr):
                    blockers.append("Final structural target does not meet minimum RR")

                target_atr = 0.0
                try:
                    if candles and len(candles) >= 15:
                        from utils.atr import atr as calculate_atr
                        target_atr = max(0.0, float(calculate_atr(candles, period=14)))
                except (TypeError, ValueError, OverflowError):
                    target_atr = 0.0
                minimum_target_gap = max(
                    risk_distance * max(0.0, float(getattr(Config, "MIN_TP_TARGET_SEPARATION_R", 0.35))),
                    target_atr * max(0.0, float(getattr(Config, "MIN_TP_TARGET_SEPARATION_ATR", 0.20))),
                    entry_price * max(0.0, float(getattr(Config, "MIN_TP_TARGET_SEPARATION_PERCENT", 0.0005))),
                )
                if any(
                    abs(tp_prices[index + 1] - tp_prices[index]) < minimum_target_gap
                    for index in range(len(tp_prices) - 1)
                ):
                    blockers.append("Adjacent TP levels belong to the same liquidity cluster")

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

        if current is not None and entry_price is not None:
            distance = abs(current - entry_price)
            distance_pct = distance / max(abs(current), 1e-12)
            entry_type = str(entry.get("entry_type") or "").upper()
            if entry_type == "LIMIT":
                max_limit_atr = max(0.0, float(getattr(Config, "MAX_LIMIT_ENTRY_DISTANCE_ATR", 3.0)))
                max_limit_pct = max(0.0, float(getattr(Config, "MAX_LIMIT_ENTRY_DISTANCE_PERCENT", 0.05)))
                too_far_by_atr = bool(atr and atr > 0 and distance > atr * max_limit_atr)
                too_far_by_percent = distance_pct > max_limit_pct
                if too_far_by_atr or too_far_by_percent:
                    warnings.append(
                        f"LIMIT entry is far ({max_limit_atr:g} ATR / {max_limit_pct * 100:g}% reference); "
                        "keep it pending and expose its distance instead of rejecting the structural setup"
                    )
            if entry_type == "MARKET":
                max_market_atr = max(0.0, float(getattr(Config, "MAX_MARKET_ENTRY_DISTANCE_ATR", 0.35)))
                max_market_pct = max(0.0, float(getattr(Config, "MAX_MARKET_ENTRY_DISTANCE_PERCENT", 0.003)))
                too_far_by_atr = bool(atr and atr > 0 and distance > atr * max_market_atr)
                too_far_by_percent = distance_pct > max_market_pct
                if too_far_by_atr or too_far_by_percent:
                    blockers.append("MARKET entry is already too far from the calculated trigger")
                if not atr or atr <= 0:
                    blockers.append("MARKET entry distance cannot be validated without ATR")
            if tp_prices:
                tp1_reached = current >= tp_prices[0] if direction == "LONG" else current <= tp_prices[0]
                if tp1_reached:
                    if entry_type == "LIMIT":
                        blockers.append("TP1 has already been reached before the pending LIMIT entry; setup is stale")
                    else:
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

