"""
risk_engine.py
Atlas Risk Engine v4
"""

import math

from core.analysis_utils import clamp
from rr_engine import RREngine
from utils.atr import atr as calculate_atr
from config import Config

class RiskEngine:

    def __init__(self):
        self.rr_engine = RREngine()

    def calculate(
        self,
        entry,
        stop_loss,
        dynamic_tp=None,
        volume_profile=None,
        institutional=None,
        candles=None,
        atr_value=None,
        tick_size=None,
        spread=None,
        slippage=None,
        auto_expand_stop=None,
    ):

        if entry is None or stop_loss is None:
            return None

        side = "LONG" if entry > stop_loss else "SHORT"
        if entry == stop_loss:
            return self._invalid_risk_setup(entry, stop_loss, side=side, reason="Stop Loss invalid")

        atr_period = int(getattr(Config, "ATR_PERIOD", 14))
        min_stop_atr_multiplier = float(getattr(Config, "MIN_STOP_ATR_MULTIPLIER", 0.25))
        min_tick_fallback = float(getattr(Config, "MIN_TICK_DISTANCE_FALLBACK", 0.01))
        spread_rate = float(getattr(Config, "STOP_SPREAD_BUFFER_RATE", 0.0002))
        slippage_rate = float(getattr(Config, "STOP_SLIPPAGE_BUFFER_RATE", 0.0003))
        max_position_size_limit = float(getattr(Config, "MAX_POSITION_SIZE", 1000.0))
        should_auto_expand = bool(getattr(Config, "AUTO_EXPAND_TIGHT_STOPS", True) if auto_expand_stop is None else auto_expand_stop)

        inferred_tick_size = self._infer_tick_size(
            entry,
            stop_loss,
            (dynamic_tp or {}).get("tp1") if isinstance(dynamic_tp, dict) else None,
            (dynamic_tp or {}).get("tp2") if isinstance(dynamic_tp, dict) else None,
            (dynamic_tp or {}).get("tp3") if isinstance(dynamic_tp, dict) else None,
        )
        resolved_tick_size = self._resolve_tick_size(tick_size, inferred_tick_size, min_tick_fallback)

        atr_snapshot = self._resolve_atr(atr_value=atr_value, candles=candles, atr_period=atr_period)
        minimum_tick_distance = max(resolved_tick_size, min_tick_fallback)
        atr_floor_distance = max(atr_snapshot * min_stop_atr_multiplier, minimum_tick_distance)
        spread_buffer = self._resolve_buffer(spread, entry, spread_rate, minimum_tick_distance)
        slippage_buffer = self._resolve_buffer(slippage, entry, slippage_rate, minimum_tick_distance)
        minimum_stop_distance = atr_floor_distance + spread_buffer + slippage_buffer

        requested_risk = abs(entry - stop_loss)
        stop_too_tight = requested_risk < minimum_stop_distance
        adjusted_stop_loss = stop_loss
        stop_adjusted = False

        if stop_too_tight:
            if should_auto_expand:
                adjusted_stop_loss = self._expand_stop(entry, side, minimum_stop_distance, resolved_tick_size)
                stop_adjusted = True
            else:
                return self._invalid_risk_setup(
                    entry,
                    stop_loss,
                    side=side,
                    reason="Invalid Risk Setup",
                    atr=atr_snapshot,
                    minimum_stop_distance=minimum_stop_distance,
                    tick_size=resolved_tick_size,
                    spread_buffer=spread_buffer,
                    slippage_buffer=slippage_buffer,
                    requested_risk=requested_risk,
                    stop_adjusted=False,
                )

        risk = abs(entry - adjusted_stop_loss)

        if risk <= 0:
            return self._invalid_risk_setup(entry, adjusted_stop_loss, side=side, reason="Stop Loss invalid")

        vp_factor = self._volume_profile_position_factor(volume_profile, side=side)
        institutional_factor = self._institutional_position_factor(institutional, side=side)

        account_balance = float(getattr(Config, "INITIAL_BALANCE", 1000.0))
        base_risk_percent = float(getattr(Config, "RISK_PERCENT", 1.0))
        round_trip_cost_rate = float(getattr(Config, "ROUND_TRIP_COST_RATE", 0.0012))
        minimum_rr = float(getattr(Config, "MINIMUM_RR", 2.0))

        tp1 = None
        tp2 = None
        tp3 = None
        rr = None
        net_rr = None
        rr_breakdown = None
        rr_selection_rule = "max_rr"

        if dynamic_tp is not None:

            tp1 = dynamic_tp.get("tp1")
            tp2 = dynamic_tp.get("tp2")
            tp3 = dynamic_tp.get("tp3")

            rr_breakdown = self.rr_engine.calculate_breakdown(
                entry=entry,
                stop_loss=adjusted_stop_loss,
                tp1=tp1,
                tp2=tp2,
                tp3=tp3,
                selection_rule=rr_selection_rule,
            )

            if rr_breakdown is not None:
                rr = rr_breakdown["selected_rr"]
                selected_tp = rr_breakdown["selected_tp"]
                selected_tp_value = dynamic_tp.get(selected_tp) if selected_tp else None

                if selected_tp_value is not None:
                    gross_reward = abs(selected_tp_value - entry)
                    transaction_cost = entry * round_trip_cost_rate
                    net_reward = max(0.0, gross_reward - transaction_cost)
                    net_rr = round(net_reward / risk, 2)

        risk_reduction_factor = 1.0
        if net_rr is not None and minimum_rr > 0 and net_rr < minimum_rr:
            risk_reduction_factor = clamp(net_rr / minimum_rr, 0.35, 1.0)

        effective_risk_percent = max(0.0, base_risk_percent * risk_reduction_factor)

        target_capital_at_risk = account_balance * (effective_risk_percent / 100)
        position_size_raw = target_capital_at_risk / risk

        raw_sizing_factor = vp_factor * institutional_factor
        capped_sizing_factor = clamp(raw_sizing_factor, 0.65, 1.0)
        adjusted_position_size = position_size_raw * capped_sizing_factor
        capped_position_size = min(adjusted_position_size, max_position_size_limit)
        position_size_capped = capped_position_size < adjusted_position_size
        effective_capital_at_risk = adjusted_position_size * risk
        capped_capital_at_risk = capped_position_size * risk

        return {

            "side": side,

            "entry": round(entry, 8),

            "requested_stop_loss": round(stop_loss, 8),

            "stop_loss": round(adjusted_stop_loss, 8),

            "original_stop_loss": round(stop_loss, 8),

            "stop_adjusted": stop_adjusted,

            "risk_setup_valid": True,

            "risk_setup_reason": "Auto-expanded stop" if stop_adjusted else "OK",

            "atr": round(atr_snapshot, 8),

            "tick_size": round(resolved_tick_size, 8),

            "minimum_tick_distance": round(minimum_tick_distance, 8),

            "minimum_stop_distance": round(minimum_stop_distance, 8),

            "spread_buffer": round(spread_buffer, 8),

            "slippage_buffer": round(slippage_buffer, 8),

            "risk": round(risk, 8),

            "capital_at_risk": round(capped_capital_at_risk, 2),

            "capital_at_risk_target": round(target_capital_at_risk, 2),

            "risk_percent": round(effective_risk_percent, 4),

            "risk_percent_base": round(base_risk_percent, 4),

            "position_size": round(capped_position_size, 4),

            "position_size_raw": round(position_size_raw, 4),

            "position_size_pre_cap": round(adjusted_position_size, 4),

            "position_size_limit": round(max_position_size_limit, 4),

            "position_size_capped": position_size_capped,

            "volume_profile_factor": round(vp_factor, 4),

            "institutional_factor": round(institutional_factor, 4),

            "sizing_factor": round(capped_sizing_factor, 4),

            "sizing_factor_raw": round(raw_sizing_factor, 4),

            "portfolio_risk": (institutional or {}).get("portfolio_risk", {}),

            "adaptive_position_sizing": (institutional or {}).get("adaptive_position_sizing", {}),

            "tp1": tp1,

            "tp2": tp2,

            "tp3": tp3,

            "rr1": rr_breakdown.get("rr_by_tp", {}).get("tp1") if rr_breakdown else None,

            "rr2": rr_breakdown.get("rr_by_tp", {}).get("tp2") if rr_breakdown else None,

            "rr3": rr_breakdown.get("rr_by_tp", {}).get("tp3") if rr_breakdown else None,

            "rr_by_tp": rr_breakdown.get("rr_by_tp") if rr_breakdown else None,

            "selected_tp": rr_breakdown.get("selected_tp") if rr_breakdown else None,

            "selected_rr": rr_breakdown.get("selected_rr") if rr_breakdown else rr,

            "rr_selection_rule": rr_selection_rule,

            "rr": rr,

            "net_rr": net_rr,

            "round_trip_cost_rate": round_trip_cost_rate,

            "minimum_rr": minimum_rr,

            "risk_reduction_factor": round(risk_reduction_factor, 4),

            "requested_risk": round(requested_risk, 8),

        }

    def _resolve_atr(self, atr_value=None, candles=None, atr_period=14):
        if atr_value is not None:
            try:
                return max(0.0, float(atr_value))
            except (TypeError, ValueError):
                return 0.0

        if candles:
            try:
                return max(0.0, float(calculate_atr(candles, period=atr_period)))
            except Exception:
                return 0.0

        return 0.0

    def _resolve_tick_size(self, tick_size, inferred_tick_size, minimum_fallback):
        candidates = [value for value in [tick_size, inferred_tick_size, minimum_fallback] if value is not None]
        resolved = min(candidates) if tick_size is not None else max(candidates)
        return max(minimum_fallback, float(resolved))

    def _resolve_buffer(self, buffer_value, entry, rate, minimum_tick_distance):
        if buffer_value is None:
            resolved = abs(entry) * rate
        else:
            try:
                resolved = abs(float(buffer_value))
            except (TypeError, ValueError):
                resolved = abs(entry) * rate

        return max(resolved, minimum_tick_distance if resolved > 0 else 0.0)

    def _infer_tick_size(self, *prices):
        precision = 0
        for price in prices:
            if price is None:
                continue
            try:
                numeric = float(price)
            except (TypeError, ValueError):
                continue

            text = f"{numeric:.10f}".rstrip("0").rstrip(".")
            if "." in text:
                precision = max(precision, len(text.split(".")[1]))

        if precision <= 0:
            return float(getattr(Config, "MIN_TICK_DISTANCE_FALLBACK", 0.01))

        return 10 ** (-precision)

    def _expand_stop(self, entry, side, minimum_stop_distance, tick_size):
        if side == "LONG":
            candidate = entry - minimum_stop_distance
            return self._snap_to_tick(candidate, tick_size, "down")

        candidate = entry + minimum_stop_distance
        return self._snap_to_tick(candidate, tick_size, "up")

    def _snap_to_tick(self, price, tick_size, direction):
        if tick_size is None or tick_size <= 0:
            return round(price, 8)

        scaled = price / tick_size
        if direction == "down":
            snapped = math.floor(scaled) * tick_size
        else:
            snapped = math.ceil(scaled) * tick_size
        return round(snapped, 8)

    def _invalid_risk_setup(
        self,
        entry,
        stop_loss,
        side,
        reason,
        atr=0.0,
        minimum_stop_distance=0.0,
        tick_size=0.0,
        spread_buffer=0.0,
        slippage_buffer=0.0,
        requested_risk=0.0,
        stop_adjusted=False,
    ):
        return {
            "side": side,
            "entry": round(entry, 8),
            "requested_stop_loss": round(stop_loss, 8),
            "stop_loss": round(stop_loss, 8),
            "original_stop_loss": round(stop_loss, 8),
            "stop_adjusted": stop_adjusted,
            "risk_setup_valid": False,
            "risk_setup_reason": reason,
            "atr": round(atr, 8),
            "tick_size": round(tick_size, 8),
            "minimum_tick_distance": round(max(tick_size, 0.0), 8),
            "minimum_stop_distance": round(minimum_stop_distance, 8),
            "spread_buffer": round(spread_buffer, 8),
            "slippage_buffer": round(slippage_buffer, 8),
            "risk": None,
            "capital_at_risk": None,
            "capital_at_risk_target": None,
            "risk_percent": None,
            "risk_percent_base": None,
            "position_size": None,
            "position_size_raw": None,
            "position_size_pre_cap": None,
            "position_size_limit": float(getattr(Config, "MAX_POSITION_SIZE", 1000.0)),
            "position_size_capped": False,
            "volume_profile_factor": None,
            "institutional_factor": None,
            "sizing_factor": None,
            "sizing_factor_raw": None,
            "portfolio_risk": {},
            "adaptive_position_sizing": {},
            "tp1": None,
            "tp2": None,
            "tp3": None,
            "rr": None,
            "net_rr": None,
            "round_trip_cost_rate": float(getattr(Config, "ROUND_TRIP_COST_RATE", 0.0020)),
            "minimum_rr": float(getattr(Config, "MINIMUM_RR", 3.0)),
            "risk_reduction_factor": None,
            "requested_risk": round(requested_risk, 8),
        }

    def _volume_profile_position_factor(self, volume_profile, side):
        """Volume profile güveni ve yön uyumuna göre pozisyon boyut çarpanı döndürür."""
        if not volume_profile or not volume_profile.get("active"):
            return 1.0

        vp_direction = volume_profile.get("direction", "NONE")
        vp_confidence = volume_profile.get("confidence", 0)
        vp_state = volume_profile.get("state", "NONE")

        direction_match = (
            (side == "LONG" and vp_direction == "BULLISH")
            or (side == "SHORT" and vp_direction == "BEARISH")
        )

        if direction_match:
            state_bonus = 0.05 if (
                (side == "LONG" and vp_state in ["DISCOUNT", "VALUE_LOW", "BELOW_POC"])
                or (side == "SHORT" and vp_state in ["PREMIUM", "VALUE_HIGH", "ABOVE_POC"])
            ) else 0.0

            return clamp(1.0 + (vp_confidence / 450) + state_bonus, 1.0, 1.25)

        state_penalty = 0.05 if vp_state not in ["NONE", ""] else 0.0
        return clamp(1.0 - (vp_confidence / 300) - state_penalty, 0.65, 1.0)

    def _institutional_position_factor(self, institutional, side):
        """Kurumsal akış ve risk koşullarına göre pozisyon boyutunu ayarlar."""
        if not institutional or not institutional.get("active"):
            return 1.0

        factor = 1.0
        flow_direction = institutional.get("direction", "NONE")
        flow_confidence = institutional.get("confidence", 0)
        execution_score = institutional.get("execution_quality", {}).get("score", 0)
        portfolio_score = institutional.get("portfolio_risk", {}).get("score", 100)
        adaptive_factor = institutional.get("adaptive_position_sizing", {}).get("factor", 1.0)

        if (side == "LONG" and flow_direction == "LONG") or (side == "SHORT" and flow_direction == "SHORT"):
            factor += min(0.12, flow_confidence / 900)
        elif flow_direction in ["LONG", "SHORT"]:
            factor -= min(0.18, flow_confidence / 650)

        factor += (execution_score - 50) / 1000
        factor += (portfolio_score - 50) / 1200
        factor += (adaptive_factor - 1.0) / 2

        return clamp(factor, 0.65, 1.25)
