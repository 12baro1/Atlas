"""
setup_quality_engine.py
Atlas Setup Quality Engine

Produces practical module-level scores for professional SMC execution.
"""

from core.analysis_utils import clamp
from utils.atr import atr as calculate_atr


class SetupQualityEngine:
    """Scores independent SMC modules and market conditions before final signal confidence."""

    def evaluate(self, candles, direction, mtf, trend, structure, liquidity_sweep, orderblocks, fvg,
                 premium_discount, market_phase, session, entry, confirmation, smt=None,
                 unicorn=None, cisd=None, volume_profile=None, institutional=None):
        current = candles[-1].close if candles else None
        scores = {
            "market_structure": self._market_structure(direction, mtf, trend, structure),
            "liquidity_sweep": self._liquidity_sweep(direction, liquidity_sweep),
            "order_block": self._order_block(direction, orderblocks, current),
            "fvg": self._fvg(direction, fvg, current),
            "premium_discount": self._premium_discount(direction, premium_discount),
            "mtf_alignment": self._mtf_alignment(direction, mtf, trend),
            "momentum_volatility": self._momentum_volatility(candles, direction),
            "manipulation_filter": self._manipulation_filter(direction, candles, liquidity_sweep, market_phase),
            "session": self._session(session),
            "entry_quality": self._entry_quality(entry, confirmation, current),
            "external_confluence": self._external(direction, smt, unicorn, cisd, volume_profile, institutional),
        }
        weights = {
            "market_structure": 0.16,
            "liquidity_sweep": 0.10,
            "order_block": 0.10,
            "fvg": 0.08,
            "premium_discount": 0.08,
            "mtf_alignment": 0.13,
            "momentum_volatility": 0.12,
            "manipulation_filter": 0.08,
            "session": 0.04,
            "entry_quality": 0.07,
            "external_confluence": 0.04,
        }
        total = sum(scores[name]["score"] * weights[name] for name in weights)
        blockers = [name for name, item in scores.items() if item.get("blocker")]
        if blockers:
            total = min(total, 54)
        reasons = [f"{name}:{item['score']}" for name, item in scores.items()]
        return {
            "active": True,
            "direction": direction,
            "score": int(clamp(total)),
            "confidence": int(clamp(total)),
            "module_scores": scores,
            "blockers": blockers,
            "reasons": reasons,
            "trade_allowed": direction in ["LONG", "SHORT"] and total >= 58 and not blockers,
        }

    def _market_structure(self, direction, mtf, trend, structure):
        if direction not in ["LONG", "SHORT"]:
            return self._score(0, "No trade direction", True)
        recent = structure[-5:] if structure else []
        labels = [x.get("label") for x in recent]
        bos = [x for x in recent if x.get("bos")]
        choch = [x for x in recent if x.get("choch")]
        bullish = direction == "LONG"
        trend_ok = (trend or {}).get("trend") == ("BULLISH" if bullish else "BEARISH")
        continuation = any(l in (["HH", "HL"] if bullish else ["LL", "LH"]) for l in labels)
        fake_choch = bool(choch) and not bos and not trend_ok
        score = 35 + (25 if trend_ok else -20) + (20 if continuation else 0) + (15 if bos else 0) + (5 if choch else 0)
        if fake_choch:
            score -= 30
        return self._score(score, "Trend/structure aligned" if trend_ok else "Trend mismatch", blocker=not trend_ok or fake_choch)

    def _liquidity_sweep(self, direction, sweep):
        if sweep.get("is_sweep"):
            score = 55 + min(30, sweep.get("strength_score", 0) * 0.35)
            if sweep.get("post_structure", {}).get("confirmed"):
                score += 10
            return self._score(score, "Confirmed liquidity sweep")
        if sweep.get("is_breakout"):
            return self._score(45, "Breakout without sweep")
        return self._score(52, "No sweep; not mandatory")

    def _order_block(self, direction, orderblocks, current):
        match = [ob for ob in (orderblocks or []) if ob.get("type") == ("BULLISH" if direction == "LONG" else "BEARISH")]
        fresh = [ob for ob in match if not ob.get("mitigated")]
        if not match:
            return self._score(45, "No matching OB")
        best = max(fresh or match, key=lambda x: x.get("strength", 0))
        score = best.get("strength", 0) + (15 if best in fresh else -10)
        if current and best.get("low") and best.get("high"):
            width = max(best["high"] - best["low"], current * 0.0001)
            distance = min(abs(current - best["high"]), abs(current - best["low"])) / width
            score += max(0, 15 - distance * 5)
        return self._score(score, "OB quality scored")

    def _fvg(self, direction, fvg, current):
        match = [g for g in (fvg or []) if g.get("type") == ("BULLISH" if direction == "LONG" else "BEARISH")]
        fresh = [g for g in match if not g.get("filled")]
        if not fresh:
            return self._score(48, "No fresh FVG; alternative entries allowed")
        best = max(fresh, key=lambda x: x.get("strength", 0) + x.get("size", 0))
        return self._score(best.get("strength", 0), "Fresh valid FVG")

    def _premium_discount(self, direction, pd):
        valid = bool((pd or {}).get("valid"))
        zone = str((pd or {}).get("zone", "")).upper()
        ideal = (direction == "LONG" and "DISCOUNT" in zone) or (direction == "SHORT" and "PREMIUM" in zone)
        return self._score(78 if ideal else (62 if valid else 42), "Premium/discount checked")

    def _mtf_alignment(self, direction, mtf, trend):
        valid = bool((mtf or {}).get("valid")) and (mtf or {}).get("entry") == direction
        return self._score(82 if valid else 35, "MTF aligned" if valid else "MTF conflict", blocker=not valid)

    def _momentum_volatility(self, candles, direction):
        if not candles or len(candles) < 20:
            return self._score(55, "Limited volatility data")
        a = calculate_atr(candles, 14)
        price = candles[-1].close
        atr_pct = a / price if price else 0
        body = abs(candles[-1].close - candles[-1].open)
        bullish = candles[-1].close > candles[-1].open
        momentum_ok = bullish if direction == "LONG" else not bullish
        score = 70 if 0.0015 <= atr_pct <= 0.045 else 38
        score += 12 if momentum_ok and body >= a * 0.25 else -8
        return self._score(score, "ATR/momentum tradable", blocker=atr_pct < 0.0008 or atr_pct > 0.08)

    def _manipulation_filter(self, direction, candles, sweep, phase):
        phase_name = (phase or {}).get("phase", "")
        if phase_name in ["Manipulation", "Distribution"] and not sweep.get("post_structure", {}).get("confirmed"):
            return self._score(35, "Manipulation risk not reclaimed", True)
        return self._score(72 if sweep.get("is_sweep") else 58, "Stop-hunt/manipulation filter passed")

    def _session(self, session):
        return self._score(68 if session else 52, "Session checked")

    def _entry_quality(self, entry, confirmation, current):
        if not entry.get("valid"):
            return self._score(20, "Invalid entry", True)
        mode_bonus = {"MARKET": 14, "LIMIT": 8, "CONFIRMATION": 5}.get(entry.get("entry_type"), 0)
        near_bonus = 0
        if current and entry.get("entry"):
            near_bonus = max(0, 15 - abs(entry["entry"] - current) / current * 1000)
        return self._score(55 + mode_bonus + near_bonus + (8 if confirmation.get("confirmed") else -12), "Entry quality")

    def _external(self, direction, *mods):
        score = 55
        for mod in mods:
            if not mod or not mod.get("active"):
                continue
            raw_dir = mod.get("direction") or (mod.get("best") or {}).get("direction")
            match = raw_dir in [direction, "BULLISH" if direction == "LONG" else "BEARISH"]
            score += (8 if match else -10) + min(8, mod.get("confidence", 0) / 15)
        return self._score(score, "External confluence scored")

    def _score(self, score, reason, blocker=False):
        return {"score": int(clamp(score)), "reason": reason, "blocker": bool(blocker)}
