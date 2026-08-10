"""Adaptive learning layer based on closed trade performance.

LearningEngine, kapalı manuel (ve isteğe bağlı sinyal) işlemlerinden öğrenir ve
*yeni* setup'ların setup_quality skorunu bir META FACTOR olarak değiştirir.

Tasarım ilkeleri:
- Kanonik skema: setup özellikleri canonical_features içindeki tek isim setinden
  üretilir, böylece geçmiş record ile yeni setup'ın modülleri birebir eşleşir.
- Hierarchical lookup: EXACT -> SETUP_FAMILY -> DIRECTION+REGIME -> GLOBAL.
- Çoklu metrik: sample_count, win_rate, bayesian, wilson, average_R,
  expectancy, profit_factor, reliability(edg). Yüksek expectancy = daha güçlü.
- Min sample guard: az örnekte agresif öğrenme yapılmaz (ramp ile).
- Config sınırı: etki LEARNING_EDGE_UPLIFT_MAX / PENALTY_MAX ile tavanlanır.
- Look-ahead korumaz: record'lar yalnızca kapandıkları zamanın öncesinden
  sorulabilir (as_of_ms).
"""

import json
import math
from pathlib import Path

from canonical_features import (
    CANONICAL_MODULES,
    build_fingerprint,
    fingerprint_features,
    normalize_features,
    parse_fingerprint,
)


class LearningEngine:
    def __init__(self, path="atlas_learning.json"):
        self.path = Path(path)
        self.stats = {"setups": {}, "index": {}, "meta": {}}
        self.load()

    def load(self):
        if not self.path.exists():
            return self.stats
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                self.stats.update(payload)
                self.stats.setdefault("setups", {})
                self.stats.setdefault("index", {})
        except (OSError, json.JSONDecodeError):
            pass
        # Eski/üçüncü parti dosyalarda 'index' yoksa (legacy bucket-only format)
        # mevcut setups bucket'larından hiyerarşik index re-build edilir. Böylece
        # yalnızca dosyayı okuyan her process matching yapabilir; production'da
        # refresh_learning() journal'dan daha doğru index kurar.
        self._ensure_index_from_setups()
        return self.stats

    # ------------------------------------------------------------------
    # Index migrasyonu (legacy 'setups' -> hiyerarşik 'index')
    # ------------------------------------------------------------------

    def _ensure_index_from_setups(self):
        """'index' boş ama 'setups' doluysa legacy bucket'lardan index kurar.

        Legacy anahtar formatları parse edilir:
          - Yeni:  SHORT|EXPANSION|15M|feat|feat   (direction önde)
          - Eski:  Expansion|15m|LONG|fvg|ob       (regime/tf önde)
        Elimizdeki alanlar sınırlı olduğundan yaklaşık raw sayaçlar kurulur;
        asıl kesin index her zaman journal kayıtlarından rebuild edilir.
        """
        if not self.stats.get("setups") or self.stats.get("index"):
            return self.stats
        index = {"exact": {}, "family": {}, "global": {}}
        for setup, bucket in self.stats["setups"].items():
            ctx = self._legacy_bucket_context(setup)
            if ctx is None:
                continue
            raw = self._empty_raw()
            total = int(bucket.get("total", 0))
            wins = int(bucket.get("wins", 0))
            mean_r = float(bucket.get("average_r") or bucket.get("edge") or 0)
            raw["total"] = total
            raw["wins"] = wins
            raw["r_sum"] = mean_r * total
            raw["pos_sum"] = abs(raw["r_sum"]) if raw["r_sum"] >= 0 else 0.0
            raw["neg_sum"] = raw["r_sum"] if raw["r_sum"] < 0 else 0.0
            raw["confidence_sum"] = float(bucket.get("average_confidence", 0) or 0) * total
            raw["decay_sum"] = float(bucket.get("weight", 1.0) or 1.0) * total
            raw["decay_wins"] = wins
            metrics = self._compute_metrics(raw, counts=total)
            for level, key in self._candidate_keys(ctx):
                index[level][key] = metrics
        self.stats["index"] = index
        return self.stats

    def _legacy_bucket_context(self, setup):
        """Setup anahtarını context dict'e çevirir; parse edilemezse None."""
        if not isinstance(setup, str):
            return None
        parts = [part.strip() for part in setup.split("|") if part.strip()]
        if not parts:
            return None
        upper = [part.upper() for part in parts]
        direction = None
        if upper[0] in ("LONG", "SHORT", "NONE", "UNKNOWN"):
            direction = upper[0]
            remainder = parts[1:]
        elif len(upper) >= 3 and upper[2] in ("LONG", "SHORT", "NONE", "UNKNOWN"):
            direction = upper[2]
            remainder = parts[:2] + parts[3:]
        else:
            direction = "UNKNOWN"
            remainder = parts
        if len(remainder) >= 2:
            regime, timeframe = remainder[0].upper(), remainder[1].upper()
            feature_tokens = remainder[2:]
        else:
            regime = remainder[0].upper() if remainder else "UNKNOWN"
            timeframe = "UNKNOWN"
            feature_tokens = []
        normalized = normalize_features(feature_tokens)
        return {
            "direction": direction,
            "regime": regime,
            "timeframe": timeframe,
            "feature_key": "|".join(normalized) or "UNKNOWN",
        }

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self.stats, handle, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # Besleme (backward-compatible popülasyon)
    # ------------------------------------------------------------------

    def record_closed_trade(self, trade):
        """Tek kapanan işlemi setups bucket'ına işler (legacy/engine yolu)."""
        setup = self._setup_key(trade)
        bucket = self.stats.setdefault("setups", {}).setdefault(setup, self._empty_bucket())
        bucket["total"] += 1
        result = trade.get("result")
        if result == "WIN":
            bucket["wins"] += 1
        elif result in ("LOSS",):
            bucket["losses"] = bucket.get("losses", 0) + 1
        bucket["confidence_sum"] += float(trade.get("confidence") or 0)
        grade = str(trade.get("grade") or "UNKNOWN")
        bucket.setdefault("grade_counts", {})
        bucket["grade_counts"][grade] = bucket["grade_counts"].get(grade, 0) + 1
        bucket["last_reason"] = trade.get("close_reason") or trade.get("result")
        bucket["weight"] = self._weight(bucket)
        self.save()
        return bucket

    def rebuild_from_records(self, records):
        """learning_records() akışını çok seviyeli öğrenme istatistiklerine işler.

        Dört hiyerarşi katmanı oluşur (index):
          - exact:          regime|timeframe|direction|features
          - family:         direction|features            (regime/tf soyut)
          - direction_regime: direction|regime
          - global:         'ALL'
        Return değerleri eski testlerle uyumlu 'setups' tablosudur.
        """
        from config import Config

        half_life_days = float(getattr(Config, "LEARNING_HALF_LIFE_DAYS", 45) or 0)
        alpha = float(getattr(Config, "LEARNING_BETA_PRIOR_ALPHA", 2.0))
        beta = float(getattr(Config, "LEARNING_BETA_PRIOR_BETA", 2.0))
        min_samples = int(getattr(Config, "LEARNING_MIN_SAMPLES", 20))

        # Katmanlı ham sayaçlar.
        raw = {
            "exact": {},
            "family": {},
            "global": {},
        }

        for record in records:
            direction = str(record.get("direction") or "UNKNOWN").upper()
            regime = str(record.get("regime") or "UNKNOWN").upper()
            timeframe = str(record.get("timeframe") or "UNKNOWN").upper()
            features = fingerprint_features(record)
            feature_key = "|".join(normalize_features(features)) or "UNKNOWN"
            r_value = float(record.get("r") or 0.0)
            confidence = float(record.get("confidence") or 0)
            win = bool(record.get("win"))

            weight = 1.0
            if half_life_days > 0:
                closed_at = int(record.get("closed_at") or 0)
                age_days = max(0.0, (self._now_ms() - closed_at) / 86_400_000.0)
                weight = 0.5 ** (age_days / half_life_days)

            ctx = {
                "direction": direction,
                "regime": regime,
                "timeframe": timeframe,
                "feature_key": feature_key,
            }
            for level, key in self._candidate_keys(ctx):
                entry = raw[level].setdefault(key, self._empty_raw())
                entry["total"] += 1
                entry["wins"] += 1 if win else 0
                entry["r_sum"] += r_value
                if r_value > 0:
                    entry["pos_sum"] += r_value
                elif r_value < 0:
                    entry["neg_sum"] += r_value
                entry["confidence_sum"] += confidence
                entry["decay_sum"] += weight
                if win:
                    entry["decay_wins"] += weight

        setups = {}
        for level in raw:
            for key, accum in raw[level].items():
                setups[key] = self._compute_metrics(accum, counts=accum["total"], alpha=alpha, beta=beta)

        index = {}
        for level in raw:
            index[level] = {
                key: self._compute_metrics(accum, counts=accum["total"], alpha=alpha, beta=beta)
                for key, accum in raw[level].items()
            }

        self.stats["setups"] = setups
        self.stats["index"] = index
        self.stats["meta"] = {
            "records_fed": len(records),
            "buckets": len(setups),
            "half_life_days": half_life_days,
            "min_samples": min_samples,
            "levels": list(index.keys()),
        }
        self.save()
        return setups

    # ------------------------------------------------------------------
    # Query / Matching
    # ------------------------------------------------------------------

    def _match_context(self, setup_quality, market_phase=None, timeframe=None):
        """setup_quality + opsiyonel bağlam -> sorgu anahtarları."""
        direction = str((setup_quality or {}).get("direction") or "UNKNOWN").upper()
        module_scores = (setup_quality or {}).get("module_scores") or {}
        features = set(fingerprint_features(setup_quality or {}))
        if not features:
            features = set(
                normalize_features(
                    name for name, item in module_scores.items()
                    if item.get("score", 0) >= 50
                )
            )
        feature_key = "|".join(sorted(features)) or "UNKNOWN"
        if market_phase and isinstance(market_phase, dict):
            regime = str(market_phase.get("phase") or "UNKNOWN")
        elif isinstance(market_phase, str) and market_phase:
            regime = market_phase
        else:
            regime = "UNKNOWN"
        timeframe = str(timeframe or "UNKNOWN")
        return {
            "direction": direction,
            "regime": regime.upper(),
            "timeframe": timeframe.upper(),
            "feature_key": feature_key,
            "features": features,
        }

    def _candidate_keys(self, ctx):
        """Sorgu bağlamından hiyerarşik candidate anahtarlarını üretir.

        Bayraklar (LEARNING_USE_MARKET_REGIME / _USE_TIMEFRAME / _USE_DIRECTION)
        hangi boyutların bucket'a dahil olduğunu belirler.

        Fallback sırası:
          exact           -> dir|regime|tf|features   (en spesifik)
          family          -> dir|regime|tf           (features serbest)
          global          -> "GLOBAL" (yalnızca LEARNING_GLOBAL_FALLBACK açıkken)
        Fallback sırası:
          exact           -> dir|regime|tf|features   (en spesifik)
          family          -> dir|regime|tf           (features serbest)
          global          -> "GLOBAL" (yalnızca LEARNING_GLOBAL_FALLBACK açıkken)
        Direction/regime/timeframe ANLAŞMALARI her zaman korunur; böylece bir
        direction/regime/tf geçmişi başka direction/regime/tf'ye *körü körüne*
        aynı etkiyi taşımaz (izolasyon).
        """
        from config import Config

        use_regime = bool(getattr(Config, "LEARNING_USE_MARKET_REGIME", True))
        use_tf = bool(getattr(Config, "LEARNING_USE_TIMEFRAME", True))
        use_dir = bool(getattr(Config, "LEARNING_USE_DIRECTION", True))

        base = []
        if use_dir:
            base.append(ctx["direction"])
        if use_regime:
            base.append(ctx["regime"])
        if use_tf:
            base.append(ctx["timeframe"])

        def join(parts):
            return "|".join(p for p in parts if p) or "GLOBAL"

        exact = join(list(base) + [ctx["feature_key"]])
        family = join(list(base))
        return [
            ("exact", exact),
            ("family", family),
            ("global", "GLOBAL"),
        ]

    def _global_enabled(self):
        from config import Config
        return bool(getattr(Config, "LEARNING_GLOBAL_FALLBACK", True))

    def _match(self, setup_quality, market_phase=None, timeframe=None):
        """Hierarchical fallback ile en iyi eşleşen öğrenme kaydını döner.

        Sıra: exact -> family -> direction_regime -> global. Örneklem yeterliyse
        en spesifik seviye döner; yoksa bir altını dener. Return: {'level',
        'key', 'metrics'} veya None.
        """
        from config import Config

        ctx = self._match_context(setup_quality, market_phase, timeframe)
        index = self.stats.get("index", {})
        min_samples = int(getattr(Config, "LEARNING_MIN_SAMPLES", 20))

        matched = None
        for level, key in self._candidate_keys(ctx):
            if level == "global" and not self._global_enabled():
                continue
            bucket = (index.get(level) or {}).get(key)
            if not bucket:
                continue
            total = bucket.get("total", 0)
            if total <= 0:
                continue
            matched = {"level": level, "key": key, "metrics": bucket}
            if total >= min_samples:
                return matched
        return matched

    def adjustments_for(self, setup_quality, market_phase=None, timeframe=None):
        """Her kanonik modül için öğrenilmiş çarpan (1.0=tarafsız)."""
        match = self._match(setup_quality, market_phase, timeframe)
        adjustments = {name: 1.0 for name in CANONICAL_MODULES}
        if not match:
            return adjustments
        delta_points = self._edge_delta(match["metrics"])
        factor = 1.0 + delta_points / 100.0
        feature_set = self._match_context(setup_quality, market_phase, timeframe)["features"]
        for name in feature_set:
            if name in adjustments:
                adjustments[name] = round(factor, 4)
        return adjustments

    def apply_to_setup_quality(self, setup_quality, market_phase=None, timeframe=None):
        """Öğrenilen veri ile yeni setup skorunu (META FACTOR) günceller.

        Eşleşme varsa ve örneklem güvenilirse skoru tarihsel ucu kadar
        yükseltir/ düşürür; config sınırları içinde. Eşleşme yoksa skor değişmez
        (saf 'reaggregation' artefaktını üretmez).
        """
        if not setup_quality or not setup_quality.get("module_scores"):
            return setup_quality
        adjusted = dict(setup_quality)
        module_scores = {k: dict(v) for k, v in setup_quality.get("module_scores", {}).items()}
        ctx = self._match_context(setup_quality, market_phase, timeframe)
        match = self._match(setup_quality, market_phase, timeframe)

        if not match:
            adjusted["module_scores"] = module_scores
            adjusted["learning_adjustments"] = {name: 1.0 for name in CANONICAL_MODULES}
            adjusted["learning"] = {
                "matched": False,
                "level": None,
                "score_delta": 0,
                "sample_count": 0,
                "historical_edge": 0.0,
                "reliability": 0.0,
                "expected_r": 0.0,
                "edge_score": 0.0,
                "no_match_reason": self._no_match_reason(ctx),
            }
            return adjusted

        metrics = match["metrics"]
        base_score = int(setup_quality.get("score") or 0)
        delta = self._edge_delta(metrics)
        new_score = max(0, min(100, base_score + delta))

        weights = {name: 1.0 for name in CANONICAL_MODULES}
        for name in ctx["features"]:
            if name in weights:
                weights[name] = round(1.0 + delta / 100.0, 4)
        for name, payload in module_scores.items():
            payload["learned_weight"] = weights.get(name, 1.0)

        reliability = float(metrics.get("reliability", 0) or 0)
        expected_r = float(metrics.get("average_r", 0) or 0)
        sample_count = int(metrics.get("total", 0) or 0)
        edge_score = round(self._edge_score(metrics), 4)

        adjusted["module_scores"] = module_scores
        adjusted["score"] = new_score
        adjusted["confidence"] = new_score
        if setup_quality.get("trade_allowed") is not None:
            adjusted["trade_allowed"] = bool(setup_quality.get("trade_allowed")) and new_score >= 58
        adjusted["learning_adjustments"] = weights
        adjusted["learning"] = {
            "matched": True,
            "level": match["level"],
            "sample_count": sample_count,
            "historical_edge": expected_r,
            "reliability": reliability,
            "expected_r": expected_r,
            "score_delta": delta,
            "edge_score": edge_score,
        }
        return adjusted

    def _no_match_reason(self, ctx):
        """matched=False'in nedenini net biçimde raporlar."""
        index = self.stats.get("index", {})
        if not any(index.get(level) for level in ("exact", "family", "global")):
            return "learning index yok (index bos)"
        if self.stats.get("meta", {}).get("records_fed", 0) <= 0:
            return "kapanmis trade kaydi yok"
        feature_key = ctx.get("feature_key") or "UNKNOWN"
        regime = ctx.get("regime") or "UNKNOWN"
        tf = ctx.get("timeframe") or "UNKNOWN"
        direction = ctx.get("direction") or "UNKNOWN"
        return (
            f"hierarjide eslesen bucket yok (dir={direction} regime={regime} "
            f"tf={tf} features={feature_key})"
        )

    def setup_success_rates(self):
        output = {}
        for setup, bucket in self.stats.get("setups", {}).items():
            total = bucket.get("total", 0)
            output[setup] = {
                "total": total,
                "winrate": round(bucket.get("wins", 0) / total * 100, 2) if total else 0,
                "weight": bucket.get("weight", 1.0),
            }
        return output

    def edge_summary(self):
        """Meta katmanın genel görünümü (skor ayarlama önerileri ile)."""
        from config import Config

        strong_negative = float(getattr(Config, "LEARNING_STRONG_NEGATIVE_EDGE", -0.20))
        confidence_floor = float(getattr(Config, "LEARNING_EDGE_CONFIDENCE_FLOOR", 65))
        setups = self.stats.get("setups", {})
        summary = {"setups": {}, "suggestions": []}
        for key, bucket in setups.items():
            summary["setups"][key] = bucket
            if bucket.get("total", 0) < 5:
                continue
            edge = float(bucket.get("average_r", 0) or bucket.get("edge", 0) or 0)
            wilson = float(bucket.get("wilson_lower", 0) or 0)
            bayesian = float(bucket.get("bayesian", 50) or 50)
            avg_confidence = float(bucket.get("average_confidence", 0) or 0)
            if bayesian >= 55 and wilson > 0 and avg_confidence >= confidence_floor:
                summary["suggestions"].append({"setup": key, "action": "BOOST", "edge": edge, "confidence": avg_confidence})
            elif edge <= strong_negative:
                summary["suggestions"].append({"setup": key, "action": "WAIT", "edge": edge})
            elif bayesian <= 40:
                summary["suggestions"].append({"setup": key, "action": "WAIT", "edge": edge})
        return summary

    # ------------------------------------------------------------------
    # Metrikler
    # ------------------------------------------------------------------

    def _compute_metrics(self, raw, counts=None, alpha=2.0, beta=2.0):
        total = int(raw["total"])
        if raw.get("decay_sum"):
            winrate = raw.get("decay_wins", 0) / raw["decay_sum"]
        else:
            winrate = raw["wins"] / total if total else 0.0
        bayesian = (alpha + raw["wins"]) / (alpha + beta + total)
        wilson = self._wilson_lower(winrate, total)
        mean_r = raw["r_sum"] / total if total else 0.0
        avg_confidence = raw["confidence_sum"] / total if total else 0.0
        losses = total - raw["wins"]
        neg_r = abs(raw["neg_sum"])
        profit_factor = raw["pos_sum"] / neg_r if neg_r > 0 else (raw["pos_sum"] if raw["pos_sum"] > 0 else 0.0)
        return {
            "total": total,
            "wins": raw["wins"],
            "losses": losses,
            "winrate": round(winrate * 100, 2),
            "bayesian": round(bayesian * 100, 2),
            "wilson_lower": round(wilson * 100, 2),
            "average_r": round(mean_r, 4),
            "average_confidence": round(avg_confidence, 2),
            "expectancy": round(mean_r, 4),
            "profit_factor": round(profit_factor, 4),
            "reliability": round(bayesian, 4),
            "weight": self._meta_weight(bayesian, total),
        }

    def _empty_raw(self):
        return {
            "total": 0,
            "wins": 0,
            "r_sum": 0.0,
            "pos_sum": 0.0,
            "neg_sum": 0.0,
            "confidence_sum": 0.0,
            "decay_sum": 0.0,
            "decay_wins": 0.0,
        }

    def _edge_score(self, metrics):
        """Reliability ile dengeli ham edge skoru (mean R * reliability)."""
        mean_r = float(metrics.get("average_r", 0) or 0)
        reliability = float(metrics.get("reliability", 0) or 0)
        return mean_r * reliability

    def _edge_delta(self, metrics):
        """Skoru değiştiren (bound) delta puan.

        Sign: mean R decide ediyor; büyüklük |mean R| * scale ile sınırlanır,
        ramp ise örneklem yetersizliğinde etkiyi azaltır. Safe: yanlışlıkla
        agresif ceza değil, config tavanı ile kesilir.
        """
        from config import Config

        uplift_max = float(getattr(Config, "LEARNING_EDGE_UPLIFT_MAX", 6))
        penalty_max = float(getattr(Config, "LEARNING_EDGE_PENALTY_MAX", 10))
        scale = float(getattr(Config, "LEARNING_EDGE_SCALE", 3.0))
        min_samples = int(getattr(Config, "LEARNING_MIN_SAMPLES", 20))
        mean_r = float(metrics.get("average_r", 0) or 0)
        ramp = min(1.0, float(metrics.get("total", 0) or 0) / max(min_samples, 1))
        raw = mean_r * scale * ramp
        if raw >= 0:
            return int(max(0, min(uplift_max, raw)))
        return int(-min(penalty_max, -raw))

    def _meta_weight(self, bayesian, total):
        from config import Config

        min_samples = int(getattr(Config, "LEARNING_MIN_SAMPLES", 20))
        min_reliability = float(getattr(Config, "LEARNING_MIN_RELIABILITY", 0.55))
        uplift_max = float(getattr(Config, "LEARNING_EDGE_UPLIFT_MAX", 6))
        penalty_max = float(getattr(Config, "LEARNING_EDGE_PENALTY_MAX", 10))
        if total < min_samples:
            return 1.0
        if bayesian >= min_reliability:
            scale = max(0.0, (bayesian - min_reliability) / (1.0 - min_reliability))
            return 1.0 + scale * (uplift_max / 100.0)
        scale = max(0.0, (min_reliability - bayesian) / min_reliability)
        return 1.0 - scale * (penalty_max / 100.0)

    def _wilson_lower(self, winrate, n, z=1.96):
        if n == 0:
            return 0.0
        p = max(0.0, min(1.0, winrate))
        denom = 1 + z * z / n
        center = p + z * z / (2 * n)
        margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
        return max(0.0, (center - margin) / denom)

    def _now_ms(self):
        import time
        return int(time.time() * 1000)

    def _setup_key(self, trade):
        metadata = trade.get("metadata") or {}
        return metadata.get("setup_type") or trade.get("setup_type") or trade.get("side") or "UNKNOWN"

    def _empty_bucket(self):
        return {"total": 0, "losses": 0, "wins": 0, "confidence_sum": 0.0, "grade_counts": {}, "weight": 1.0}

    def _weight(self, bucket):
        total = bucket.get("total", 0)
        if total < 5:
            return 1.0
        winrate = bucket.get("wins", 0) / total
        if winrate >= 0.62:
            return 1.12
        if winrate <= 0.42:
            return 0.88
        return 1.0

    # Backward-compat: eski bucket_key söz dizimi. (Kullanım dışı ama birebir tutulur.)
    def bucket_key(self, record, *, use_regime, use_timeframe, use_direction):
        parts = []
        if use_regime:
            parts.append(record.get("regime"))
        if use_timeframe:
            parts.append(record.get("timeframe"))
        if use_direction:
            parts.append(record.get("direction"))
        parts.append(record.get("setup_fingerprint"))
        return "|".join(p for p in parts if p)

    def _bucket_key(self, record):
        from config import Config

        use_regime = bool(getattr(Config, "LEARNING_USE_MARKET_REGIME", True))
        use_timeframe = bool(getattr(Config, "LEARNING_USE_TIMEFRAME", True))
        use_direction = bool(getattr(Config, "LEARNING_USE_DIRECTION", True))
        key = self.bucket_key(record, use_regime=use_regime, use_timeframe=use_timeframe, use_direction=use_direction)
        setup = record.get("setup_fingerprint") or record.get("setup_type") or "UNKNOWN"
        return key or setup