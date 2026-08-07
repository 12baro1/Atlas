"""
engine.py
Atlas SMC Engine v3

Ana orkestrasyon katmanı: alt motorları modüler bir akışta birleştirir.
Kod İngilizce, açıklamalar Türkçe tutulmuştur.
"""

from importlib import import_module
import logging
import threading
import time

from backtest_engine import BacktestEngine
from bos_engine import BOSEngine
from breaker_block_engine import BreakerBlockEngine
from choch_engine import CHOCHEngine
from config import Config
from confluence_engine import ConfluenceEngine
from trade_cooldown_engine import TradeCooldownEngine
from state_engine import StateEngine
from learning_engine import LearningEngine
from economic_news_engine import EconomicNewsFilter
from correlation_engine import CorrelationEngine
from core.market_structure_engine import MarketStructureEngine
from cisd_engine import CISDEngine
from decision_engine import DecisionEngine
from dynamic_tp_engine import DynamicTPEngine
from entry_confirmation_engine import EntryConfirmationEngine
from entry_engine import EntryEngine
from fvg_engine import FVGEngine
from htf_fvg_engine import HTFFVGEngine
from htf_orderblock_engine import HTFOrderBlockEngine
from killzone_engine import KillZoneEngine
from liquidity_engine import LiquidityEngine
from liquidity_sweep_engine import LiquiditySweepEngine
from institutional_engine import InstitutionalAnalysisEngine
from market_phase_engine import MarketPhaseEngine
from manual_trade_quality import ManualTradeQualityGate
from mitigation_engine import MitigationEngine
from mtf_engine import MTFEngine
from orderblock_engine import OrderBlockEngine
from ote_engine import OTEEngine
from position_manager import PositionManager
from premium_discount_engine import PremiumDiscountEngine
from risk_engine import RiskEngine
from rr_engine import RREngine
from scanner_engine import ScannerEngine
from session_filter import SessionFilter
from signal_engine import SignalEngine
from setup_quality_engine import SetupQualityEngine
from smt_engine import SMTDivergenceEngine
from statistics_engine import StatisticsEngine
from trade_manager import TradeManager
from trade_journal import TradeJournal
from trend_engine import TrendEngine
from trendline_engine import TrendlineEngine
from unicorn_engine import UnicornEngine
from volume_profile_engine import VolumeProfileEngine
from utils.structure_labels import label_swings


class AtlasEngine:
    """Atlas'ın tüm analiz motorlarını yöneten ana sınıf."""

    REQUIRED_TIMEFRAMES = ("1w", "1d", "4h", "15m")
    SWEEP_TIMEFRAMES = ("15m", "1h", "4h", "1d")
    SMT_TIMEFRAMES = ("15m", "1h", "4h", "1d")
    UNICORN_TIMEFRAMES = ("15m", "1h", "4h", "1d")
    CISD_TIMEFRAMES = ("15m", "1h", "4h", "1d")
    VOLUME_PROFILE_TIMEFRAMES = ("15m", "1h", "4h", "1d")

    def __init__(self, structure_engine_cls=None):
        Config.refresh_from_env()
        # Testlerde sahte sınıf enjekte edebilmek için sınıf referansı tutulur.
        self.structure_engine_cls = structure_engine_cls or MarketStructureEngine
        self.logger = logging.getLogger("atlas.engine")

        # Structure ve seviye motorları
        self.bos = BOSEngine()
        self.choch = CHOCHEngine()
        self.liquidity = LiquidityEngine()
        self.orderblocks = OrderBlockEngine()
        self.mitigation = MitigationEngine()
        self.fvg = FVGEngine()
        self.liquidity_sweep = LiquiditySweepEngine()
        self.breaker = BreakerBlockEngine()
        self.trendline = TrendlineEngine()

        # Faz, bağlam ve MTF motorları
        self.trend = TrendEngine()
        self.market_phase = MarketPhaseEngine()
        self.mtf = MTFEngine()
        self.premium_discount = PremiumDiscountEngine()
        self.killzone = KillZoneEngine()
        self.session = SessionFilter()
        self.ote = OTEEngine()
        self.htf_orderblock = HTFOrderBlockEngine()
        self.htf_fvg = HTFFVGEngine()
        self.smt = SMTDivergenceEngine()
        self.unicorn = UnicornEngine()
        self.cisd = CISDEngine()
        self.volume_profile = VolumeProfileEngine()
        self.institutional = InstitutionalAnalysisEngine()
        self.decision = DecisionEngine()
        self.setup_quality = SetupQualityEngine()
        self.state_engine = StateEngine(getattr(Config, "STATE_ENGINE_FILE", "atlas_state.json"))
        self.news_filter = EconomicNewsFilter()
        self.correlation = CorrelationEngine()
        self.cooldown = TradeCooldownEngine()
        self.learning = LearningEngine(getattr(Config, "LEARNING_ENGINE_FILE", "atlas_learning.json"))
        self.manual_quality_gate = ManualTradeQualityGate(Config)

        # Sinyal, risk ve operasyon motorları
        self.entry = EntryEngine()
        self.entry_confirmation = EntryConfirmationEngine()
        self.confluence = ConfluenceEngine()
        self.signal = SignalEngine()
        self.risk = RiskEngine()
        self.rr = RREngine()
        self.dynamic_tp = DynamicTPEngine()
        self.telegram = None
        self._telegram_signal_cache = {}
        self._telegram_threads = []

        # Dış API uyumluluğu için korunur
        self.config = Config()
        self.position = PositionManager()
        self.position.positions.extend(self.state_engine.load_open_positions())
        self.trade = TradeManager()
        self.trade_journal = TradeJournal(
            db_path=getattr(Config, "TRADE_JOURNAL_DB_FILE", None) if getattr(Config, "SIGNAL_TRACKING_ENABLED", True) else None
        )
        self.scanner = ScannerEngine()
        self.statistics = StatisticsEngine()
        self.backtest = BacktestEngine()

    def analyze(self, data):
        """Çoklu zaman dilimi verisini analiz eder ve birleşik çıktı üretir."""
        self._validate_market_data(data)

        symbol = data.get("symbol", "UNKNOWN")
        candles = data["15m"]
        if bool(getattr(Config, "STATE_ENGINE_ENABLED", True)) and bool(getattr(Config, "INCREMENTAL_ANALYSIS_ENABLED", True)):
            cached = self._restore_incremental_if_unchanged(symbol, candles)
            if cached is not None:
                cached_analysis = cached.get("analysis") if isinstance(cached, dict) else None
                if isinstance(cached, dict):
                    cached.setdefault("symbol", symbol)
                if cached_analysis:
                    cached_analysis.setdefault("symbol", symbol)
                    cached["journal"] = self.trade_journal.record_analysis(
                        analysis=cached_analysis,
                        symbol=symbol,
                        timeframe="multi",
                        metadata={
                            "decision": (cached.get("decision") or {}).get("action"),
                            "signal": (cached.get("signal") or {}).get("signal"),
                            "confidence": (cached.get("signal") or {}).get("confidence", 0),
                            "source": "incremental_cache",
                        },
                    )
                return cached
            data = self._trim_incremental_data(symbol, data)
            candles = data["15m"]
        h1 = data.get("1h") or data.get("1H")
        weekly = data["1w"]
        daily = data["1d"]
        h4 = data["4h"]

        tf_analysis = {
            "entry": self._analyze_timeframe(candles),
            "weekly": self._analyze_timeframe(weekly),
            "daily": self._analyze_timeframe(daily),
            "h4": self._analyze_timeframe(h4),
            "h1": self._analyze_timeframe(h1) if h1 else {"pivots": [], "structure": []},
        }

        smt_state = self._build_smt_state(data)

        structure_state = self._build_structure_state(
            candles=candles,
            structure=tf_analysis["entry"]["structure"],
            timeframe_data={
                "15m": {
                    "candles": candles,
                    "structure": tf_analysis["entry"]["structure"],
                },
                "1h": {
                    "candles": h1 or [],
                    "structure": tf_analysis["h1"]["structure"],
                },
                "4h": {
                    "candles": h4,
                    "structure": tf_analysis["h4"]["structure"],
                },
                "1d": {
                    "candles": daily,
                    "structure": tf_analysis["daily"]["structure"],
                },
            },
        )

        context_state = self._build_context_state(
            candles=candles,
            daily=daily,
            h4=h4,
            weekly_structure=tf_analysis["weekly"]["structure"],
            daily_structure=tf_analysis["daily"]["structure"],
            h4_structure=tf_analysis["h4"]["structure"],
            entry_structure=structure_state["structure"],
            liquidity=structure_state["liquidity"],
            fvg=structure_state["fvg"],
            orderblocks=structure_state["orderblocks"],
            liquidity_sweep=structure_state["liquidity_sweep"],
            breakers=structure_state["breaker"],
        )

        unicorn_state = self._build_unicorn_state(
            data=data,
            tf_analysis=tf_analysis,
            context_state=context_state,
            structure_state=structure_state,
            smt_state=smt_state,
        )

        cisd_state = self._build_cisd_state(
            data=data,
            tf_analysis=tf_analysis,
            context_state=context_state,
            smt_state=smt_state,
        )

        volume_profile_state = self._build_volume_profile_state(data)
        institutional_state = self._build_institutional_state(
            data=data,
            context_state=context_state,
            structure_state=structure_state,
            volume_profile_state=volume_profile_state,
            smt_state=smt_state,
            unicorn_state=unicorn_state,
            cisd_state=cisd_state,
        )
        news_state = self.news_filter.evaluate(
            timestamp_ms=candles[-1].time,
            events=data.get("economic_events"),
        ) if bool(getattr(Config, "ECONOMIC_NEWS_FILTER_ENABLED", True)) else {"active": False, "trade_allowed": True}
        correlation_state = self.correlation.evaluate(
            symbol=data.get("symbol", "UNKNOWN"),
            direction=context_state["mtf"].get("entry", "WAIT"),
            data=data,
        ) if bool(getattr(Config, "CORRELATION_ENGINE_ENABLED", True)) else {"active": False, "trade_allowed": True}
        cooldown_state = self.cooldown.evaluate(
            symbol=data.get("symbol", "UNKNOWN"),
            direction=context_state["mtf"].get("entry", "WAIT"),
            open_positions=self.position.open_positions(),
        )

        execution_state = self._build_execution_state(
            candles=candles,
            entry_structure=structure_state["structure"],
            mtf=context_state["mtf"],
            trend=context_state["trend"],
            fvg=structure_state["fvg"],
            orderblocks=structure_state["orderblocks"],
            premium_discount=context_state["premium_discount"],
            liquidity_sweep=structure_state["liquidity_sweep"],
            breaker=structure_state["breaker"],
            ote=context_state["ote"],
            htf_orderblock=context_state["htf_orderblock"],
            htf_fvg=context_state["htf_fvg"],
            killzone=context_state["killzone"],
            session=context_state["session"],
            market_phase=context_state["market_phase"],
            liquidity=structure_state["liquidity"],
            smt=smt_state,
            unicorn=unicorn_state,
            cisd=cisd_state,
            volume_profile=volume_profile_state,
            institutional=institutional_state,
            news_filter=news_state,
            correlation=correlation_state,
            cooldown=cooldown_state,
            trendline_sweep=structure_state.get("trendline_sweep"),
            ifvg=structure_state.get("ifvg"),
            eqh_eql=structure_state.get("eqh_eql"),
            internal_structure=structure_state.get("internal_structure"),
        )

        decision_state = self.decision.decide(
            signal=execution_state["signal"],
            confluence=execution_state["confluence"],
            entry=execution_state["entry"],
            risk=execution_state["risk"],
            mtf=context_state.get("mtf"),
            ote=context_state.get("ote"),
            htf_orderblock=context_state.get("htf_orderblock"),
            liquidity_sweep=structure_state.get("liquidity_sweep"),
            market_phase=context_state.get("market_phase"),
            cisd=cisd_state,
            volume_profile=volume_profile_state,
            institutional=institutional_state,
            unicorn=unicorn_state,
            smt=smt_state,
            news_filter=news_state,
            correlation=correlation_state,
            cooldown=cooldown_state,
        )

        decision_state = self._apply_external_risk_filters(
            decision=decision_state,
            news_filter=news_state,
            correlation=correlation_state,
            cooldown=cooldown_state,
        )

        execution_state["signal"] = self._apply_decision_to_signal(
            signal=execution_state["signal"],
            decision=decision_state,
        )
        if execution_state["signal"].get("gated_by_decision"):
            self.logger.info(
                "Signal gated by decision | symbol=%s action=%s",
                data.get("symbol", "UNKNOWN"),
                execution_state["signal"].get("decision_action", "WAIT"),
            )

        analysis = self._compose_analysis(
            structure_state=structure_state,
            context_state=context_state,
            execution_state=execution_state,
            smt_state=smt_state,
            unicorn_state=unicorn_state,
            cisd_state=cisd_state,
            institutional_state=institutional_state,
            decision_state=decision_state,
            volume_profile_state=volume_profile_state,
            news_state=news_state,
            correlation_state=correlation_state,
            cooldown_state=cooldown_state,
        )

        journal_snapshot = self.trade_journal.record_analysis(
            analysis=analysis,
            symbol=data.get("symbol", "UNKNOWN"),
            timeframe="multi",
            metadata={
                "decision": decision_state.get("action"),
                "signal": execution_state["signal"].get("signal"),
                "confidence": execution_state["signal"].get("confidence", 0),
            },
        )
        analysis["journal"] = journal_snapshot

        result_payload = {
            "symbol": symbol,
            "analysis": analysis,
            "signal": execution_state["signal"],
            "risk": execution_state["risk"],
            "rr": execution_state["rr"],
            "dynamic_tp": execution_state["dynamic_tp"],
            "journal": journal_snapshot,
            "decision": decision_state,
        }

        self.scanner.add(symbol, result_payload)
        self.statistics.record_payload(result_payload)
        if execution_state["signal"].get("signal") in ("LONG", "SHORT"):
            self.backtest.record(result_payload)

        if bool(getattr(Config, "STATE_ENGINE_ENABLED", True)):
            self.state_engine.update_analysis_state(symbol, data, result_payload)
            self.state_engine.sync_open_positions(self.position.open_positions())
        if execution_state["signal"].get("signal") in ["LONG", "SHORT"] and decision_state.get("action") in ["EXECUTE", "EXECUTE_WITH_CAUTION"]:
            self.cooldown.register_signal(symbol, execution_state["signal"].get("signal"))
            if getattr(Config, "SIGNAL_TRACKING_ENABLED", True) and self.trade_journal is not None:
                self._register_tracked_signal(symbol, result_payload)

        self._notify_if_elite(
            data=data,
            signal=execution_state["signal"],
            entry=execution_state["entry"],
            risk=execution_state["risk"],
            rr=execution_state["rr"],
            dynamic_tp=execution_state["dynamic_tp"],
            confluence=execution_state["confluence"],
            market_phase=context_state["market_phase"],
            unicorn=unicorn_state,
            cisd=cisd_state,
            institutional=institutional_state,
            decision=decision_state,
        )

        return result_payload

    def record_closed_trade_learning(self, trade):
        """Feed a closed trade result into the adaptive learning engine."""
        if not bool(getattr(Config, "LEARNING_ENGINE_ENABLED", True)):
            return None
        return self.learning.record_closed_trade(trade)

    def _register_tracked_signal(self, symbol, result_payload):
        """EXECUTE sinyalini canlı sonuç takibi için trade journal'a yazar.

        Cooldown penceresi içinde aynı yöndeki tekrar üretimini, mevcut açık
        kayıtla çakışmadan tek sefere indirir (mükerrer sinyal kaydı açmaz).
        """
        risk = result_payload.get("risk") or {}
        entry = risk.get("entry")
        stop_loss = risk.get("stop_loss")
        side = result_payload.get("signal", {}).get("signal")
        if entry is None or stop_loss is None or side not in ("LONG", "SHORT"):
            return None

        for existing in self.trade_journal.open_trades(symbol=symbol):
            if existing.get("side") == side and existing.get("entry") == entry:
                return None

        trade = {
            "symbol": symbol,
            "side": side,
            "entry": entry,
            "stop_loss": stop_loss,
            "tp1": risk.get("tp1") or (result_payload.get("dynamic_tp") or {}).get("tp1"),
            "tp2": risk.get("tp2") or (result_payload.get("dynamic_tp") or {}).get("tp2"),
            "tp3": risk.get("tp3") or (result_payload.get("dynamic_tp") or {}).get("tp3"),
            "confidence": result_payload.get("signal", {}).get("confidence"),
            "confluence_score": (result_payload.get("analysis") or {}).get("confluence", {}).get("score"),
            "market_phase": (result_payload.get("analysis") or {}).get("market_phase", {}).get("phase"),
            "rr": result_payload.get("rr", {}).get("rr") if isinstance(result_payload.get("rr"), dict) else result_payload.get("rr"),
        }
        return self.trade_journal.register_trade(
            trade, analysis=result_payload, symbol=symbol,
            metadata={"origin": "live_scanner", "decision_action": result_payload.get("decision", {}).get("action")},
        )

    def _restore_incremental_if_unchanged(self, symbol, candles):
        """Return cached analysis when the latest 15m candle was already processed."""
        if not self.state_engine.has_new_entry_candle(symbol, candles):
            cached = self.state_engine.restore_cached_result(symbol)
            if cached is not None:
                self.logger.info("Incremental cache hit | symbol=%s last_candle=%s", symbol, candles[-1].time if candles else None)
                return cached
        return None

    def _trim_incremental_data(self, symbol, data):
        """Avoid reprocessing the full history when persisted state already has older candles."""
        symbol_state = self.state_engine.get_symbol_state(symbol) or {}
        if not symbol_state.get("last_candle"):
            return data
        warmup = int(getattr(Config, "INCREMENTAL_WARMUP_CANDLES", 250))
        trimmed = dict(data)
        for timeframe in self.REQUIRED_TIMEFRAMES + ("1h",):
            candles = data.get(timeframe) or data.get(timeframe.upper())
            if not candles or len(candles) <= warmup:
                continue
            trimmed[timeframe] = candles[-warmup:]
        trimmed["incremental"] = {
            "enabled": True,
            "warmup_candles": warmup,
            "new_15m_candles": len(self.state_engine.new_candles_since_last(symbol, data.get("15m") or [])),
        }
        return trimmed

    def _apply_external_risk_filters(self, decision, news_filter, correlation, cooldown):
        """Gate new entries around macro news, market correlation conflicts and duplicate trades."""
        blockers = []
        for name, payload in (("news_filter", news_filter), ("correlation", correlation), ("cooldown", cooldown)):
            # Correlation motoru veri yokken active=False döner; o durumda engelleme yapma.
            if payload and not bool(payload.get("active", True)):
                continue
            if payload and not payload.get("trade_allowed", True):
                blockers.append(f"{name}: {payload.get('reason', 'blocked')}")
        if not blockers:
            return decision
        enriched = dict(decision or {})
        enriched["action"] = "SKIP"
        enriched["external_blockers"] = blockers
        existing = enriched.get("critical_blockers") or []
        enriched["critical_blockers"] = existing + blockers
        enriched["reason"] = "; ".join(blockers)
        return enriched

    def _analyze_timeframe(self, candles):
        """Tek zaman dilimi için pivot, etiket, BOS ve CHoCH üretir."""
        engine = self.structure_engine_cls()

        engine.find_pivots(candles)
        engine.calculate_strength(candles)
        engine.merge_pivots()
        engine.filter_noise()

        pivots = engine.validate_sequence()
        structure = self.choch.detect(self.bos.detect(label_swings(pivots)))

        return {
            "pivots": pivots,
            "structure": structure,
        }

    def _build_structure_state(self, candles, structure, timeframe_data):
        """BOS/CHoCH sonrası seviye ve likidite katmanını üretir."""
        liquidity_layers = self.liquidity.detect_layers(structure, candles)
        liquidity = liquidity_layers["all"]
        eqh_eql = self._detect_eqh_eql(liquidity)

        raw_orderblocks = self.orderblocks.detect(candles, structure)
        orderblocks = self.mitigation.detect(candles, raw_orderblocks)
        breaker = self.breaker.detect(candles, orderblocks)

        fvg = self.fvg.detect(candles)
        liquidity_sweep = self.liquidity_sweep.detect(
            candles=candles,
            structure=structure,
            liquidity_layers=liquidity_layers,
            timeframe="15m",
        )

        mtf_sweep = self._detect_mtf_liquidity_sweep(timeframe_data)
        liquidity_sweep["mtf"] = mtf_sweep

        if mtf_sweep.get("best"):
            liquidity_sweep["strength_score"] = max(
                liquidity_sweep.get("strength_score", 0),
                mtf_sweep["best"].get("strength_score", 0),
            )

        inducement = self._detect_inducement(structure, liquidity_sweep, eqh_eql)

        current_price = candles[-1].close if candles else 0.0

        trendline_liquidity = self.trendline.detect_liquidity(
            structure,
            candles,
            current_price,
        )
        trendline_sweep = self.trendline.detect_sweep(structure, candles)
        trendline_sweep_state = self.trendline.serialize(trendline_sweep)

        ifvg = self.fvg.detect_inversion(candles)

        internal_structure, external_structure = self._detect_internal_external_structure(
            structure,
            candles,
            liquidity_layers,
        )

        return {
            "structure": structure,
            "bos": [item for item in structure if item.get("bos")],
            "choch": [item for item in structure if item.get("choch")],
            "liquidity": liquidity,
            "liquidity_layers": liquidity_layers,
            "eqh_eql": eqh_eql,
            "orderblocks": orderblocks,
            "fvg": fvg,
            "ifvg": ifvg,
            "trendline_liquidity": trendline_liquidity,
            "trendline_sweep": trendline_sweep_state,
            "internal_structure": internal_structure,
            "external_structure": external_structure,
            "liquidity_sweep": liquidity_sweep,
            "inducement": inducement,
            "breaker": breaker,
        }

    def _detect_internal_external_structure(self, structure, candles, liquidity_layers):
        """İç (minor) ve dış (major) yapı katmanlarını etiketler.

        - external_structure: daha geniş bakış açısıyla major swing noktaları
        - internal_structure: major swing arasındaki minor hareketler
        """
        if not structure:
            return [], []

        # Dış yapı: yüksek öneme sahip (break/önemli) ve aralıklı pivotlar
        majors = [
            item
            for item in structure
            if item.get("bos") or item.get("choch")
        ]
        if not majors:
            majors = structure[::3]

        external = []
        for item in majors:
            external.append(
                {
                    "index": item.get("index"),
                    "price": item.get("price"),
                    "type": item.get("kind"),
                    "kind": item.get("kind"),
                    "label": item.get("label"),
                    "bos": item.get("bos", False),
                    "choch": item.get("choch", False),
                }
            )

        # İç yapı: major pivotların arasındaki swing'ler
        major_indices = {item.get("index") for item in majors}
        internal = [
            {
                "index": item.get("index"),
                "price": item.get("price"),
                "type": item.get("kind"),
                "kind": item.get("kind"),
                "label": item.get("label"),
            }
            for item in structure
            if item.get("index") not in major_indices
        ]

        return internal, external

    def _detect_mtf_liquidity_sweep(self, timeframe_data):
        """15m/1h/4h/1d için MTF liquidity sweep analizi üretir."""
        payload = {}

        for timeframe in self.SWEEP_TIMEFRAMES:
            data = timeframe_data.get(timeframe) or {}
            candles = data.get("candles") or []
            structure = data.get("structure") or []

            if not candles:
                continue

            payload[timeframe] = {
                "candles": candles,
                "structure": structure,
                "liquidity_layers": self.liquidity.detect_layers(structure, candles),
            }

        return self.liquidity_sweep.detect_multi(payload)

    def _build_context_state(
        self,
        candles,
        daily,
        h4,
        weekly_structure,
        daily_structure,
        h4_structure,
        entry_structure,
        liquidity,
        fvg,
        orderblocks,
        liquidity_sweep,
        breakers,
    ):
        """MTF, trend, premium/discount, OTE ve market phase katmanını üretir."""
        swing_high, swing_low, current_price = self._price_context(candles)

        premium_discount = self.premium_discount.calculate(
            swing_high,
            swing_low,
            current_price,
        )

        timestamp = candles[-1].time
        killzone = self.killzone.detect(timestamp)
        session = self.session.check(timestamp)

        mtf = self.mtf.detect(
            weekly_structure,
            daily_structure,
            h4_structure,
            entry_structure,
        )
        trend = self.trend.calculate(mtf)

        daily_orderblocks = self.orderblocks.detect(daily, daily_structure)
        h4_orderblocks = self.orderblocks.detect(h4, h4_structure)

        ote = self.ote.detect(
            swing_high,
            swing_low,
            current_price,
            mtf.get("entry", "NONE"),
        )

        htf_orderblock = self.htf_orderblock.detect(
            current_price,
            daily_orderblocks,
            h4_orderblocks,
        )
        htf_fvg = self.htf_fvg.detect(self.fvg.detect(h4), self.fvg.detect(daily))

        market_phase = self.market_phase.detect(
            structure=entry_structure,
            trend=trend,
            liquidity_sweep=liquidity_sweep,
            fvg=fvg,
            orderblocks=orderblocks,
            premium_discount=premium_discount,
            mtf=mtf,
            candles=candles,
        )

        return {
            "mtf": mtf,
            "trend": trend,
            "premium_discount": premium_discount,
            "killzone": killzone,
            "session": session,
            "ote": ote,
            "htf_orderblock": htf_orderblock,
            "htf_fvg": htf_fvg,
            "market_phase": market_phase,
            "price": {
                "swing_high": swing_high,
                "swing_low": swing_low,
                "current_price": current_price,
            },
            "daily_orderblocks": daily_orderblocks,
            "h4_orderblocks": h4_orderblocks,
            "breaker": breakers,
            "liquidity": liquidity,
        }

    def _build_execution_state(
        self,
        candles,
        entry_structure,
        mtf,
        trend,
        fvg,
        orderblocks,
        premium_discount,
        liquidity_sweep,
        breaker,
        ote,
        htf_orderblock,
        htf_fvg,
        killzone,
        session,
        market_phase,
        liquidity,
        smt,
        unicorn,
        cisd,
        volume_profile,
        institutional,
        news_filter=None,
        correlation=None,
        cooldown=None,
        trendline_sweep=None,
        ifvg=None,
        eqh_eql=None,
        internal_structure=None,
    ):
        """Entry, confirmation, confluence, signal, risk ve RR katmanını üretir."""
        entry = self.entry.generate(mtf, entry_structure, fvg, orderblocks, current_price=candles[-1].close if candles else None)
        confirmation = self.entry_confirmation.confirm(mtf, entry_structure, fvg, entry)

        setup_quality = self.setup_quality.evaluate(
            candles=candles,
            direction=entry.get("direction", "WAIT"),
            mtf=mtf,
            trend=trend,
            structure=entry_structure,
            liquidity_sweep=liquidity_sweep,
            orderblocks=orderblocks,
            fvg=fvg,
            premium_discount=premium_discount,
            market_phase=market_phase,
            session=session,
            entry=entry,
            confirmation=confirmation,
            smt=smt,
            unicorn=unicorn,
            cisd=cisd,
            volume_profile=volume_profile,
            institutional=institutional,
        )
        if bool(getattr(Config, "LEARNING_ENGINE_ENABLED", True)):
            setup_quality = self.learning.apply_to_setup_quality(setup_quality)
        setup_quality["external_risk_filters"] = {
            "news_filter": news_filter or {},
            "correlation": correlation or {},
            "cooldown": cooldown or {},
        }
        if any(not (flt or {}).get("trade_allowed", True) for flt in setup_quality["external_risk_filters"].values()):
            setup_quality["trade_allowed"] = False
            setup_quality.setdefault("blockers", []).extend(
                name for name, flt in setup_quality["external_risk_filters"].items() if not (flt or {}).get("trade_allowed", True)
            )

        confluence = self.confluence.evaluate(
            mtf=mtf,
            trend=trend,
            entry=entry,
            confirmation=confirmation,
            premium_discount=premium_discount,
            liquidity_sweep=liquidity_sweep,
            breaker=breaker,
            ote=ote,
            htf_orderblock=htf_orderblock,
            htf_fvg=htf_fvg,
            killzone=killzone,
            session=session,
            smt=smt,
            orderblocks=orderblocks,
            fvg=fvg,
            market_phase=market_phase,
            unicorn=unicorn,
            cisd=cisd,
            volume_profile=volume_profile,
            institutional=institutional,
            trendline_sweep=trendline_sweep,
            ifvg=ifvg,
            eqh_eql=eqh_eql,
            internal_structure=internal_structure,
        )

        dynamic_tp = self._calculate_dynamic_tp(
            entry=entry,
            liquidity=liquidity,
            fvg=fvg,
            orderblocks=orderblocks,
            candles=candles,
            structure=entry_structure,
        )
        risk = self._calculate_risk(entry, dynamic_tp, volume_profile, institutional, candles=candles)
        rr = self.rr.evaluate(risk) if risk is not None else None

        analysis_for_signal = {
            "entry": entry,
            "confirmation": confirmation,
            "confluence": confluence,
            "market_phase": market_phase,
            "liquidity_sweep": liquidity_sweep,
            "smt": smt,
            "unicorn": unicorn,
            "cisd": cisd,
            "volume_profile": volume_profile,
            "institutional": institutional,
            "setup_quality": setup_quality,
            "news_filter": news_filter or {},
            "correlation": correlation or {},
            "cooldown": cooldown or {},
        }
        signal = self.signal.generate(analysis_for_signal)

        if not entry.get("valid"):
            self.logger.info("Entry rejected | reason=%s", entry.get("reason", "unknown"))
        if not confirmation.get("confirmed"):
            self.logger.info("Confirmation rejected | reason=%s", confirmation.get("reason", "unknown"))
        if isinstance(risk, dict) and risk.get("risk_setup_valid") is False:
            self.logger.info("Risk rejected | reason=%s", risk.get("risk_setup_reason", "Invalid Risk Setup"))
        if signal.get("signal") == "WAIT":
            self.logger.info("Signal WAIT | reason=%s", signal.get("wait_reason", "unknown"))

        return {
            "entry": entry,
            "confirmation": confirmation,
            "confluence": confluence,
            "dynamic_tp": dynamic_tp,
            "risk": risk,
            "rr": rr,
            "signal": signal,
            "setup_quality": setup_quality,
        }

    def _compose_analysis(
        self,
        structure_state,
        context_state,
        execution_state,
        smt_state,
        unicorn_state=None,
        cisd_state=None,
        institutional_state=None,
        decision_state=None,
        volume_profile_state=None,
        news_state=None,
        correlation_state=None,
        cooldown_state=None,
    ):
        """Dış API'de beklenen analysis sözlüğünü oluşturur."""
        analysis_payload = {
            "structure": structure_state["structure"],
            "bos": structure_state["bos"],
            "choch": structure_state["choch"],
            "liquidity": structure_state["liquidity"],
            "liquidity_layers": structure_state.get(
                "liquidity_layers",
                {
                    "swing": [],
                    "internal": [],
                    "all": structure_state.get("liquidity", []),
                    "bsl": [],
                    "ssl": [],
                    "eqh": [],
                    "eql": [],
                },
            ),
            "eqh_eql": structure_state["eqh_eql"],
            "ifvg": structure_state.get("ifvg", []),
            "trendlines": structure_state.get("trendline_liquidity", []),
            "trendline_sweep": structure_state.get("trendline_sweep", {}),
            "internal_structure": structure_state.get("internal_structure", []),
            "external_structure": structure_state.get("external_structure", []),
            "orderblocks": structure_state["orderblocks"],
            "fvg": structure_state["fvg"],
            "liquidity_sweep": structure_state["liquidity_sweep"],
            "inducement": structure_state["inducement"],
            "mtf": context_state["mtf"],
            "trend": context_state["trend"],
            "entry": execution_state["entry"],
            "confirmation": execution_state["confirmation"],
            "ote": context_state["ote"],
            "premium_discount": context_state["premium_discount"],
            "killzone": context_state["killzone"],
            "session": context_state["session"],
            "breaker": structure_state["breaker"],
            "htf_orderblock": context_state["htf_orderblock"],
            "htf_fvg": context_state["htf_fvg"],
            "dynamic_tp": execution_state["dynamic_tp"],
            "confluence": execution_state["confluence"],
            "market_phase": context_state["market_phase"],
            "smt": smt_state,
            "volume_profile": volume_profile_state or {
                "active": False,
                "direction": "NONE",
                "confidence": 0,
                "best": None,
                "timeframes": {},
            },
            "unicorn": unicorn_state or {
                "active": False,
                "direction": "NONE",
                "confidence": 0,
                "best": None,
                "setups": [],
                "timeframes": {},
            },
            "cisd": cisd_state or {
                "active": False,
                "direction": "NONE",
                "confidence": 0,
                "best": None,
                "timeframes": {},
                "events": [],
            },
            "institutional": institutional_state or {
                "active": False,
                "direction": "NONE",
                "confidence": 0,
                "score": 0,
                "best": None,
            },
            "setup_quality": execution_state.get("setup_quality", {}),
            "news_filter": news_state or {},
            "correlation": correlation_state or {},
            "cooldown": cooldown_state or {},
            "learning": {"setup_success_rates": self.learning.setup_success_rates()},
            "decision": decision_state or {
                "action": "WAIT",
                "reason": "No decision",
            },
            "symbol": decision_state.get("symbol") if isinstance(decision_state, dict) else None,
            "modules": {
                "structure": structure_state,
                "context": context_state,
                "execution": execution_state,
                "smt": smt_state,
                "unicorn": unicorn_state or {},
                "cisd": cisd_state or {},
                "volume_profile": volume_profile_state or {},
                "institutional": institutional_state or {},
                "news_filter": news_state or {},
                "correlation": correlation_state or {},
                "cooldown": cooldown_state or {},
                "decision": decision_state or {},
            },
        }
        if analysis_payload["symbol"] is None:
            analysis_payload.pop("symbol")
        return analysis_payload

    def _build_institutional_state(self, data, context_state, structure_state, volume_profile_state, smt_state, unicorn_state, cisd_state):
        """Kurumsal akış, VWAP ve regime katmanını üretir."""
        payload = dict(data)
        payload["session"] = context_state.get("session", {})
        payload["market_phase"] = context_state.get("market_phase", {})
        payload["volume_profile"] = volume_profile_state or {}
        payload["smt"] = smt_state or {}
        payload["unicorn"] = unicorn_state or {}
        payload["cisd"] = cisd_state or {}
        payload["liquidity_sweep"] = structure_state.get("liquidity_sweep", {})

        return self.institutional.analyze(payload)

    def _build_volume_profile_state(self, data):
        """Çoklu zaman diliminde volume profile durumunu üretir."""
        payload = {}

        for timeframe in self.VOLUME_PROFILE_TIMEFRAMES:
            candles = data.get(timeframe) or data.get(timeframe.upper())
            if candles:
                payload[timeframe] = candles

        return self.volume_profile.detect_multi(payload)

    def _build_cisd_state(self, data, tf_analysis, context_state, smt_state):
        """CISD için MTF payload oluşturur ve sonucu döndürür."""
        timeframe_to_structure_key = {
            "15m": "entry",
            "1h": "h1",
            "4h": "h4",
            "1d": "daily",
        }

        payload = {}

        for timeframe in self.CISD_TIMEFRAMES:
            candles = data.get(timeframe) or data.get(timeframe.upper())
            if not candles:
                continue

            key = timeframe_to_structure_key[timeframe]
            structure = tf_analysis.get(key, {}).get("structure", [])
            liquidity_layers = self.liquidity.detect_layers(structure, candles)
            liquidity_sweep = self.liquidity_sweep.detect(
                candles=candles,
                structure=structure,
                liquidity_layers=liquidity_layers,
                timeframe=timeframe,
            )

            payload[timeframe] = {
                "candles": candles,
                "structure": structure,
                "liquidity_sweep": liquidity_sweep,
                "market_phase": context_state["market_phase"],
                "smt": smt_state,
            }

        return self.cisd.detect_multi(payload)

    def _build_unicorn_state(self, data, tf_analysis, context_state, structure_state, smt_state):
        """Unicorn setup tespiti için MTF payload üretir ve sonucu döndürür."""
        mtf_direction = context_state["mtf"].get("entry", "NONE")
        timeframe_to_structure_key = {
            "15m": "entry",
            "1h": "h1",
            "4h": "h4",
            "1d": "daily",
        }

        payload = {}

        for timeframe in self.UNICORN_TIMEFRAMES:
            candles = data.get(timeframe) or data.get(timeframe.upper())
            if not candles:
                continue

            key = timeframe_to_structure_key[timeframe]
            structure = tf_analysis.get(key, {}).get("structure", [])

            liquidity_layers = self.liquidity.detect_layers(structure, candles)
            liquidity = liquidity_layers["all"]
            eqh_eql = self._detect_eqh_eql(liquidity)

            raw_orderblocks = self.orderblocks.detect(candles, structure)
            orderblocks = self.mitigation.detect(candles, raw_orderblocks)
            breaker = self.breaker.detect(candles, orderblocks)
            fvg = self.fvg.detect(candles)

            liquidity_sweep = self.liquidity_sweep.detect(
                candles=candles,
                structure=structure,
                liquidity_layers=liquidity_layers,
                timeframe=timeframe,
            )
            inducement = self._detect_inducement(structure, liquidity_sweep, eqh_eql)

            swing_high, swing_low, current_price = self._price_context(candles)
            ote = self.ote.detect(
                swing_high=swing_high,
                swing_low=swing_low,
                current_price=current_price,
                direction=mtf_direction,
            )

            payload[timeframe] = {
                "structure": structure,
                "breaker": breaker,
                "fvg": fvg,
                "market_phase": context_state["market_phase"],
                "liquidity_sweep": liquidity_sweep,
                "smt": smt_state,
                "orderblocks": orderblocks,
                "eqh_eql": eqh_eql,
                "inducement": inducement,
                "ote": ote,
                "liquidity_layers": liquidity_layers,
                "liquidity": liquidity,
            }

        unicorn = self.unicorn.detect(payload)

        # 15m için zaten hesaplanan katmanı tekrar kullan.
        if "15m" in unicorn.get("timeframes", {}):
            unicorn["timeframes"]["15m"]["liquidity_sweep"] = structure_state["liquidity_sweep"]

        return unicorn

    def _build_smt_state(self, data):
        """BTC, ETH ve seçili altcoin verileriyle SMT divergence üretir."""
        primary_symbol = data.get("symbol", "UNKNOWN")

        primary_timeframes = {
            "15m": data.get("15m"),
            "1h": data.get("1h") or data.get("1H"),
            "4h": data.get("4h"),
            "1d": data.get("1d"),
        }

        smt_universe = data.get("smt_universe") or {}
        selected_altcoins = data.get("selected_altcoins") or []

        if primary_symbol not in smt_universe:
            smt_universe = dict(smt_universe)
            smt_universe[primary_symbol] = primary_timeframes

        return self.smt.detect(
            primary_symbol=primary_symbol,
            primary_timeframes=primary_timeframes,
            smt_universe=smt_universe,
            selected_symbols=selected_altcoins,
            timeframes=self.SMT_TIMEFRAMES,
        )

    def _validate_market_data(self, data):
        """Gerekli veri setlerinin varlığını ve boş olmadığını doğrular."""
        missing = [tf for tf in self.REQUIRED_TIMEFRAMES if not data.get(tf)]
        if missing:
            raise ValueError(f"Missing or empty market data timeframes: {', '.join(missing)}")

    def _price_context(self, candles):
        """Geçerli fiyat ve işlem aralığını hesaplar."""
        swing_high = max(candle.high for candle in candles)
        swing_low = min(candle.low for candle in candles)
        current_price = candles[-1].close
        return swing_high, swing_low, current_price

    def _detect_eqh_eql(self, liquidity, tolerance_pct=0.003):
        """EQH/EQL detection: yakın fiyattaki çoklu swing tepelerini/dipleri kümeleyerek
        gerçek equal high/low seviyelerini tespit eder.

        Bir seviye yalnızca en az iki *farklı* swing noktası aynı fiyat bandına
        kümelendiğinde EQH (equal high) / EQL (equal low) sayılır.
        """
        from collections import defaultdict

        equal_highs = []
        equal_lows = []

        buy = [level for level in liquidity if level.get("type") == "BUY_SIDE"]
        sell = [level for level in liquidity if level.get("type") == "SELL_SIDE"]

        def _cluster(levels, level_tag):
            result = []
            grouped = defaultdict(list)
            for level in levels:
                price = level.get("price", 0) or 0
                if not price:
                    continue
                placed = False
                for key in list(grouped.keys()):
                    if abs(key - price) <= tolerance_pct * price:
                        grouped[key].append(level)
                        placed = True
                        break
                if not placed:
                    grouped[price].append(level)
            for entries in grouped.values():
                distinct_prices = {round(e["price"], 6) for e in entries}
                if len(distinct_prices) < 2:
                    continue
                touches = sum(e.get("touches", 1) for e in entries)
                price = sum(e["price"] for e in entries) / len(entries)
                indices = [e["index"] for e in entries if e.get("index") is not None]
                result.append(
                    {
                        "type": "SELL_SIDE" if level_tag == "EQL" else "BUY_SIDE",
                        "level": level_tag,
                        "price": price,
                        "touches": touches,
                        "indices": indices,
                        "confirmed": True,
                    }
                )
            return result

        equal_highs = _cluster(buy, "EQH")
        equal_lows = _cluster(sell, "EQL")

        return {
            "eqh": equal_highs,
            "eql": equal_lows,
            "active": bool(equal_highs or equal_lows),
        }

    def _detect_inducement(self, structure, liquidity_sweep, eqh_eql):
        """Liquidity sweep ve EQH/EQL bağlamından inducement sinyali üretir."""
        direction = None

        if liquidity_sweep.get("sell_side"):
            direction = "LONG"
        elif liquidity_sweep.get("buy_side"):
            direction = "SHORT"

        return {
            "active": direction is not None and eqh_eql.get("active", False),
            "direction": direction,
            "reason": "Liquidity sweep after equal highs/lows" if direction else "No inducement",
            "recent_structure": structure[-3:] if structure else [],
        }

    def _calculate_dynamic_tp(self, entry, liquidity, fvg, orderblocks, candles=None, structure=None):
        """Entry yoksa boş TP şablonu, varsa dinamik hedefler döndürür."""
        if entry.get("entry") is None:
            return {"tp1": None, "tp2": None, "tp3": None}

        try:
            payload = self.dynamic_tp.calculate(
                direction=entry["direction"],
                entry=entry["entry"],
                stop_loss=entry.get("stop_loss"),
                liquidity=liquidity,
                fvg=fvg,
                orderblocks=orderblocks,
                structure=structure,
                candles=candles,
            )
            self.logger.info(
                "TP calculated | direction=%s tp1=%s tp2=%s tp3=%s reason=%s",
                entry.get("direction"),
                payload.get("tp1"),
                payload.get("tp2"),
                payload.get("tp3"),
                payload.get("reason"),
            )
            return payload
        except Exception:
            self.logger.exception("Dynamic TP hesaplama hatasi")
            return {"tp1": None, "tp2": None, "tp3": None}

    def _calculate_risk(self, entry, dynamic_tp, volume_profile=None, institutional=None, candles=None):
        """Geçerli entry/SL için risk çıktısını hesaplar."""
        if entry.get("entry") is None or entry.get("stop_loss") is None:
            return None

        risk_payload = self.risk.calculate(
            entry=entry["entry"],
            stop_loss=entry["stop_loss"],
            dynamic_tp=dynamic_tp,
            volume_profile=volume_profile,
            institutional=institutional,
            candles=candles,
        )

        if isinstance(risk_payload, dict) and risk_payload.get("risk_setup_valid") is False:
            self.logger.info(
                "Risk invalid | reason=%s requested_risk=%s min_stop=%s",
                risk_payload.get("risk_setup_reason"),
                risk_payload.get("requested_risk"),
                risk_payload.get("minimum_stop_distance"),
            )

        return risk_payload

    def _notify_if_elite(
        self,
        data,
        signal,
        entry,
        risk,
        rr,
        dynamic_tp,
        confluence,
        market_phase,
        unicorn,
        cisd,
        institutional,
        decision,
    ):
        """Yüksek güvenli sinyallerde Telegram bildirimi gönderir."""
        Config.refresh_from_env()

        if not bool(getattr(Config, "TELEGRAM_ENABLED", True)):
            return False

        if signal.get("signal") not in ["LONG", "SHORT"]:
            self._telegram_skip_log(
                reason_code="NO_DIRECTION",
                symbol=data.get("symbol", "UNKNOWN"),
                signal=signal,
                risk=risk,
                decision=decision,
                market_phase=market_phase,
                detail=f"signal_dir={signal.get('signal', 'WAIT')} decision={(decision or {}).get('action', 'WAIT')}",
            )
            return False

        signal_action = signal.get("signal", "WAIT")
        decision_action = (decision or {}).get("action", "WAIT")
        decision_trade_direction = self._resolve_trade_direction_from_decision(
            signal_action=signal_action,
            decision_action=decision_action,
        )
        require_decision_action = bool(getattr(Config, "TELEGRAM_REQUIRE_DECISION_ACTION", False))
        if require_decision_action and decision_trade_direction not in ["LONG", "SHORT"]:
            self._telegram_skip_log(
                reason_code="DECISION_NOT_TRADEABLE",
                symbol=data.get("symbol", "UNKNOWN"),
                signal=signal,
                risk=risk,
                decision=decision,
                market_phase=market_phase,
                detail=f"decision_action={decision_action}",
            )
            return False
        action_for_message = decision_trade_direction if decision_trade_direction in ["LONG", "SHORT"] else signal_action

        if not entry.get("valid", False):
            self._telegram_skip_log(
                reason_code="ENTRY_INVALID",
                symbol=data.get("symbol", "UNKNOWN"),
                signal=signal,
                risk=risk,
                decision=decision,
                market_phase=market_phase,
                detail=f"entry_valid={entry.get('valid')}",
            )
            return False

        if entry.get("entry") is None or entry.get("stop_loss") is None:
            self._telegram_skip_log(
                reason_code="ENTRY_LEVELS_MISSING",
                symbol=data.get("symbol", "UNKNOWN"),
                signal=signal,
                risk=risk,
                decision=decision,
                market_phase=market_phase,
                detail=f"entry={entry.get('entry')} stop_loss={entry.get('stop_loss')}",
            )
            return False

        if not risk or risk.get("risk") is None or risk.get("risk") <= 0:
            self._telegram_skip_log(
                reason_code="RISK_PAYLOAD_INVALID",
                symbol=data.get("symbol", "UNKNOWN"),
                signal=signal,
                risk=risk,
                decision=decision,
                market_phase=market_phase,
                detail=f"risk_setup_valid={risk.get('risk_setup_valid') if isinstance(risk, dict) else None} reason={risk.get('risk_setup_reason') if isinstance(risk, dict) else None}",
            )
            return False

        min_confidence = float(getattr(Config, "TELEGRAM_MIN_CONFIDENCE", 85))
        if signal.get("confidence", 0) < min_confidence:
            self._telegram_skip_log(
                reason_code="LOW_CONFIDENCE",
                symbol=data.get("symbol", "UNKNOWN"),
                signal=signal,
                risk=risk,
                decision=decision,
                market_phase=market_phase,
                detail=f"confidence={self._safe_number(signal.get('confidence'))} < min={min_confidence}",
            )
            return False

        manual_quality = self.manual_quality_gate.evaluate(
            symbol=data.get("symbol", "UNKNOWN"),
            signal=signal,
            entry=entry,
            risk=risk,
            decision=decision,
            confluence=confluence,
            market_phase=market_phase,
            trade_journal=self.trade_journal,
        )
        quality_blockers = self._telegram_quality_blockers(
            signal=signal,
            entry=entry,
            risk=risk,
            decision=decision,
            confluence=confluence,
            market_phase=market_phase,
        )
        quality_blockers.extend(manual_quality.get("blockers") or [])
        if quality_blockers:
            self._telegram_skip_log(
                reason_code="QUALITY_GATE",
                symbol=data.get("symbol", "UNKNOWN"),
                signal=signal,
                risk=risk,
                decision=decision,
                market_phase=market_phase,
                detail="; ".join(quality_blockers),
            )
            return False

        symbol = data.get("symbol", "UNKNOWN")
        if not self._should_send_telegram_signal(symbol, action_for_message, entry, risk):
            self._telegram_skip_log(
                reason_code="SIGNAL_COOLDOWN",
                symbol=symbol,
                signal=signal,
                risk=risk,
                decision=decision,
                market_phase=market_phase,
                detail="duplicate setup in cooldown window",
            )
            return False

        bot_token = str(getattr(Config, "TELEGRAM_BOT_TOKEN", "") or "").strip()
        if not bot_token:
            self._telegram_skip_log(
                reason_code="BOT_TOKEN_MISSING",
                symbol=symbol,
                signal=signal,
                risk=risk,
                decision=decision,
                market_phase=market_phase,
                detail="bot token not configured",
            )
            return False

        telegram_module = import_module("telegram_engine")
        telegram_engine = self.telegram or telegram_module.TelegramEngine()
        self.telegram = telegram_engine

        signal_for_message = dict(signal)
        signal_for_message["signal"] = action_for_message
        try:
            confidence = int(float(signal.get("confidence", 0)))
        except (TypeError, ValueError):
            confidence = 0
        signal_for_message["confidence"] = max(0, min(100, confidence))

        message = telegram_engine.format_signal(
            {
                "symbol": symbol,
                "signal": signal_for_message,
                "entry": entry,
                "risk": risk,
                "rr": rr,
                "dynamic_tp": dynamic_tp,
                "confluence": confluence,
                "market_phase": market_phase,
                "unicorn": unicorn,
                "cisd": cisd,
                "institutional": institutional,
                "decision": decision,
                "manual_quality": manual_quality,
            }
        )

        bot_class = getattr(telegram_module, "TelegramBot")
        reply_markup = None
        if hasattr(bot_class, "trade_feedback_keyboard"):
            reply_markup = bot_class.trade_feedback_keyboard(symbol, action_for_message)

        print(message)
        if bool(getattr(Config, "TELEGRAM_ASYNC_SEND", True)):
            thread = threading.Thread(
                target=self._send_telegram_safe,
                kwargs={
                    "telegram_module": telegram_module,
                    "message": message,
                    "symbol": symbol,
                    "reply_markup": reply_markup,
                },
                daemon=False,
            )
            thread.start()
            self._telegram_threads.append(thread)
            return True

        return self._send_telegram_safe(
            telegram_module=telegram_module,
            message=message,
            symbol=symbol,
            reply_markup=reply_markup,
        )


    def _telegram_quality_blockers(self, signal, entry=None, risk=None, decision=None, confluence=None, market_phase=None):
        """Telegram'a sadece manuel islem icin disiplinli risk/kalite kurallarini gecen setup'lari birakir."""
        if not bool(getattr(Config, "TELEGRAM_QUALITY_FILTERS_ENABLED", True)):
            return []

        blockers = []
        signal = signal or {}
        entry = entry or {}
        risk = risk or {}
        decision = decision or {}
        confluence = confluence or {}
        market_phase = market_phase or {}

        min_grade = str(getattr(Config, "TELEGRAM_MIN_GRADE", "A") or "A").strip().upper()
        grade = str(signal.get("grade", "") or "").strip().upper()
        if not self._grade_at_least(grade, min_grade):
            blockers.append(f"grade {grade or 'NONE'} < {min_grade}")

        min_rr = float(getattr(Config, "TELEGRAM_MIN_RR", 3.0))
        rr_value = self._resolve_telegram_rr(risk)
        if rr_value is None or rr_value < min_rr:
            blockers.append(f"rr {self._fmt_optional_number(rr_value)} < {self._fmt_optional_number(min_rr)}")

        min_confluence = float(getattr(Config, "TELEGRAM_MIN_CONFLUENCE_SCORE", 70))
        confluence_score = self._safe_number(confluence.get("score"), None)
        if confluence_score is None or confluence_score < min_confluence:
            blockers.append(
                f"confluence {self._fmt_optional_number(confluence_score)} < {self._fmt_optional_number(min_confluence)}"
            )

        action = str(decision.get("action", "WAIT") or "WAIT").strip().upper()
        allowed_actions = {"EXECUTE"}
        if bool(getattr(Config, "TELEGRAM_ALLOW_CAUTION_SIGNALS", False)):
            allowed_actions.add("EXECUTE_WITH_CAUTION")
        if action not in allowed_actions:
            blockers.append(f"decision action {action} not allowed")

        for blocker in decision.get("critical_blockers") or []:
            blockers.append(f"critical blocker: {blocker}")
        for blocker in decision.get("external_blockers") or []:
            blockers.append(f"external blocker: {blocker}")
        if decision.get("risk_valid") is False:
            blockers.append("decision risk invalid")

        if bool(getattr(Config, "TELEGRAM_REQUIRE_MTF_ALIGNMENT", True)):
            mtf_valid = decision.get("mtf_valid")
            if mtf_valid is False:
                blockers.append("MTF alignment invalid")

        allowed_phases = set(getattr(Config, "TELEGRAM_ALLOWED_MARKET_PHASES", ("Expansion", "Trending", "Reversal")))
        phase = str(market_phase.get("phase") or decision.get("market_phase") or "").strip()
        if allowed_phases and phase not in allowed_phases:
            blockers.append(f"market phase {phase or 'UNKNOWN'} not allowed")

        if entry.get("direction") and signal.get("signal") and entry.get("direction") != signal.get("signal"):
            blockers.append("entry direction and signal direction mismatch")

        return blockers

    def _resolve_telegram_rr(self, risk):
        selected_rr = self._safe_positive_number(risk.get("selected_rr"))
        if selected_rr is not None:
            return selected_rr

        rr = self._safe_positive_number(risk.get("rr"))
        if rr is not None:
            return rr

        rr_by_tp = risk.get("rr_by_tp")
        if isinstance(rr_by_tp, dict):
            values = [self._safe_positive_number(value) for value in rr_by_tp.values()]
            values = [value for value in values if value is not None]
            if values:
                return max(values)

        return None

    def _grade_at_least(self, grade, minimum_grade):
        rank = {"D": 1, "C": 2, "B": 3, "A": 4, "A+": 5, "S": 6, "S+": 7}
        return rank.get(str(grade or "").strip().upper(), 0) >= rank.get(str(minimum_grade or "").strip().upper(), 0)

    def _safe_positive_number(self, value):
        number = self._safe_number(value, None)
        return number if number is not None and number > 0 else None

    def _safe_number(self, value, default=None):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _fmt_optional_number(self, value):
        if value is None:
            return "NONE"
        return f"{float(value):.2f}".rstrip("0").rstrip(".")

    def _telegram_skip_log(
        self,
        reason_code,
        symbol,
        signal=None,
        risk=None,
        decision=None,
        market_phase=None,
        detail=None,
    ):
        """Telegram'a engellenen her sinyal için ayrıntılı, yapılandırılmış log üretir.

        reason_code, confidence, RR, stop_distance, risk_amount ve market_phase'i
        tek bir satırda toplar; engellenen sinyallerin teşhisini kolaylaştırır.
        """
        signal = signal or {}
        risk = risk or {}
        decision = decision or {}
        market_phase = market_phase or {}

        confidence = self._safe_number(signal.get("confidence"))
        rr_value = self._resolve_telegram_rr(risk)
        stop_loss = risk.get("stop_loss") if isinstance(risk, dict) else None
        entry = risk.get("entry") if isinstance(risk, dict) else None
        stop_distance = None
        if entry is not None and stop_loss is not None:
            stop_distance = self._safe_number(abs(self._safe_number(entry, 0.0) - self._safe_number(stop_loss, 0.0)))
        risk_amount = self._safe_number(risk.get("risk")) if isinstance(risk, dict) else None
        phase = str(market_phase.get("phase") or decision.get("market_phase") or "UNKNOWN")

        self.logger.info(
            "Telegram skip | reason_code=%s symbol=%s confidence=%s rr=%s "
            "stop_distance=%s risk_amount=%s market_phase=%s detail=%s",
            reason_code,
            symbol,
            self._fmt_optional_number(confidence),
            self._fmt_optional_number(rr_value),
            self._fmt_optional_number(stop_distance),
            self._fmt_optional_number(risk_amount),
            phase,
            detail or "-",
        )

    def _send_telegram_safe(self, telegram_module, message, symbol, reply_markup=None):
        """Telegram gönderimini güvenli şekilde çalıştırır; analiz akışını düşürmez."""
        try:
            bot = telegram_module.TelegramBot()
            try:
                sent = bot.send(message, reply_markup=reply_markup)
            except TypeError:
                sent = bot.send(message)
            if not sent:
                self.logger.warning("Telegram send failed: %s", symbol)
            return sent
        except Exception:
            self.logger.exception("Telegram send hatasi: %s", symbol)
            return False

    def flush_telegram_notifications(self, join_timeout=0.5):
        """Kuyruktaki async Telegram gönderimlerini bitmesini bekler."""
        if not self._telegram_threads:
            return

        alive_threads = []
        for thread in self._telegram_threads:
            if thread.is_alive():
                thread.join(timeout=join_timeout)
            if thread.is_alive():
                alive_threads.append(thread)

        pending = len(alive_threads)
        self._telegram_threads = alive_threads
        if pending:
            self.logger.warning("Telegram flush timeout: pending_threads=%s", pending)

    def _apply_decision_to_signal(self, signal, decision):
        """Decision sonucunu sinyal metadatasina isler; yonu bozmaz."""
        action = (decision or {}).get("action")
        if action in ["EXECUTE", "EXECUTE_WITH_CAUTION"]:
            enriched = dict(signal or {})
            enriched["gated_by_decision"] = False
            enriched["decision_action"] = action
            return enriched

        enriched = dict(signal or {})
        enriched["gated_by_decision"] = True
        enriched["decision_action"] = action or "WAIT"
        return enriched

    def _resolve_trade_direction_from_decision(self, signal_action, decision_action):
        """Yeni/legacy decision aksiyonlarini LONG/SHORT/WAIT formatina normalize eder."""
        if decision_action in ["LONG", "SHORT"]:
            return decision_action

        if decision_action in ["EXECUTE", "EXECUTE_WITH_CAUTION"] and signal_action in ["LONG", "SHORT"]:
            return signal_action

        return "WAIT"

    def _signal_fingerprint(self, action, entry, risk):
        """Aynı setup tekrarlarını baskılamak için sade imza üretir."""
        return (
            action,
            round(float(entry.get("entry", 0.0)), 6),
            round(float(entry.get("stop_loss", 0.0)), 6),
            round(float((risk or {}).get("tp3", 0.0)), 6),
            round(float((risk or {}).get("rr", 0.0)), 2),
        )

    def _should_send_telegram_signal(self, symbol, action, entry, risk):
        dedup_enabled = bool(getattr(Config, "TELEGRAM_SIGNAL_DEDUP_ENABLED", True))
        if not dedup_enabled:
            return True

        cooldown_minutes = float(getattr(Config, "TELEGRAM_SIGNAL_COOLDOWN_MINUTES", 180))
        if cooldown_minutes <= 0:
            return True

        now_ts = time.time()
        cooldown_seconds = cooldown_minutes * 60.0
        fingerprint = self._signal_fingerprint(action, entry, risk)

        cached = self._telegram_signal_cache.get(symbol)
        if cached:
            age = now_ts - cached.get("timestamp", 0.0)
            if cached.get("fingerprint") == fingerprint and age < cooldown_seconds:
                return False

        self._telegram_signal_cache[symbol] = {
            "fingerprint": fingerprint,
            "timestamp": now_ts,
        }
        return True
