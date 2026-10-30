"""
entry_engine.py
Atlas Entry Engine v5
"""

import math

from config import Config
from utils.atr import atr as calculate_atr


class EntryEngine:

    def _structure_fallback_levels(self, direction, structure):
        """FVG/OB yoksa son swinglerden entry ve stop_loss üretir."""
        highs = [item["price"] for item in structure if item.get("kind") == "HIGH"]
        lows = [item["price"] for item in structure if item.get("kind") == "LOW"]

        if direction == "LONG":
            if not lows:
                return None, None

            stop_loss = lows[-1]
            reference_high = highs[-1] if highs else stop_loss * 1.01
            entry = (reference_high + stop_loss) / 2
            if entry <= stop_loss:
                entry = stop_loss * 1.002
            return entry, stop_loss

        if not highs:
            return None, None

        stop_loss = highs[-1]
        reference_low = lows[-1] if lows else stop_loss * 0.99
        entry = (reference_low + stop_loss) / 2
        if entry >= stop_loss:
            entry = stop_loss * 0.998
        return entry, stop_loss

    def _select_structural_stop(self, direction, structure, selected_fvg, selected_ob):
        """Choose the outermost relevant swing/POI invalidation level."""
        candidates = []
        if direction == "LONG":
            if selected_ob:
                value = self._safe_price(selected_ob.get("low"))
                if value is not None:
                    candidates.append(("order_block", value))
            if selected_fvg:
                value = self._safe_price(selected_fvg.get("from"))
                if value is not None:
                    candidates.append(("fvg", value))
            for item in reversed(structure or []):
                kind = str(item.get("kind", "")).upper()
                label = str(item.get("label", "")).upper()
                if kind == "LOW" or label in {"HL", "LL"}:
                    value = self._safe_price(item.get("price", item.get("low")))
                    if value is not None:
                        candidates.append(("swing_low", value))
                        break
            selected = min(candidates, key=lambda item: item[1]) if candidates else None
            return (selected[1], selected[0]) if selected else (None, None)

        if selected_ob:
            value = self._safe_price(selected_ob.get("high"))
            if value is not None:
                candidates.append(("order_block", value))
        if selected_fvg:
            value = self._safe_price(selected_fvg.get("to"))
            if value is not None:
                candidates.append(("fvg", value))
        for item in reversed(structure or []):
            kind = str(item.get("kind", "")).upper()
            label = str(item.get("label", "")).upper()
            if kind == "HIGH" or label in {"LH", "HH"}:
                value = self._safe_price(item.get("price", item.get("high")))
                if value is not None:
                    candidates.append(("swing_high", value))
                    break
        selected = max(candidates, key=lambda item: item[1]) if candidates else None
        return (selected[1], selected[0]) if selected else (None, None)

    def _safe_price(self, value):
        try:
            price = float(value)
        except (TypeError, ValueError):
            return None
        return price if math.isfinite(price) and price > 0 else None

    def generate(self, mtf, structure, fvg, orderblocks, current_price=None, allow_structure_fallback=False, candles=None):
        mtf = mtf if isinstance(mtf, dict) else {}
        structure = structure if isinstance(structure, list) else []
        fvg = fvg if isinstance(fvg, list) else []
        orderblocks = orderblocks if isinstance(orderblocks, list) else []
        current_price = self._safe_price(current_price)

        result = {
            "valid": False,
            "direction": "NONE",
            "entry": None,
            "stop_loss": None,
            "entry_type": "NONE",
            "entry_type_reason": "No valid directional setup",
            "entry_zone_crossed": False,
            "entry_too_far": False,
            "requires_pullback": False,
            "score": 0,
            "reason": "",
            "checks": []
        }

        direction = mtf.get("entry")

        if direction not in ["LONG", "SHORT"] and allow_structure_fallback and structure:
            # Optional legacy mode: infer direction from 15m structure only when explicitly enabled.
            last_label = structure[-1].get("label")
            if last_label in ["HH", "HL"]:
                direction = "LONG"
            elif last_label in ["LL", "LH"]:
                direction = "SHORT"

        if direction not in ["LONG", "SHORT"]:
            result["reason"] = "No MTF direction"
            return result

        result["direction"] = direction

        # -------------------------
        # Structure
        # -------------------------

        if structure:

            last = structure[-1]["label"]

            if direction == "LONG":

                if last in ["HH", "HL"]:
                    result["score"] += 20
                    result["checks"].append("✓ Bullish Structure")
                else:
                    result["checks"].append("✗ Bullish Structure")

            else:

                if last in ["LL", "LH"]:
                    result["score"] += 20
                    result["checks"].append("✓ Bearish Structure")
                else:
                    result["checks"].append("✗ Bearish Structure")

        # -------------------------
        # Best FVG
        # -------------------------

        selected_fvg = None

        for gap in reversed(fvg):

            if gap.get("filled", False):
                continue

            if direction == "LONG" and gap["type"] == "BULLISH":
                selected_fvg = gap
                break

            if direction == "SHORT" and gap["type"] == "BEARISH":
                selected_fvg = gap
                break

        if selected_fvg:
            result["score"] += 25
            result["checks"].append("✓ Fresh FVG")
        else:
            result["checks"].append("✗ FVG")

        # -------------------------
        # Best Order Block
        # -------------------------

        selected_ob = None

        for ob in reversed(orderblocks):

            if ob.get("mitigated", False):
                continue

            if direction == "LONG" and ob["type"] == "BULLISH":
                selected_ob = ob
                break

            if direction == "SHORT" and ob["type"] == "BEARISH":
                selected_ob = ob
                break

        if selected_ob:
            result["score"] += 25
            result["checks"].append("✓ Fresh Order Block")
        else:
            result["checks"].append("✗ Order Block")

        # -------------------------
        # Entry
        # -------------------------

        if direction == "LONG":

            result["stop_loss"], result["stop_source"] = self._select_structural_stop(
                direction, structure, selected_fvg, selected_ob
            )

            limit_entry = selected_fvg["to"] if selected_fvg else (selected_ob["high"] if selected_ob else None)
            if current_price is not None and result["stop_loss"] is not None:
                near_market = current_price > result["stop_loss"] and (limit_entry is None or abs(current_price - limit_entry) / current_price <= 0.004)
                if near_market:
                    result["entry"] = current_price
                    result["entry_type"] = "MARKET"
                    result["entry_type_reason"] = "Price is within 0.4% of the selected bullish POI"
                    result["score"] += 10
                    result["checks"].append("✓ Market Entry Near POI")
                elif limit_entry is not None and current_price > limit_entry:
                    result["entry"] = limit_entry
                    result["entry_type"] = "LIMIT"
                    result["requires_pullback"] = True
                    result["entry_type_reason"] = "Wait for pullback to bullish POI"
                else:
                    result["entry"] = None
                    result["entry_type"] = "NONE"
                    result["entry_type_reason"] = "Bullish POI already crossed; wait for a fresh setup"
                    result["entry_zone_crossed"] = True
            else:
                result["entry"] = limit_entry
                result["entry_type"] = "LIMIT" if limit_entry is not None else "NONE"
                result["entry_type_reason"] = "Bullish POI limit level" if limit_entry is not None else "No valid bullish POI"

        else:

            result["stop_loss"], result["stop_source"] = self._select_structural_stop(
                direction, structure, selected_fvg, selected_ob
            )

            limit_entry = selected_fvg["from"] if selected_fvg else (selected_ob["low"] if selected_ob else None)
            if current_price is not None and result["stop_loss"] is not None:
                near_market = current_price < result["stop_loss"] and (limit_entry is None or abs(current_price - limit_entry) / current_price <= 0.004)
                if near_market:
                    result["entry"] = current_price
                    result["entry_type"] = "MARKET"
                    result["entry_type_reason"] = "Price is within 0.4% of the selected bearish POI"
                    result["score"] += 10
                    result["checks"].append("✓ Market Entry Near POI")
                elif limit_entry is not None and current_price < limit_entry:
                    result["entry"] = limit_entry
                    result["entry_type"] = "LIMIT"
                    result["requires_pullback"] = True
                    result["entry_type_reason"] = "Wait for pullback to bearish POI"
                else:
                    result["entry"] = None
                    result["entry_type"] = "NONE"
                    result["entry_type_reason"] = "Bearish POI already crossed; wait for a fresh setup"
                    result["entry_zone_crossed"] = True
            else:
                result["entry"] = limit_entry
                result["entry_type"] = "LIMIT" if limit_entry is not None else "NONE"
                result["entry_type_reason"] = "Bearish POI limit level" if limit_entry is not None else "No valid bearish POI"

        # Keep valid pending LIMIT POIs regardless of distance. Distance is
        # informational so the user can distinguish near vs far entries.
        if result.get("requires_pullback") and result.get("entry") is not None and current_price is not None:
            distance = abs(result["entry"] - current_price)
            distance_pct = distance / current_price if current_price > 0 else None
            atr_value = 0.0
            try:
                if candles:
                    atr_value = float(calculate_atr(candles, period=int(getattr(Config, "ATR_PERIOD", 14))))
            except (TypeError, ValueError, OverflowError):
                atr_value = 0.0
            result["entry_distance_pct"] = round(distance_pct * 100.0, 4) if distance_pct is not None else None
            result["entry_distance_atr"] = round(distance / atr_value, 3) if atr_value > 0 else None
            is_near = (
                distance_pct is not None
                and distance_pct <= 0.01
                and (atr_value <= 0 or distance <= atr_value)
            )
            result["entry_distance_label"] = "YAKIN GİRİŞ" if is_near else "UZAK GİRİŞ"
            result["entry_type_reason"] = (
                "Fiyat LIMIT giriş bölgesine dönünce emir tetiklenir; " + result["entry_distance_label"].lower()
            )

        if (
            (result["entry"] is None or result["stop_loss"] is None)
            and not result.get("entry_zone_crossed")
            and not result.get("entry_too_far")
        ):
            fallback_entry, fallback_sl = self._structure_fallback_levels(direction, structure)
            market_side_valid = (
                current_price is not None
                and fallback_sl is not None
                and (
                    (direction == "LONG" and current_price > fallback_sl)
                    or (direction == "SHORT" and current_price < fallback_sl)
                )
            )
            # A swing midpoint is not itself an executable order. Only recommend
            # the fallback as MARKET when a finite live price is available and
            # remains on the valid side of structural invalidation.
            fallback_stop_invalid = (
                fallback_entry is not None
                and fallback_sl is not None
                and (
                    (direction == "LONG" and fallback_sl >= fallback_entry)
                    or (direction == "SHORT" and fallback_sl <= fallback_entry)
                )
            )
            if fallback_stop_invalid:
                # Preserve the invalid levels long enough for the directional
                # stop guard below to report the precise structural error.
                result["entry"] = fallback_entry
                result["stop_loss"] = fallback_sl
                result["stop_source"] = "swing_fallback"
                result["checks"].append("✗ SL direction")
            elif fallback_entry is not None and fallback_sl is not None and market_side_valid:
                result["entry"] = current_price
                result["stop_loss"] = fallback_sl
                result["stop_source"] = "swing_fallback"
                result["score"] += 20
                result["entry_type"] = "MARKET"
                result["entry_type_reason"] = "Market entry from valid structural fallback"
                result["checks"].append("✓ Market Structure Entry")
                result["checks"].append("✓ Structure Fallback Levels")
            else:
                result["entry"] = None
                result["stop_loss"] = None
                result["entry_type"] = "NONE"
                result["entry_type_reason"] = "No executable MARKET/LIMIT entry available"
                result["checks"].append("✗ Executable Structure Fallback Entry")

        # -------------------------
        # Risk Filter
        # -------------------------

        if (
            result["entry"] is not None
            and result["stop_loss"] is not None
        ):

            distance = abs(
                result["entry"] -
                result["stop_loss"]
            )

            if distance > 0:
                result["score"] += 30
            else:
                result["checks"].append("✗ Invalid SL")

        # Directional SL guard: LONG stops must be below entry; SHORT stops above.
        if result["entry"] is not None and result["stop_loss"] is not None:
            if direction == "LONG" and result["stop_loss"] >= result["entry"]:
                result["reason"] = "Invalid LONG: stop-loss must be below entry"
                result["checks"].append("✗ SL direction")
                return result
            if direction == "SHORT" and result["stop_loss"] <= result["entry"]:
                result["reason"] = "Invalid SHORT: stop-loss must be above entry"
                result["checks"].append("✗ SL direction")
                return result

        result["valid"] = (
            not result.get("entry_too_far")
            and result["score"] >= 60
            and result["entry_type"] in {"MARKET", "LIMIT"}
            and result["entry"] is not None
            and result["stop_loss"] is not None
        )

        if result["valid"]:
            result["reason"] = "High probability setup"
        else:
            result["reason"] = "Weak setup"

        return result
