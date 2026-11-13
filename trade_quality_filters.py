"""
trade_quality_filters.py

Atlas Kontrollü İşlem Kalite Filtreleri

Tüm filtreler YALNIZCA kanıt üretir (geçti/geçmedi, ciddiyet, neden, skor
cezası/bonusu). Hiçbir filtre tek başına işlemi iptal etmez veya alt motor
olarak bağımsız karar vermez. Üretilen kanıt, tek nihai yetkili olan
DecisionEngine'e (tek ana karar motoru) trade_quality engelleri üzerinden
iletilir ve DecisionEngine karar verir.

Filtreler:
  1. HTF/LTF uyumu: 4H piyasa yapısıyla 15M işlem yönünün eşliği.
  2. Likidite kalitesi: Sweep, SFP, EQH/EQL ve likidite hedefleri.
  3. Giriş mesafesi: Giriş-fiyat/POI uzaklığı ATR ile ölçülür.
  4. Stop kalitesi: Stop swing yapısı ve invalidation seviyesine göre.
  5. TP/RR tutarlılığı: TP'ler gerçek likiditeye, net RR komisyon+spread ile.
  6. Motor çetelişi: Güçlü bağımsız motorların yön çetelişi.

LONG ve SHORT simetrik olarak değerlendirilir; hiçbir yöne keyfi avantaj
verilmez. Sweep her işlemde zorunlu tutulmaz.
"""

import math

from config import Config
from utils.atr import atr as calculate_atr


class TradeQualityFilters:
    """Alt motor kanıtlayıcıları; nihai kabul/red kararı DecisionEngine'dir."""

    def __init__(self):
        # Per-filter elimination bookkeeping for backtest reporting.
        # {filter_name: {"total": int, "blocked": int, "winners_blocked": int,
        #                "losers_blocked": int}}
        self.elimination = {
            "htf_ltf_alignment": {"total": 0, "blocked": 0, "winners_blocked": 0, "losers_blocked": 0},
            "liquidity_quality": {"total": 0, "blocked": 0, "winners_blocked": 0, "losers_blocked": 0},
            "entry_distance": {"total": 0, "blocked": 0, "winners_blocked": 0, "losers_blocked": 0},
            "stop_quality": {"total": 0, "blocked": 0, "winners_blocked": 0, "losers_blocked": 0},
            "tp_rr_consistency": {"total": 0, "blocked": 0, "winners_blocked": 0, "losers_blocked": 0},
            "motor_conflict": {"total": 0, "blocked": 0, "winners_blocked": 0, "losers_blocked": 0},
        }
        self._enabled = bool(getattr(Config, "QUALITY_FILTERS_ENABLED", True))

    # ------------------------------------------------------------------ public

    def evaluate_all(
        self,
        *,
        direction,
        entry,
        risk,
        dynamic_tp,
        current_price,
        candles,
        atr_value=None,
        mtf=None,
        h4_structure=None,
        entry_structure=None,
        liquidity_sweep=None,
        liquidity_layers=None,
        eqh_eql=None,
        smt=None,
        cisd=None,
        volume_profile=None,
        institutional=None,
        unicorn=None,
        spread_rate=None,
        commission_rate=None,
    ):
        """Alt motor değerlendirmesi; ana motor karar için kanıt döndürür.

        Döndürür:
            {
              "enabled": bool,
              "allowed": bool,                 # tüm kritik filtreler geçti mi
              "critical_blockers": [str],      # DecisionEngine'e SKIP gerekçesi
              "adjustments": [{"delta": int, "label": str}],  # skor cezası/bonusu
              "warnings": [str],               # veto etmez, yalnızca kanıt
              "filters": {name: {...per-filter detail...}},
            }
        """
        result = {
            "enabled": self._enabled,
            "allowed": True,
            "critical_blockers": [],
            "adjustments": [],
            "warnings": [],
            "filters": {},
        }

        if not self._enabled:
            return result

        direction = str(direction or "").upper()
        mtf = mtf if isinstance(mtf, dict) else {}
        entry = entry if isinstance(entry, dict) else {}
        risk = risk if isinstance(risk, dict) else {}
        dynamic_tp = dynamic_tp if isinstance(dynamic_tp, dict) else {}
        liquidity_sweep = liquidity_sweep if isinstance(liquidity_sweep, dict) else {}
        liquidity_layers = liquidity_layers if isinstance(liquidity_layers, dict) else {}
        eqh_eql = eqh_eql if isinstance(eqh_eql, dict) else {}
        candles = candles if isinstance(candles, (list, tuple)) else []

        atr = self._resolve_atr(atr_value, candles)

        # 1. HTF/LTF uyumu
        f1 = self._filter_htf_ltf_alignment(
            direction=direction, mtf=mtf, h4_structure=h4_structure,
            entry_structure=entry_structure, liquidity_sweep=liquidity_sweep,
        )
        result["filters"]["htf_ltf_alignment"] = f1
        result["critical_blockers"].extend(f1.get("critical_blockers", []))
        result["adjustments"].extend(f1.get("adjustments", []))
        result["warnings"].extend(f1.get("warnings", []))
        if not f1["passed"]:
            result["allowed"] = False

        # 2. Likidite kalitesi
        f2 = self._filter_liquidity_quality(
            direction=direction, liquidity_sweep=liquidity_sweep,
            liquidity_layers=liquidity_layers, eqh_eql=eqh_eql,
            dynamic_tp=dynamic_tp, entry=entry,
        )
        result["filters"]["liquidity_quality"] = f2
        result["critical_blockers"].extend(f2.get("critical_blockers", []))
        result["adjustments"].extend(f2.get("adjustments", []))
        result["warnings"].extend(f2.get("warnings", []))
        if not f2["passed"]:
            result["allowed"] = False

        # 3. Giriş mesafesi
        f3 = self._filter_entry_distance(
            direction=direction, entry=entry, current_price=current_price,
            atr=atr,
        )
        result["filters"]["entry_distance"] = f3
        result["critical_blockers"].extend(f3.get("critical_blockers", []))
        result["adjustments"].extend(f3.get("adjustments", []))
        result["warnings"].extend(f3.get("warnings", []))
        if not f3["passed"]:
            result["allowed"] = False

        # 4. Stop kalitesi
        f4 = self._filter_stop_quality(
            direction=direction, entry=entry, risk=risk, atr=atr,
            entry_structure=entry_structure or h4_structure,
        )
        result["filters"]["stop_quality"] = f4
        result["critical_blockers"].extend(f4.get("critical_blockers", []))
        result["adjustments"].extend(f4.get("adjustments", []))
        result["warnings"].extend(f4.get("warnings", []))
        if not f4["passed"]:
            result["allowed"] = False

        # 5. TP/RR tutarlılığı
        f5 = self._filter_tp_rr_consistency(
            direction=direction, entry=entry, risk=risk,
            dynamic_tp=dynamic_tp, atr=atr,
        )
        result["filters"]["tp_rr_consistency"] = f5
        result["critical_blockers"].extend(f5.get("critical_blockers", []))
        result["adjustments"].extend(f5.get("adjustments", []))
        result["warnings"].extend(f5.get("warnings", []))
        if not f5["passed"]:
            result["allowed"] = False

        # 6. Motor çetelişi
        f6 = self._filter_motor_conflict(
            direction=direction, smt=smt, cisd=cisd, volume_profile=volume_profile,
            institutional=institutional, unicorn=unicorn,
        )
        result["filters"]["motor_conflict"] = f6
        result["critical_blockers"].extend(f6.get("critical_blockers", []))
        result["adjustments"].extend(f6.get("adjustments", []))
        result["warnings"].extend(f6.get("warnings", []))
        if not f6["passed"]:
            result["allowed"] = False

        # Kritik engelleri benzersiz yap (DecisionEngine zaten _append_unique
        # ile tekilleştirir, ama burada da netlik için tekilleştirilir).
        result["critical_blockers"] = self._unique(result["critical_blockers"])
        return result

    def record_elimination(self, filter_name, was_winner, was_blocked):
        """Backtest raporu için filtre bazlı kazanan/kaybeden çıkarma sayacı."""
        if filter_name not in self.elimination:
            return
        bucket = self.elimination[filter_name]
        bucket["total"] += 1
        if was_blocked:
            bucket["blocked"] += 1
            if was_winner:
                bucket["winners_blocked"] += 1
            else:
                bucket["losers_blocked"] += 1

    def elimination_report(self):
        """Her filtre: kaç işlem değerlendirildi, kaç engelledi, kaç kazanan/
        kaybedeni çıkardı. Net RR/PF üzerinden yorum yapılabilir."""
        report = {}
        for name, bucket in self.elimination.items():
            total = bucket["total"]
            blocked = bucket["blocked"]
            report[name] = {
                "evaluated": total,
                "blocked": blocked,
                "block_rate": round(blocked / total, 4) if total else 0.0,
                "winners_blocked": bucket["winners_blocked"],
                "losers_blocked": bucket["losers_blocked"],
            }
        return report

    def reset_elimination(self):
        for bucket in self.elimination.values():
            bucket.update(total=0, blocked=0, winners_blocked=0, losers_blocked=0)

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _unique(items):
        seen = []
        for item in items:
            if item and item not in seen:
                seen.append(item)
        return seen

    def _resolve_atr(self, atr_value, candles):
        if atr_value is not None:
            try:
                value = float(atr_value)
                return value if math.isfinite(value) and value > 0 else 0.0
            except (TypeError, ValueError, OverflowError):
                return 0.0
        if candles:
            try:
                value = float(calculate_atr(list(candles), period=int(getattr(Config, "ATR_PERIOD", 14))))
                return value if math.isfinite(value) and value > 0 else 0.0
            except (TypeError, ValueError, OverflowError, ZeroDivisionError):
                return 0.0
        return 0.0

    @staticmethod
    def _safe_float(value):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _match_direction(module_direction, trade_direction):
        if trade_direction not in {"LONG", "SHORT"}:
            return False
        module_direction = str(module_direction or "").upper()
        if trade_direction == "LONG":
            return module_direction in {"LONG", "BULLISH"}
        return module_direction in {"SHORT", "BEARISH"}

    @staticmethod
    def _module_side(module):
        if not isinstance(module, dict):
            return "NONE"
        value = module.get("direction") or module.get("signal") or module.get("trend") or module.get("type")
        if not value and isinstance(module.get("best"), dict):
            best = module["best"]
            value = best.get("direction") or best.get("signal") or best.get("trend") or best.get("type")
        return str(value or "NONE").upper()

    # ---------------------------------------------------------------- filter 1

    def _filter_htf_ltf_alignment(
        self, *, direction, mtf, h4_structure, entry_structure, liquidity_sweep
    ):
        """4H yapısıyla 15M yön uyumu. Güçlü ters yapı engeller; nötr geçer.

        Kanıt: mtf.h4 (4H trend), mtf.entry (15M sinyal yönü),
        mtf.entry_source (H4_STRUCTURE / CONFIRMED_15M_REVERSAL),
        liquidity_sweep.post_structure (onaylı ters dönüş).
        """
        detail = {
            "name": "HTF/LTF uyumu",
            "passed": True,
            "severity": "none",
            "reason": "",
            "score_delta": 0,
            "critical_blockers": [],
            "adjustments": [],
            "warnings": [],
        }

        h4_trend = str((mtf or {}).get("h4", "NEUTRAL")).upper()
        entry_signal = str((mtf or {}).get("entry", "NONE")).upper()
        entry_source = str((mtf or {}).get("entry_source", "")).upper()

        if direction not in {"LONG", "SHORT"} or h4_trend not in {"BULLISH", "BEARISH"}:
            # HTF yönü yoksa 15M'e değer kalır; filtre sessize geçer.
            detail["passed"] = True
            detail["reason"] = "HTF yönü tanımlı değil; 15M üzerinden değerlendirilir"
            return detail

        if (
            entry_signal in {"LONG", "SHORT"} and entry_signal != direction
        ) or (
            entry_source == "CONFIRMED_15M_REVERSAL" and entry_signal != direction
        ):
            detail["passed"] = False
            detail["severity"] = "critical"
            detail["reason"] = (
                f"MTF entry direction conflicts with setup: "
                f"15m={entry_signal}, setup={direction}"
            )
            detail["critical_blockers"].append(
                f"MTF entry direction {entry_signal} conflicts with setup {direction}"
            )
            return detail

        aligned = (
            (direction == "LONG" and h4_trend == "BULLISH")
            or (direction == "SHORT" and h4_trend == "BEARISH")
        )
        opposing = not aligned

        # Ters dönüşler 4H karşıtlığına karşın geçerlidir; onaylı swept
        # reversal bir yorum yapısıdır, otomatik veto değildir.
        post = liquidity_sweep.get("post_structure") if isinstance(liquidity_sweep.get("post_structure"), dict) else {}
        sweep_side = str(liquidity_sweep.get("sweep_side") or "").upper()
        expected_sweep_side = "SELL_SIDE" if direction == "LONG" else "BUY_SIDE"
        post_type = str(post.get("type") or "").upper()
        sweep_index = post.get("sweep_index", liquidity_sweep.get("sweep_index"))
        confirmation_index = post.get("confirmation_index")
        causal_confirmation = False
        if sweep_index is not None and confirmation_index is not None:
            try:
                causal_confirmation = int(confirmation_index) > int(sweep_index)
            except (TypeError, ValueError, OverflowError):
                causal_confirmation = False
        confirmed_reversal = bool(
            entry_source == "CONFIRMED_15M_REVERSAL"
            and entry_signal == direction
            and liquidity_sweep.get("is_sweep")
            and sweep_side == expected_sweep_side
            and post.get("confirmed")
            and (not post_type or post_type == "CHOCH")
            and self._match_direction(post.get("direction"), direction)
            and causal_confirmation
        )

        if aligned:
            detail["passed"] = True
            detail["reason"] = f"4H yapısı {direction} ile aynı yönde"
            detail["score_delta"] = 2
            detail["adjustments"].append({"delta": 2, "label": "HTF + LTF aligned"})
            return detail

        # Karşı yönlü 4H yapısı.
        if confirmed_reversal:
            detail["passed"] = True
            detail["severity"] = "warning"
            detail["reason"] = (
                f"4H {h4_trend} ama onaylı swept reversal {direction}; ters-yön yorumu, engel değil"
            )
            detail["warnings"].append(f"HTF conflict with confirmed reversal ({direction})")
            return detail

        # Güçlü ters yapı: 4H yönü işlem yönüne karşı ve onaylı reversal yok.
        detail["passed"] = False
        detail["severity"] = "critical"
        detail["reason"] = (
            f"Güçlü ters HTF yapısı: 4H={h4_trend}, işlem={direction}, "
            "onaylı swept reversal yok"
        )
        detail["critical_blockers"].append(
            f"HTF/LTF conflict: 4H {h4_trend} opposes {direction} without confirmed reversal"
        )
        return detail

    # ---------------------------------------------------------------- filter 2

    def _filter_liquidity_quality(
        self, *, direction, liquidity_sweep, liquidity_layers, eqh_eql, dynamic_tp, entry
    ):
        """Likidite kalitesi: sweep, SFP, EQH/EQL, hedefler.

        Sweep her işlemde ZORUNLU DEĞIL; sweep yoksa yalnızca kanıt zayıflar.
        Gerçeklik kontrolü: tek taraflı sweep, EQH/EQL kümeleri ve TP hedeflerinin
        gerçek likiditeyle örtüşmesi.
        """
        detail = {
            "name": "Likidite kalitesi",
            "passed": True,
            "severity": "none",
            "reason": "",
            "score_delta": 0,
            "critical_blockers": [],
            "adjustments": [],
            "warnings": [],
        }

        is_sweep = bool(liquidity_sweep.get("is_sweep"))
        buy_side = bool(liquidity_sweep.get("buy_side"))
        sell_side = bool(liquidity_sweep.get("sell_side"))
        ambiguous = bool(liquidity_sweep.get("ambiguous_sweep"))
        post = liquidity_sweep.get("post_structure") if isinstance(liquidity_sweep.get("post_structure"), dict) else {}
        post_confirmed = bool(post.get("confirmed"))
        post_direction = str(post.get("direction", "")).upper()

        expected_sweep = sell_side if direction == "LONG" else buy_side
        opposing_sweep = buy_side if direction == "LONG" else sell_side

        swing_layers = liquidity_layers.get("swing", []) if isinstance(liquidity_layers, dict) else []
        internal_layers = liquidity_layers.get("internal", []) if isinstance(liquidity_layers, dict) else []

        eqh = eqh_eql.get("eqh", []) if isinstance(eqh_eql, dict) else []
        eql = eqh_eql.get("eql", []) if isinstance(eqh_eql, dict) else []
        expected_eq = eqh if direction == "LONG" else eql
        opposite_eq = eql if direction == "LONG" else eqh

        targets = dynamic_tp.get("targets") or []
        if isinstance(targets, dict):
            targets = [targets.get("tp1"), targets.get("tp2"), targets.get("tp3")]
        targets = [t for t in targets if self._safe_float(t) is not None]

        entry_price = self._safe_float(entry.get("entry"))

        score = 50
        reasons = []

        if is_sweep and not ambiguous:
            if expected_sweep and post_confirmed and self._match_direction(post_direction, direction):
                score += 25
                reasons.append("Tek taraflı onaylı sweep işlem yönünde")
            elif expected_sweep and not post_confirmed:
                score += 10
                reasons.append("Sweep algılandı ancak post-süreç onayı eksik")
            elif opposing_sweep:
                # Karşı sweep işlem kalitesini zayıflandırır ancak zaten
                # TradeQualityEngine'de uyarı olarak tutulur; burada da veto
                # yerine uyarı kalır (sweep her işlemde zorunlu değil).
                score -= 10
                reasons.append("Sweep işlem yönüne karşı (çeşitre refakat)")
                detail["warnings"].append(
                    "Sweep evidence opposes the setup; use it to refine the POI entry"
                )
        elif ambiguous:
            score -= 5
            reasons.append("Sweep iki yönde de algılandı; yön belirsiz")
        else:
            # Sweep zorunlu değil: puanı etkilemez, yalnızca kanıt notu.
            reasons.append("Sweep zorunlu değil; likidite kanıtı kısmi")

        if expected_eq:
            score += min(15, len(expected_eq) * 5)
            reasons.append(f"{len(expected_eq)} EQH/EQL kümeleri işlem yönünde")
        if opposite_eq:
            score -= min(20, len(opposite_eq) * 4)
            reasons.append(f"{len(opposite_eq)} karşı-yön EQH/EQL kümeleri")

        # TP hedeflerinin gerçek likidite seviyelerine yakınlığı (basit mesafe kontrolü).
        liquidity_prices = []
        for layer in list(swing_layers) + list(internal_layers):
            if isinstance(layer, dict) and layer.get("price") is not None:
                price = self._safe_float(layer.get("price"))
                if price is not None:
                    liquidity_prices.append(price)
        if targets and entry_price is not None and liquidity_prices:
            aligned_targets = 0
            for target in targets:
                target = self._safe_float(target)
                if target is None:
                    continue
                nearest = min(abs(target - lp) for lp in liquidity_prices)
                # %0.25 civarı bir likidite kümesine ulaşmak "gerçek hedef" sayılır.
                if entry_price and nearest <= max(entry_price * 0.0025, 1e-9):
                    aligned_targets += 1
            if aligned_targets:
                score += 10
                reasons.append(f"{aligned_targets} hedef gerçek likidite kümesine uygun")
            else:
                reasons.append("Hedefler net likidite kümesiyle örtüşmemiş olabilir")

        if score < 30:
            detail["passed"] = False
            detail["severity"] = "critical"
            detail["reason"] = "Zayıf/çatışan likidite kanıtı; " + "; ".join(reasons[:3])
            detail["critical_blockers"].append("Liquidity quality: weak or conflicting liquidity evidence")
        elif score <= 60:
            detail["passed"] = True
            detail["severity"] = "warning"
            detail["reason"] = "Orta seviyede likidite kalitesi; " + "; ".join(reasons[:3])
            detail["warnings"].append("Liquidity quality: moderate")
        else:
            detail["passed"] = True
            detail["severity"] = "none"
            detail["reason"] = "Likidite kalitesi yeterli; " + "; ".join(reasons[:3])
            if score >= 80:
                detail["score_delta"] = 4
                detail["adjustments"].append({"delta": 4, "label": "Strong liquidity quality"})

        detail["score"] = score
        return detail

    # ---------------------------------------------------------------- filter 3

    def _filter_entry_distance(self, *, direction, entry, current_price, atr):
        """Giriş mesafesi: ATR cinsinden giriş-fiyat ve POI uzaklığı.

        Geç kalınmış girişler engellenir; bekleyen LIMIT girişleri mesafesiyle
        uyarmakla beraber otomatik olarak reddedilmez.
        """
        detail = {
            "name": "Giriş mesafesi",
            "passed": True,
            "severity": "none",
            "reason": "",
            "score_delta": 0,
            "critical_blockers": [],
            "adjustments": [],
            "warnings": [],
        }

        entry_price = self._safe_float(entry.get("entry"))
        current = self._safe_float(current_price)
        entry_type = str(entry.get("entry_type") or "").upper()
        max_distance_atr = float(getattr(Config, "QUALITY_MAX_ENTRY_DISTANCE_ATR", 2.0))

        if entry_price is None or current is None or atr <= 0:
            detail["passed"] = True
            detail["reason"] = "ATR veya fiyat eksik; mesafe filtresi devre dışı"
            return detail

        distance = abs(entry_price - current)
        distance_atr = distance / atr
        distance_pct = distance / abs(current)

        detail["distance_atr"] = round(distance_atr, 3)
        detail["distance_pct"] = round(distance_pct * 100, 4)

        if entry_type == "MARKET" and distance_atr > max_distance_atr:
            detail["passed"] = False
            detail["severity"] = "critical"
            detail["reason"] = (
                f"Geç MARKET girişi: {distance_atr:.2f} ATR ({distance_pct:.2%}) > "
                f"{max_distance_atr} ATR sınırı"
            )
            detail["critical_blockers"].append(
                f"Entry too far: {distance_atr:.2f} ATR from market price (MARKET)"
            )
            return detail

        if entry_type == "LIMIT" and distance_atr > max_distance_atr:
            detail["passed"] = True
            detail["severity"] = "warning"
            detail["reason"] = (
                f"Uzak LIMIT girişi: {distance_atr:.2f} ATR; beklemede tutulur, "
                "reddedilmez"
            )
            detail["warnings"].append(
                f"LIMIT entry is far: {distance_atr:.2f} ATR; kept pending"
            )
            return detail

        detail["passed"] = True
        detail["reason"] = (
            f"Giriş mesafesi kabul edilebilir: {distance_atr:.2f} ATR "
            f"({distance_pct:.2%})"
        )
        if distance_atr <= 0.5:
            detail["score_delta"] = 3
            detail["adjustments"].append({"delta": 3, "label": "Entry close to market"})
        return detail

    # ---------------------------------------------------------------- filter 4

    def _filter_stop_quality(self, *, direction, entry, risk, atr, entry_structure):
        """Stop kalitesi: swing yapısı ve invalidation seviyesine göre.

        Aşırı dar stop (< minimum ATR) ve anlamsız geniş stop (>
        QUALITY_MAX_STOP_ATR) engellenir.
        """
        detail = {
            "name": "Stop kalitesi",
            "passed": True,
            "severity": "none",
            "reason": "",
            "score_delta": 0,
            "critical_blockers": [],
            "adjustments": [],
            "warnings": [],
        }

        entry_price = self._safe_float(entry.get("entry"))
        stop = self._safe_float(risk.get("stop_loss", entry.get("stop_loss")))
        min_stop_atr = float(getattr(Config, "QUALITY_MIN_STOP_ATR", 0.25))
        max_stop_atr = float(getattr(Config, "QUALITY_MAX_STOP_ATR", 4.0))

        if entry_price is None or stop is None or atr <= 0:
            detail["passed"] = True
            detail["reason"] = "Stop/fiyat/ATR eksik; RiskEngine zaten doğrular"
            return detail

        if direction == "LONG" and not stop < entry_price:
            detail["passed"] = False
            detail["severity"] = "critical"
            detail["reason"] = "LONG stopu girişin üstünde (geçersiz yan)"
            detail["critical_blockers"].append("Stop-loss on wrong side of entry (LONG)")
            return detail
        if direction == "SHORT" and not stop > entry_price:
            detail["passed"] = False
            detail["severity"] = "critical"
            detail["reason"] = "SHORT stopu girişin altında (geçersiz yan)"
            detail["critical_blockers"].append("Stop-loss on wrong side of entry (SHORT)")
            return detail

        stop_atr = abs(entry_price - stop) / atr
        detail["stop_atr"] = round(stop_atr, 3)

        if stop_atr < min_stop_atr:
            detail["passed"] = False
            detail["severity"] = "critical"
            detail["reason"] = (
                f"Aşırı dar stop: {stop_atr:.2f} ATR < {min_stop_atr} ATR minimumu"
            )
            detail["critical_blockers"].append(
                f"Stop too tight: {stop_atr:.2f} ATR < {min_stop_atr}"
            )
            return detail

        if stop_atr > max_stop_atr:
            detail["passed"] = False
            detail["severity"] = "critical"
            detail["reason"] = (
                f"Anlamsız geniş stop: {stop_atr:.2f} ATR > {max_stop_atr} ATR sınırı"
            )
            detail["critical_blockers"].append(
                f"Stop too wide: {stop_atr:.2f} ATR > {max_stop_atr}"
            )
            return detail

        detail["passed"] = True
        detail["reason"] = f"Stop yapısal ve geçerli: {stop_atr:.2f} ATR"
        if min_stop_atr <= stop_atr <= 1.5:
            detail["score_delta"] = 3
            detail["adjustments"].append({"delta": 3, "label": "Well-sized structural stop"})
        return detail

    # ---------------------------------------------------------------- filter 5

    def _filter_tp_rr_consistency(
        self, *, direction, entry, risk, dynamic_tp, atr
    ):
        """TP/RR tutarlılığı: gerçek likidite hedefleri, komisyon+spread dahil net RR.

        Net RR (weighted_net_rr / execution_rr) kritik eşiğin altındaysa engel.
        Sentetik TP fallback'ı reddedilir.
        """
        detail = {
            "name": "TP/RR tutarlılığı",
            "passed": True,
            "severity": "none",
            "reason": "",
            "score_delta": 0,
            "critical_blockers": [],
            "adjustments": [],
            "warnings": [],
        }

        sources = dynamic_tp.get("sources") or []
        synthetic = bool(dynamic_tp.get("synthetic_targets"))

        tp1 = self._safe_float(dynamic_tp.get("tp1"))
        tp2 = self._safe_float(dynamic_tp.get("tp2"))
        tp3 = self._safe_float(dynamic_tp.get("tp3"))
        available_tps = [t for t in (tp1, tp2, tp3) if t is not None]

        entry_price = self._safe_float(entry.get("entry"))
        stop = self._safe_float(risk.get("stop_loss", entry.get("stop_loss")))

        weighted_net_rr = risk.get("weighted_net_rr")
        try:
            weighted_net_rr = float(weighted_net_rr) if weighted_net_rr is not None else None
        except (TypeError, ValueError, OverflowError):
            weighted_net_rr = None
        execution_rr = risk.get("execution_rr")
        try:
            execution_rr = float(execution_rr) if execution_rr is not None else None
        except (TypeError, ValueError, OverflowError):
            execution_rr = None
        net_rr = weighted_net_rr if weighted_net_rr is not None else execution_rr
        min_net_rr = float(getattr(Config, "MINIMUM_NET_RR", 2.0))
        min_tp1_rr = float(getattr(Config, "MIN_TP1_RR", 0.80))

        risk_distance = None
        if entry_price is not None and stop is not None:
            risk_distance = abs(entry_price - stop)

        direction_norm = str(direction or entry.get("direction") or "").upper()
        if direction_norm not in {"LONG", "SHORT"} and entry_price is not None and stop is not None:
            direction_norm = "LONG" if stop < entry_price else "SHORT"

        # Yön işaretli TP doğrulaması: mutlak değer, yanlış tarafta kalan bir
        # hedefi geçerli gösteremez. LONG: TP > Entry, SHORT: TP < Entry.
        tp_levels = (("tp1", tp1), ("tp2", tp2), ("tp3", tp3))
        wrong_side_tps = [
            name for name, value in tp_levels
            if value is not None and entry_price is not None and (
                (direction_norm == "LONG" and value <= entry_price)
                or (direction_norm == "SHORT" and value >= entry_price)
            )
        ]

        tp1_rr = None
        if risk_distance and risk_distance > 0 and tp1 is not None:
            tp1_rr = (
                (tp1 - entry_price) if direction_norm == "LONG" else (entry_price - tp1)
            ) / risk_distance

        reasons = []

        if bool(getattr(Config, "QUALITY_REJECT_SYNTHETIC_TP", True)) and synthetic:
            detail["passed"] = False
            detail["severity"] = "critical"
            detail["reason"] = "Sentetik TP fallback kullanıldı; gerçek likidite hedefi yok"
            detail["critical_blockers"].append("TP/RR: synthetic target (no real liquidity)")
            return detail

        if not sources or any(str(s).lower() != "market_structure" for s in sources):
            # Tüm kaynaklar market_structure değilse uyarı; kritik engelleme
            # gerçek hedef yoksa Filter5 zaten yukarıda yakalar. Burada hafifçe işaretle.
            if synthetic or not available_tps:
                pass
            else:
                reasons.append("Bazı TP kaynakları market_structure dışı")
                detail["warnings"].append("TP sources not all market_structure")

        if not available_tps:
            detail["passed"] = False
            detail["severity"] = "critical"
            detail["reason"] = "Geçerli yapısal TP hedefi yok"
            detail["critical_blockers"].append("TP/RR: no valid structural target")
            return detail

        if direction_norm not in {"LONG", "SHORT"}:
            detail["passed"] = False
            detail["severity"] = "critical"
            detail["reason"] = "TP/RR doğrulaması için yön belirlenemedi"
            detail["critical_blockers"].append("TP/RR: direction unresolved")
            return detail

        if entry_price is None or stop is None:
            detail["passed"] = False
            detail["severity"] = "critical"
            detail["reason"] = "TP/RR doğrulanamadı: entry veya stop yok"
            detail["critical_blockers"].append("TP/RR: missing entry or stop")
            return detail

        if tp1 is None:
            detail["passed"] = False
            detail["severity"] = "critical"
            detail["reason"] = "TP1 hedefi yok; TP/RR doğrulaması yapılamaz"
            detail["critical_blockers"].append("TP/RR: TP1 missing")
            return detail

        if wrong_side_tps:
            detail["passed"] = False
            detail["severity"] = "critical"
            detail["reason"] = (
                f"TP yanlış tarafta ({direction_norm}): {', '.join(wrong_side_tps)}"
            )
            detail["critical_blockers"].append(
                f"TP/RR: {'/'.join(wrong_side_tps)} on wrong side of entry ({direction_norm})"
            )
            return detail

        present_tps = [value for _, value in tp_levels if value is not None]
        ordered = all(
            (
                present_tps[index] < present_tps[index + 1]
                if direction_norm == "LONG"
                else present_tps[index] > present_tps[index + 1]
            )
            for index in range(len(present_tps) - 1)
        )
        if not ordered:
            detail["passed"] = False
            detail["severity"] = "critical"
            detail["reason"] = (
                f"TP sıralaması bozuk ({direction_norm}: TP1<TP2<TP3 beklenir)"
                if direction_norm == "LONG"
                else f"TP sıralaması bozuk ({direction_norm}: TP1>TP2>TP3 beklenir)"
            )
            detail["critical_blockers"].append("TP/RR: broken target ordering")
            return detail

        if tp1_rr is not None and tp1_rr < min_tp1_rr:
            detail["passed"] = False
            detail["severity"] = "critical"
            detail["reason"] = f"TP1 çok yakın: {tp1_rr:.2f}R < {min_tp1_rr}R"
            detail["critical_blockers"].append(
                f"TP/RR: TP1 {tp1_rr:.2f}R below minimum {min_tp1_rr}R"
            )
            return detail

        if net_rr is None:
            detail["passed"] = True
            detail["severity"] = "warning"
            detail["reason"] = "Net RR hesaplanamadı; brut RR göz önünde"
            detail["warnings"].append("Net RR unavailable after costs")
            return detail

        if net_rr < min_net_rr:
            detail["passed"] = False
            detail["severity"] = "critical"
            detail["reason"] = (
                f"Net RR (maliyet sonrası) çok düşük: {net_rr:.2f}R < {min_net_rr}R"
            )
            detail["critical_blockers"].append(
                f"TP/RR: net RR {net_rr:.2f} below minimum {min_net_rr} after costs"
            )
            return detail

        detail["passed"] = True
        detail["reason"] = (
            f"Net RR {net_rr:.2f}R (komisyon+spread sonrası) ≥ {min_net_rr}R; "
            f"TP1 {tp1_rr:.2f}R"
        )
        if net_rr >= 3.0:
            detail["score_delta"] = 5
            detail["adjustments"].append({"delta": 5, "label": "Strong net RR after costs"})
        elif net_rr >= 2.0:
            detail["score_delta"] = 3
            detail["adjustments"].append({"delta": 3, "label": "Adequate net RR after costs"})
        detail["net_rr"] = round(net_rr, 4)
        detail["tp1_rr"] = round(tp1_rr, 3) if tp1_rr is not None else None
        return detail

    # ---------------------------------------------------------------- filter 6

    def _filter_motor_conflict(
        self, *, direction, smt, cisd, volume_profile, institutional, unicorn
    ):
        """Motor çetelişi: güçlü bağımsız motorların yön çetelişi.

        Tek bir zayıf karşı sinyal işlemi ENGELLEMEZ. Yalnızca eşikteki veya
        üzeri güvetteki ve yönünde karşı olan motor sayısı
        QUALITY_MAX_STRONG_OPPOSING_MOTORS'ı aştığında engel olur.
        """
        detail = {
            "name": "Motor çetelişi",
            "passed": True,
            "severity": "none",
            "reason": "",
            "score_delta": 0,
            "critical_blockers": [],
            "adjustments": [],
            "warnings": [],
        }

        if direction not in {"LONG", "SHORT"}:
            detail["passed"] = True
            detail["reason"] = "Yön tanımlı değil; motor çetelişi değerlendirilmez"
            return detail

        confidence_threshold = float(getattr(Config, "QUALITY_MOTOR_CONFIDENCE_THRESHOLD", 75))
        max_opposing = int(getattr(Config, "QUALITY_MAX_STRONG_OPPOSING_MOTORS", 1))

        modules = (
            ("SMT", smt),
            ("CISD", cisd),
            ("Volume Profile", volume_profile),
            ("Institutional", institutional),
            ("Unicorn", unicorn),
        )

        strong_opposing = []
        weak_opposing = []
        aligned = []

        for label, module in modules:
            if not isinstance(module, dict) or not module.get("active"):
                continue
            try:
                confidence = float(module.get("confidence", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                confidence = 0.0
            module_direction = self._module_side(module)
            if module_direction not in {"LONG", "SHORT", "BULLISH", "BEARISH"}:
                continue
            if self._match_direction(module_direction, direction):
                aligned.append((label, confidence))
                continue
            if confidence >= confidence_threshold:
                strong_opposing.append((label, confidence))
            else:
                weak_opposing.append((label, confidence))

        detail["strong_opposing"] = strong_opposing
        detail["weak_opposing"] = weak_opposing
        detail["aligned"] = aligned

        if len(strong_opposing) > max_opposing:
            detail["passed"] = False
            detail["severity"] = "critical"
            names = ", ".join(f"{label}({conf:.0f})" for label, conf in strong_opposing)
            detail["reason"] = (
                f"{len(strong_opposing)} güçlü karşı motor: {names}; "
                "tek zayıf karşı sinyal engellemez ama bu seviyede çeteliş engeller"
            )
            detail["critical_blockers"].append(
                f"Motor conflict: {len(strong_opposing)} strong opposing motors ({names})"
            )
            return detail

        if strong_opposing:
            names = ", ".join(f"{label}({conf:.0f})" for label, conf in strong_opposing)
            detail["passed"] = True
            detail["severity"] = "warning"
            detail["reason"] = f"Tek güçlü karşı motor kabul edilir: {names}"
            detail["warnings"].append(f"Motor conflict: one strong opposing motor ({names})")
            return detail

        if weak_opposing:
            names = ", ".join(f"{label}({conf:.0f})" for label, conf in weak_opposing)
            detail["passed"] = True
            detail["severity"] = "none"
            detail["reason"] = f"Zayıf karşı motorlar engellemez: {names}"
            return detail

        detail["passed"] = True
        detail["reason"] = "Motor yönleri işlem yönüyle uyumlu veya nötr"
        return detail
