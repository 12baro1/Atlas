"""
engine.py
Atlas SMC Engine v3

Ana orkestrasyon katmanı: alt motorları modüler bir akışta birleştirir.
Kod İngilizce, açıklamalar Türkçe tutulmuştur.
"""

from importlib import import_module
import math
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
from manual_trade_service import ManualTradeService
from economic_news_engine import EconomicNewsFilter
from correlation_engine import CorrelationEngine
from core.market_structure_engine import MarketStructureEngine
from cisd_engine import CISDEngine
from decision_engine import DecisionEngine
from dynamic_tp_engine import DynamicTPEngine
from entry_confirmation_engine import EntryConfirmationEngine
from entry_engine import EntryEngine
from entry_optimizer import EntryOptimizer
from fvg_engine import FVGEngine
from htf_fvg_engine import HTFFVGEngine
from htf_orderblock_engine import HTFOrderBlockEngine
from killzone_engine import KillZoneEngine
from liquidity_engine import LiquidityEngine
from liquidity_sweep_engine import LiquiditySweepEngine
from institutional_engine import InstitutionalAnalysisEngine
from market_phase_engine import MarketPhaseEngine
from market_regime_engine import MarketRegimeEngine
from trade_quality_engine import TradeQualityEngine
from manual_trade_quality import ManualTradeQualityGate
from mitigation_engine import MitigationEngine
from mtf_engine import MTFEngine
from orderblock_engine import OrderBlockEngine
from orderbook_engine import OrderBookEngine
from ote_engine import OTEEngine
from position_manager import PositionManager
from premium_discount_engine import PremiumDiscountEngine
from risk_engine import RiskEngine
from rr_engine import RREngine
from scanner_engine import ScannerEngine
from session_filter import SessionFilter
from signal_engine import SignalEngine
from setup_quality_engine import SetupQualityEngine
from setup_reasoning_engine import SetupReasoningEngine
from atlas_main_engine import AtlasMainEngine, MotorProxy
from smt_engine import SMTDivergenceEngine
from statistics_engine import StatisticsEngine
from trade_manager import TradeManager
from trade_journal import TradeJournal
from trend_engine import TrendEngine
from trendline_engine import TrendlineEngine
from unicorn_engine import UnicornEngine
from volume_profile_engine import VolumeProfileEngine
from utils.structure_labels import label_swings
from strategy_lab import SevenStrategyLab


DYNAMIC_ANALYSIS_INPUT_KEYS = (
    "orderbook",
    "recent_trades",
    "open_interest",
    "funding_rate",
    "economic_events",
    "smt_universe",
)


def _has_dynamic_market_context(data):
    """Return True when a candle-only incremental cache could hide fresh inputs."""
    if not isinstance(data, dict):
        return False
    return any(bool(data.get(key)) for key in DYNAMIC_ANALYSIS_INPUT_KEYS)


def _tp1_already_reached(direction, current_price, tp1):
    """Return True when price has already crossed TP1 before the proposed entry."""
    try:
        current = float(current_price)
        target = float(tp1)
    except (TypeError, ValueError):
        return False
    if direction == "LONG":
        return current >= target
    if direction == "SHORT":
        return current <= target
    return False


def _tp1_touched_on_signal_candle(direction, candle, tp1):
    """Use the completed signal candle range, not only its close, for stale-order detection."""
    try:
        target = float(tp1)
        extreme = float(candle.high if direction == "LONG" else candle.low)
    except (AttributeError, TypeError, ValueError):
        return False
    if not math.isfinite(target) or not math.isfinite(extreme):
        return False
    return extreme >= target if direction == "LONG" else extreme <= target


class AtlasEngine:
    """Atlas'ın tüm analiz motorlarını yöneten ana sınıf."""

    def __setattr__(self, name, value):
        # Test/extension replacements remain attached to the central evidence bus.
        main_engine = self.__dict__.get("main_engine")
        if (
            main_engine is not None
            and name in main_engine.motors
            and value is not None
            and not isinstance(value, MotorProxy)
        ):
            value = main_engine.attach_motor(name, value)
        object.__setattr__(self, name, value)

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
        self.orderbook = OrderBookEngine()
        self.mitigation = MitigationEngine()
        self.fvg = FVGEngine()
        self.liquidity_sweep = LiquiditySweepEngine()
        self.breaker = BreakerBlockEngine()
        self.trendline = TrendlineEngine()

        # Faz, bağlam ve MTF motorları
        self.trend = TrendEngine()
        self.market_phase = MarketPhaseEngine()
        self.market_regime = MarketRegimeEngine()
        self.trade_quality = TradeQualityEngine()
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
        self.setup_reasoner = SetupReasoningEngine()
        self.state_engine = StateEngine(getattr(Config, "STATE_ENGINE_FILE", "atlas_state.json"))
        self.news_filter = EconomicNewsFilter()
        self.correlation = CorrelationEngine()
        self.cooldown = TradeCooldownEngine()
        self.learning = LearningEngine(getattr(Config, "LEARNING_ENGINE_FILE", "atlas_learning.json"))
        self.manual_quality_gate = ManualTradeQualityGate(Config)

        # Sinyal, risk ve operasyon motorları
        self.entry = EntryEngine()
        self.entry_optimizer = EntryOptimizer()
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
        self.manual_trade_service = ManualTradeService(
            journal=self.trade_journal,
            refresh_learning=self.refresh_learning,
        )
        self._warm_learning_index()
        self.scanner = ScannerEngine()
        self.statistics = StatisticsEngine()
        self.backtest = BacktestEngine()
        # Explicit specialist inventory: services/state containers are not motors.
        # Every registered motor is wrapped so calls publish evidence through the
        # single main authority instead of bypassing the shared evidence pool.
        specialist_motor_names = (
            "bos", "choch", "liquidity", "orderblocks", "orderbook",
            "mitigation", "fvg", "liquidity_sweep", "breaker", "trendline",
            "trend", "market_phase", "market_regime", "trade_quality", "mtf",
            "premium_discount", "killzone", "session", "ote",
            "htf_orderblock", "htf_fvg", "smt", "unicorn", "cisd",
            "volume_profile", "institutional", "entry", "entry_optimizer",
            "entry_confirmation", "confluence", "signal", "risk", "rr",
            "dynamic_tp", "setup_quality", "news_filter", "correlation",
            "cooldown", "learning",
        )
        self.main_engine = AtlasMainEngine(
            motors={name: getattr(self, name) for name in specialist_motor_names},
            setup_reasoner=self.setup_reasoner,
            decision_engine=self.decision,
        )
        for motor_name in specialist_motor_names:
            setattr(self, motor_name, self.main_engine.motors[motor_name])

    def analyze(self, data):
        """Route every market analysis through the single main engine."""
        return self.main_engine.analyze(data, pipeline=self._analyze_with_motors)

    def _analyze_with_motors(self, data):
        """Execute registered specialist motors and assemble their evidence."""
        self._validate_market_data(data)

        symbol = data.get("symbol", "UNKNOWN")
        candles = data["15m"]
        # Any fresh non-candle input can change the decision without a new 15m close.
        # Do not restore a candle-only cache when order flow, derivatives, news or
        # cross-market context is present, even if the order-book request failed.
        if (not _has_dynamic_market_context(data)) and bool(getattr(Config, "STATE_ENGINE_ENABLED", True)) and bool(getattr(Config, "INCREMENTAL_ANALYSIS_ENABLED", True)):
            cached = self._restore_incremental_if_unchanged(symbol, candles)
            if cached is not None:
                cached_analysis = cached.get("analysis") if isinstance(cached, dict) else None
                if cached_analysis:
                    self._reapply_learning_to_cached(cached_analysis)
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

        # LOOK-AHEAD GUARD (canli + backtest ortak kural):
        # Ust zaman dilimi mumlari yalnizca TAMAMEN KAPANDIKTAN sonra analize
        # girer. Olusmakta olan HTF mumunun OHLC'si ileriye donuk bilgi saklar.
        # Referans: son kapalı 15m mumunun KAPANIŞ zamanı. Canlı ve backtest
        # aynı karar anını kullanır; kapanış sınırındaki HTF mumları gecikmez,
        # oluşmakta olan HTF mumları da geleceğe dönük bilgi sızdıramaz.
        from timing import TF_PERIOD_MS, closed_htf_candles
        ref_ms = candles[-1].time + TF_PERIOD_MS["15m"] if candles else None
        if ref_ms is not None:
            h1 = closed_htf_candles(h1, ref_ms, "1h") if h1 else h1
            weekly = closed_htf_candles(weekly, ref_ms, "1w")
            daily = closed_htf_candles(daily, ref_ms, "1d")
            h4 = closed_htf_candles(h4, ref_ms, "4h")
            # _build_* fonksiyonlari data dict'inden HTF okuduğu için dict'i de
            # kırpılmış sürümle güncelle: SMT/unicorn/CISD/VPoS aynı kurala ticks.
            data = dict(data)
            data["1h"] = h1
            data["4h"] = h4
            data["1d"] = daily
            data["1w"] = weekly

        tf_analysis = {
            "entry": self._analyze_timeframe(candles, timeframe="15m"),
            "weekly": self._analyze_timeframe(weekly, timeframe="1w"),
            "daily": self._analyze_timeframe(daily, timeframe="1d"),
            "h4": self._analyze_timeframe(h4, timeframe="4h"),
            "h1": self._analyze_timeframe(h1, timeframe="1h") if h1 else {"pivots": [], "structure": []},
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

        market_regime_state = self.market_regime.analyze(h4)
        context_state["market_regime"] = market_regime_state

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
        orderbook_state = self.orderbook.analyze(
            data.get("orderbook"),
            direction=context_state["mtf"].get("entry", "NONE"),
            now_ms=int(time.time() * 1000),
            trades=data.get("recent_trades"),
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
            liquidity_layers=structure_state.get("liquidity_layers"),
            internal_structure=structure_state.get("internal_structure"),
            external_structure=structure_state.get("external_structure"),
            market_regime=market_regime_state,
            orderbook=orderbook_state,
            h4_orderblocks=context_state.get("h4_orderblocks", []),
            daily_orderblocks=context_state.get("daily_orderblocks", []),
            h4_fvg=context_state.get("h4_fvg", []),
            daily_fvg=context_state.get("daily_fvg", []),
            inducement=structure_state.get("inducement"),
            trendline_liquidity=structure_state.get("trendline_liquidity", []),
        )

        # Seven raw setups (SMC included) share one filter and one final selector.
        smc_raw = {
            "entry": execution_state.get("entry") or {},
            "risk": execution_state.get("risk") or {},
            "dynamic_tp": execution_state.get("dynamic_tp") or {},
            "signal": execution_state.get("signal") or {},
            "analysis": {
                "entry": execution_state.get("entry") or {},
                "setup_quality": execution_state.get("setup_quality") or {},
            },
        }
        strategy_report = SevenStrategyLab().analyze(data, smc_result=smc_raw)
        selected = strategy_report.get("selected")
        if isinstance(selected, dict):
            selected_risk = dict(selected.get("risk_plan") or {})
            selected_entry = dict(execution_state.get("entry") or {})
            selected_entry.update({
                "valid": True,
                "direction": selected["direction"],
                "entry_type": selected["entry_type"],
                "entry": selected["entry"],
                "stop_loss": selected["stop_loss"],
                "reason": "Selected by the shared seven-strategy decision",
                "entry_reason_code": "SHARED_STRATEGY_SELECTION",
            })
            selected_risk.update({
                "entry": selected["entry"], "stop_loss": selected["stop_loss"],
                "tp1": selected["tp1"], "tp2": selected["tp2"], "tp3": selected["tp3"],
                "risk_setup_valid": True,
            })
            execution_state["entry"] = selected_entry
            execution_state["risk"] = selected_risk
            execution_state["dynamic_tp"] = {
                "tp1": selected["tp1"], "tp2": selected["tp2"], "tp3": selected["tp3"],
                "synthetic_targets": selected.get("target_model") == "R_MULTIPLE_FALLBACK",
            }
            execution_state["rr"] = {
                "rr": selected.get("rr_tp1"),
                "weighted_rr": selected_risk.get("weighted_rr"),
                "weighted_net_rr": selected_risk.get("weighted_net_rr"),
                "target_max_rr": selected_risk.get("target_max_rr"),
                "partial_exit_weights": selected.get("partial_exit_weights") or {},
            }
            execution_state["signal"] = {
                **(execution_state.get("signal") or {}),
                "signal": selected["direction"],
                "confidence": selected.get("strength", 0),
                "strength": selected.get("strength", 0),
                "grade": "SELECTED",
                "decision_action": "EXECUTE",
                "gated_by_decision": False,
                "wait_reason": None,
                "strategy_id": selected.get("strategy_id"),
            }
            decision_state = {
                "action": "EXECUTE", "signal": selected["direction"],
                "reason": "Best setup selected after the shared filter",
                "decision_authority": "SEVEN_STRATEGY_SELECTOR",
                "selected_strategy_id": selected.get("strategy_id"),
            }
        else:
            execution_state["entry"] = {
                **(execution_state.get("entry") or {}),
                "valid": False, "direction": "WAIT", "entry": None, "stop_loss": None,
                "reason": "No setup passed the shared filter",
            }
            execution_state["risk"] = {}
            execution_state["dynamic_tp"] = {}
            execution_state["rr"] = {}
            execution_state["signal"] = {
                **(execution_state.get("signal") or {}),
                "signal": "WAIT", "confidence": 0, "decision_action": "SKIP",
                "gated_by_decision": True, "wait_reason": "No setup passed the shared filter",
            }
            decision_state = {
                "action": "SKIP", "signal": "WAIT",
                "reason": "No setup passed the shared filter",
                "decision_authority": "SEVEN_STRATEGY_SELECTOR",
                "selected_strategy_id": None,
            }

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
            market_regime_state=market_regime_state,
        )

        analysis["strategy_lab"] = strategy_report

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
            "decision": decision_state,,
            "strategy_lab": strategy_report
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

    def _warm_learning_index(self):
        """Process başlangıcında journal'daki kapanmış kayıtlardan index kurar.

        Hangı entrypoint kullanılırsa kullanılsın (main.py, telegram, testler,
        betikler) learning index'in hazır olmasını garantiler. Hata olursa sessiz
        atlanır; atlas_learning.json'daki legacy bucket'lardan kurulan index
        zaten hazırdır.
        """
        try:
            if not bool(getattr(Config, "LEARNING_ENGINE_ENABLED", True)):
                return None
            return self.refresh_learning()
        except Exception:
            self.logger.exception("Learning index warm-up basarisiz.")
            return None

    def refresh_learning(self, symbol=None):
        """Kapanmış işlemlerden öğrenme indeksini güvenli kaynak önceliğiyle yeniler.

        Varsayılan olarak kullanıcının gerçekten açıp kapattığı manuel işlemler
        birincildir. Manuel veri yoksa scanner tarafından takip edilen gerçek
        işlemler, onlar da yoksa teorik sinyal sonuçları kullanılır. Böylece
        aynı sinyalin teorik sonucu gerçek kullanıcı sonucunu gölgeleyemez.
        """
        if not bool(getattr(Config, "LEARNING_ENGINE_ENABLED", True)):
            return None
        if self.trade_journal is None:
            return None

        signal_records = self.trade_journal.learning_records(source="signal", symbol=symbol)
        tracked_records = self.trade_journal.learning_records(source="tracked", symbol=symbol)
        manual_records = self.trade_journal.learning_records(source="manual", symbol=symbol)

        if bool(getattr(Config, "LEARNING_MANUAL_TRADE_PRIMARY", True)):
            source_order = (
                ("manual", manual_records),
                ("tracked", tracked_records),
                ("signal", signal_records),
            )
        else:
            source_order = (
                ("tracked", tracked_records),
                ("signal", signal_records),
                ("manual", manual_records),
            )
        source, records = next(
            ((name, rows) for name, rows in source_order if rows),
            (None, []),
        )
        if not records:
            # Geçerli kayıt kalmadıysa eski öğrenme index'ini tutma; aksi
            # halde EXPIRED/PENDING sinyallerden kalma istatistikler etkili olur.
            self.learning.stats["source"] = None
            self.learning.stats["feed_meta"] = {
                "signal": 0, "tracked": 0, "manual": 0, "selected": None,
            }
            return self.learning.rebuild_from_records([])

        self.learning.stats["source"] = source
        self.learning.stats["feed_meta"] = {
            "signal": len(signal_records),
            "tracked": len(tracked_records),
            "manual": len(manual_records),
            "selected": source,
        }
        return self.learning.rebuild_from_records(records)

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
                return existing

        analysis = result_payload.get("analysis") or {}
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
            "entry_type": (analysis.get("entry") or {}).get("entry_type") or "LIMIT",
        }
        journal_trade = self.trade_journal.register_trade(
            trade, analysis=result_payload, symbol=symbol,
            metadata={"origin": "live_scanner", "decision_action": result_payload.get("decision", {}).get("action")},
        )

        # Teorik sinyal sonucu (SIGNAL OUTCOME) kaydı: TP/SL çözümlenmesi için.
        # Aynı sembol+yönde açık bir kayıt varsa tekrar açılmaz.
        opened_at = result_payload.get("decision", {}).get("executed_at") or int(time.time() * 1000)
        analysis = result_payload.get("analysis") or {}
        setup_quality = analysis.get("setup_quality") or {}
        setup_fingerprint = (
            setup_quality.get("setup_fingerprint")
            or (analysis.get("setup") or {}).get("fingerprint")
            or None
        )
        setup_features = list(setup_quality.get("features") or [])
        signal_id = None
        existing = [
            o
            for o in self.trade_journal.open_signal_outcomes(symbol=symbol)
            if o.get("direction") == side
        ]
        if existing:
            signal_id = existing[0].get("signal_id")
        else:
            try:
                outcome = self.trade_journal.register_signal_outcome(
                    symbol=symbol,
                    direction=side,
                    timeframe="15m",
                    entry=entry,
                    stop_loss=stop_loss,
                    tp1=risk.get("tp1") or (result_payload.get("dynamic_tp") or {}).get("tp1"),
                    tp2=risk.get("tp2") or (result_payload.get("dynamic_tp") or {}).get("tp2"),
                    tp3=risk.get("tp3") or (result_payload.get("dynamic_tp") or {}).get("tp3"),
                    rr=trade["rr"],
                    confidence=trade["confidence"],
                    grade=(analysis.get("signal") or {}).get("grade"),
                    market_phase=trade["market_phase"],
                    setup_fingerprint=setup_fingerprint,
                    opened_at=opened_at,
                    payload={
                        "origin": "live_scanner",
                        "decision_action": result_payload.get("decision", {}).get("action"),
                        "setup_type": (analysis.get("setup") or {}).get("type")
                        or setup_quality.get("setup")
                        or None,
                        "setup_features": setup_features,
                        "learning": setup_quality.get("learning") or {},
                        "setup_quality": setup_quality,
                        "motor_diagnostics": (analysis.get("motor_diagnostics") or {}),
                        "execution_costs": {
                            "entry_type": (analysis.get("entry") or {}).get("entry_type") or "LIMIT",
                            "maker_fee_rate": risk.get("maker_fee_rate"),
                            "taker_fee_rate": risk.get("taker_fee_rate"),
                            "spread_rate": risk.get("spread_rate"),
                            "slippage_rate": risk.get("slippage_rate"),
                            "partial_exit_weights": risk.get("partial_exit_weights"),
                            "round_trip_cost_rate": risk.get("round_trip_cost_rate"),
                            "spread_buffer": risk.get("spread_buffer"),
                            "slippage_buffer": risk.get("slippage_buffer"),
                            "model": risk.get("cost_model") or "per_fill_maker_taker_with_market_friction",
                        },
                        "decision": result_payload.get("decision") or {},
                    },
                )
                signal_id = (outcome or {}).get("signal_id")
            except Exception:
                self.logger.exception("register_signal_outcome hatasi | symbol=%s signal=%s", symbol, side)

        if isinstance(journal_trade, dict) and signal_id:
            journal_trade["signal_id"] = signal_id
            try:
                self.trade_journal._persist_trade(journal_trade)
            except Exception:
                pass
        return journal_trade

    def _restore_incremental_if_unchanged(self, symbol, candles):
        """Return cached analysis when the latest 15m candle was already processed."""
        if not self.state_engine.has_new_entry_candle(symbol, candles):
            cached = self.state_engine.restore_cached_result(symbol)
            if cached is not None:
                self.logger.info("Incremental cache hit | symbol=%s last_candle=%s", symbol, candles[-1].time if candles else None)
                return cached
        return None

    def _reapply_learning_to_cached(self, cached_analysis):
        """Cache'ten dönen analize güncel learning index'i yeniden uygular.

        Incremental cache sırasında zaman geçebilir; arada yeni trade'ler
        kapanıp learning index değişebilir. Cache'teki setup_quality'nin
        eski/boş learning meta'sını taşıması yerine güncel öğrenme etkisi
        yeniden hesaplanıp hem setup_quality hem de sinyal meta'sı güncellenir.
        """
        if not bool(getattr(Config, "LEARNING_ENGINE_ENABLED", True)):
            return cached_analysis
        setup_quality = cached_analysis.get("setup_quality") or {}
        if not isinstance(setup_quality, dict) or not setup_quality.get("module_scores"):
            return cached_analysis
        phase = (cached_analysis.get("market_phase") or {}).get("phase") if isinstance(cached_analysis.get("market_phase"), dict) else None
        adjusted = self.learning.apply_to_setup_quality(
            setup_quality,
            market_phase=phase,
            timeframe="15m",
        )
        cached_analysis["setup_quality"] = adjusted
        signal = cached_analysis.get("signal")
        if isinstance(signal, dict):
            signal["learning"] = adjusted.get("learning") or {}
        self._log_learning_live(
            setup_quality.get("score"),
            adjusted,
            context="cache_hit",
        )
        return cached_analysis

    def _log_learning_live(self, setup_quality_before, adjusted, context="live"):
        """Canlı öğrenme etkisini uçtan uca tek satırda loglar."""
        learning_info = (adjusted or {}).get("learning") or {}
        adjustments = (adjusted or {}).get("learning_adjustments") or {}
        active_adjustments = {
            name: round(float(value), 4)
            for name, value in adjustments.items()
            if float(value) != 1.0
        }
        self.logger.info(
            "LEARNING LIVE | context=%s matched=%s level=%s samples=%s "
            "historical_edge=%.4f reliability=%.4f expected_r=%.4f "
            "learning_adjustment=%s setup_quality_before=%s setup_quality_after=%s "
            "score_delta=%+d no_match_reason=%s",
            context,
            learning_info.get("matched"),
            learning_info.get("level"),
            int(learning_info.get("sample_count") or 0),
            float(learning_info.get("historical_edge") or 0),
            float(learning_info.get("reliability") or 0),
            float(learning_info.get("expected_r") or 0),
            active_adjustments or "-",
            setup_quality_before,
            (adjusted or {}).get("score"),
            int(learning_info.get("score_delta") or 0),
            learning_info.get("no_match_reason") or "-",
        )

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

    def _analyze_timeframe(self, candles, timeframe="unknown"):
        """Tek zaman dilimi için pivot, etiket, BOS ve CHoCH üretir."""
        engine = self.main_engine.attach_motor(
            "market_structure", self.structure_engine_cls()
        )

        engine.find_pivots(candles)
        engine.calculate_strength(candles)
        engine.merge_pivots()
        engine.filter_noise()

        pivots = engine.validate_sequence()
        structure = self.choch.detect(self.bos.detect(label_swings(pivots), candles=candles, timeframe=timeframe))

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
        trendline_sweep_state = self.trendline.serialize(trendline_sweep, candles=candles)

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
                    "direction": item.get("direction"),
                    "event_id": item.get("event_id"),
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
                "event_id": item.get("event_id"),
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
            liquidity_sweep=liquidity_sweep,
        )
        trend = self.trend.calculate(mtf, structure=h4_structure)

        daily_orderblocks = self.mitigation.detect(daily, self.orderblocks.detect(daily, daily_structure))
        h4_orderblocks = self.mitigation.detect(h4, self.orderblocks.detect(h4, h4_structure))

        # OTE, 15m verisinin tüm tarihsel tepe/diplerinden değil,
        # son onaylı 4H impuls bacağından hesaplanır.
        ote_high, ote_low = self._h4_ote_range(h4_structure, mtf.get("entry", "NONE"))
        ote = self.ote.detect(
            ote_high,
            ote_low,
            current_price,
            mtf.get("entry", "NONE"),
        )

        htf_orderblock = self.htf_orderblock.detect(
            current_price,
            daily_orderblocks,
            h4_orderblocks,
            direction=mtf.get("entry", "NONE"),
        )
        h4_fvg = self.fvg.detect(h4)
        daily_fvg = self.fvg.detect(daily)
        htf_fvg = self.htf_fvg.detect(
            h4_fvg,
            daily_fvg,
            current_price=current_price,
            direction=mtf.get("entry", "NONE"),
        )

        market_phase = self.market_phase.detect(
            structure=entry_structure,
            trend=trend,
            liquidity_sweep=liquidity_sweep,
            fvg=fvg,
            orderblocks=orderblocks,
            premium_discount=premium_discount,
            mtf=mtf,
            candles=candles,
            timeframe="15m",
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
            "h4_fvg": h4_fvg,
            "daily_fvg": daily_fvg,
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
        liquidity_layers=None,
        internal_structure=None,
        external_structure=None,
        market_regime=None,
        orderbook=None,
        h4_orderblocks=None,
        daily_orderblocks=None,
        h4_fvg=None,
        daily_fvg=None,
        inducement=None,
        trendline_liquidity=None,
    ):
        """Entry, confirmation, confluence, signal, risk ve RR katmanını üretir."""
        entry = self.entry.generate(
            mtf,
            entry_structure,
            fvg,
            orderblocks,
            current_price=candles[-1].close if candles else None,
            allow_structure_fallback=bool(getattr(Config, "ENTRY_ALLOW_STRUCTURE_DIRECTION_FALLBACK", False)),
            candles=candles,
            liquidity_sweep=liquidity_sweep,
            ote=ote,
            market_regime=market_regime,
        )
        optimization = self.entry_optimizer.optimize(
            entry=entry,
            current_price=candles[-1].close if candles else None,
            trend=trend,
            liquidity_sweep=liquidity_sweep,
            ote=ote,
            market_phase=market_phase,
            market_regime=market_regime,
            htf_orderblock=htf_orderblock,
            htf_fvg=htf_fvg,
            smt=smt,
            unicorn=unicorn,
            cisd=cisd,
            volume_profile=volume_profile,
            institutional=institutional,
            orderbook=orderbook,
            correlation=correlation,
            breaker=breaker,
            trendline_sweep=trendline_sweep,
            ifvg=ifvg,
            eqh_eql=eqh_eql,
            internal_structure=internal_structure,
            external_structure=external_structure,
            current_index=len(candles) - 1 if candles else None,
        )
        # Build independent LONG/SHORT POI scenarios from the full motor context.
        # Secondary evidence shapes the scenario; it is not a score-based veto.
        reasoning = self.main_engine.build_setup(
            base_entry=entry,
            mtf=mtf,
            structure=entry_structure,
            fvg=fvg,
            orderblocks=orderblocks,
            current_price=candles[-1].close if candles else None,
            candles=candles,
            liquidity_sweep=liquidity_sweep,
            ote=ote,
            market_regime=market_regime,
            htf_orderblock=htf_orderblock,
            htf_fvg=htf_fvg,
            smt=smt,
            unicorn=unicorn,
            cisd=cisd,
            volume_profile=volume_profile,
            institutional=institutional,
            orderbook=orderbook,
            correlation=correlation,
            market_phase=market_phase,
            liquidity=liquidity,
            external_structure=external_structure,
            higher_timeframe_orderblocks=list(h4_orderblocks or []) + list(daily_orderblocks or []),
            higher_timeframe_fvg=list(h4_fvg or []) + list(daily_fvg or []),
            optimization=optimization,
            breaker=breaker,
            ifvg=ifvg,
            trendline_sweep=trendline_sweep,
            eqh_eql=eqh_eql,
            inducement=inducement,
            premium_discount=premium_discount,
            internal_structure=internal_structure,
            trendline_liquidity=trendline_liquidity,
        )
        setup_candidates = reasoning.get("candidates", [])
        selected_candidate = reasoning.get("selected")
        if isinstance(selected_candidate, dict):
            selected_candidate["optimization"] = optimization
            selected_candidate["setup_reasoning"] = {
                "selected_id": selected_candidate.get("setup_candidate_id"),
                "candidate_count": len(setup_candidates),
                "reason": reasoning.get("reason"),
                "thesis": selected_candidate.get("reasoning"),
                "supporting_evidence": selected_candidate.get("supporting_evidence", []),
                "opposing_evidence": selected_candidate.get("opposing_evidence", []),
                "supporting_event_ids": selected_candidate.get("supporting_event_ids", []),
                "opposing_event_ids": selected_candidate.get("opposing_event_ids", []),
                "market_context": selected_candidate.get("market_context", []),
            }
            # The main engine's selected candidate is the only setup.
            # Never fall back to a second, independently-created EntryEngine setup.
            entry = selected_candidate
        else:
            entry = {
                "valid": False,
                "direction": "WAIT",
                "entry": None,
                "stop_loss": None,
                "reason": reasoning.get("reason") or "Main engine produced no setup",
                "entry_reason_code": "NO_MAIN_ENGINE_SETUP",
                "setup_reasoning": {
                    "selected_id": None,
                    "candidate_count": len(setup_candidates),
                    "reason": reasoning.get("reason"),
                    "thesis": "No setup selected by AtlasMainEngine.",
                    "supporting_evidence": [],
                    "opposing_evidence": [],
                },
            }

        confirmation = self.entry_confirmation.confirm(
            mtf, entry_structure, fvg, entry,
            current_price=candles[-1].close if candles else None,
        )
        orderbook = orderbook or {"active": False, "market_entry_allowed": True}
        entry["orderbook"] = orderbook
        entry["optimization"] = optimization
        if entry.get("valid") and (orderbook.get("active") or orderbook.get("trade_flow_active")):
            entry_type = str(entry.get("entry_type") or "").upper()
            if orderbook.get("opposing") or (entry_type == "MARKET" and not orderbook.get("market_entry_allowed", True)):
                # Microstructure conflict changes execution style first; it does
                # not erase a structurally valid POI setup by itself.
                current = float(candles[-1].close) if candles else None
                price = float(entry.get("entry")) if entry.get("entry") is not None else None
                direction = str(entry.get("direction") or "").upper()
                can_fall_back_to_limit = bool(
                    entry.get("poi_zone") and current is not None and price is not None
                    and ((direction == "LONG" and price < current) or (direction == "SHORT" and price > current))
                )
                if can_fall_back_to_limit:
                    entry["entry_type"] = "LIMIT"
                    entry["requires_pullback"] = True
                    entry["entry_type_reason"] = "Order-flow karşı baskısı nedeniyle daha iyi POI LIMIT girişi"
                    entry.setdefault("checks", []).append("! Microstructure: MARKET yerine LIMIT seçildi")
                else:
                    # Keep the structurally valid setup. If the optimizer's
                    # price is not on the pullback side, anchor the LIMIT at
                    # the favorable edge of the already selected POI.
                    zone = entry.get("poi_zone") if isinstance(entry.get("poi_zone"), dict) else {}
                    try:
                        edge = float(zone.get("low" if direction == "LONG" else "high"))
                        stop = float(entry.get("stop_loss"))
                        edge_valid = edge > 0 and (
                            (direction == "LONG" and edge > stop and edge < current)
                            or (direction == "SHORT" and edge < stop and edge > current)
                        )
                    except (TypeError, ValueError, OverflowError):
                        edge_valid = False
                    if edge_valid:
                        entry["entry"] = edge
                    entry["entry_type"] = "LIMIT"
                    entry["requires_pullback"] = True
                    entry["entry_type_reason"] = "Order-flow karşı baskısı: geçerli POI LIMIT tercih edildi"
                    entry.setdefault("checks", []).append("! Order-flow çatışması sinyali iptal etmedi; LIMIT'e çevrildi")
                    confirmation["execution_advisory"] = "ORDERBOOK_COUNTERPRESSURE"
            else:
                entry.setdefault("checks", []).append(
                    "✓ Order book yönü destekli" if orderbook.get("supportive") else "✓ Order book engel oluşturmuyor"
                )

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
        setup_quality_before = setup_quality.get("score")
        if bool(getattr(Config, "LEARNING_ENGINE_ENABLED", True)):
            setup_quality = self.learning.apply_to_setup_quality(
                setup_quality,
                market_phase=(market_phase or {}).get("phase"),
                timeframe="15m",
            )
        self._log_learning_live(setup_quality_before, setup_quality, context="live")
        setup_quality["external_risk_filters"] = {
            "news_filter": news_filter or {},
            "correlation": correlation or {},
            "cooldown": cooldown or {},
            "orderbook": orderbook,
        }
        # News and duplicate-position cooldown are enforced once, by
        # AtlasMainEngine after the single decision. They remain visible here
        # as diagnostics, but do not create a second setup-quality veto.
        soft_external_warnings = [
            name for name in ("correlation", "orderbook")
            if not (setup_quality["external_risk_filters"].get(name) or {}).get("trade_allowed", True)
        ]
        if soft_external_warnings:
            setup_quality.setdefault("warnings", []).extend(
                f"{name}: counterpressure retained as entry evidence" for name in soft_external_warnings
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
            current_index=len(candles) - 1 if candles else None,
        )

        # The final target engine receives the same complete structural context
        # used to construct the selected POI: LTF + HTF imbalances/blocks and
        # internal + external structure. Trendline pools remain liquidity inputs.
        tp_fvg = list(fvg or []) + list(h4_fvg or []) + list(daily_fvg or [])
        tp_orderblocks = list(orderblocks or []) + list(h4_orderblocks or []) + list(daily_orderblocks or [])
        tp_structure = list(entry_structure or []) + list(external_structure or [])
        dynamic_tp = self._calculate_dynamic_tp(
            entry=entry,
            liquidity=liquidity,
            fvg=tp_fvg,
            orderblocks=tp_orderblocks,
            candles=candles,
            structure=tp_structure,
            trendline_liquidity=trendline_liquidity,
        )

        # Require at least one real structural objective. Missing TP2/TP3
        # remain empty; TradeQualityEngine checks the final available target RR.
        if entry.get("valid") and not any(dynamic_tp.get(key) is not None for key in ("tp1", "tp2", "tp3")):
            entry["valid"] = False
            entry["reason"] = dynamic_tp.get("reason") or "No valid structural TP targets"
            entry["entry_reason_code"] = "NO_STRUCTURAL_TARGETS"
            entry.setdefault("checks", []).append("✗ No valid structural TP targets; setup blocked")
            confirmation["confirmed"] = False
            confirmation["reason"] = "No valid structural TP targets; wait for a clearer liquidity objective"

        # TP1 can be crossed while a LIMIT entry is still waiting for a pullback.
        # Preserve that limit setup; only block a late market/confirmation entry.
        current_price = candles[-1].close if candles else None
        signal_candle = candles[-1] if candles else None
        target_exclusion_price = None
        tp1_reached = (
            entry.get("valid")
            and (
                _tp1_touched_on_signal_candle(entry.get("direction"), signal_candle, dynamic_tp.get("tp1"))
                if signal_candle is not None
                else _tp1_already_reached(entry.get("direction"), current_price, dynamic_tp.get("tp1"))
            )
        )
        entry_type = str(entry.get("entry_type") or "").upper()
        if tp1_reached and entry_type != "LIMIT":
            entry["valid"] = False
            entry["reason"] = "TP1 already reached; do not chase with a market entry"
            entry["entry_reason_code"] = "TP1_ALREADY_REACHED"
            entry.setdefault("checks", []).append("✗ TP1 already reached; market entry blocked")
            confirmation["confirmed"] = False
            confirmation["reason"] = "TP1 already reached; wait for a fresh setup"
        elif tp1_reached and entry_type == "LIMIT":
            # A LIMIT pullback can remain valid after price has traded through
            # its original TP1. Remove targets crossed by the completed signal
            # candle and rebuild from remaining structural liquidity.
            try:
                target_exclusion_price = float(
                    signal_candle.high if entry.get("direction") == "LONG" else signal_candle.low
                )
            except (AttributeError, TypeError, ValueError, OverflowError):
                target_exclusion_price = current_price
            refreshed_targets = self._calculate_dynamic_tp(
                entry=entry,
                liquidity=liquidity,
                fvg=fvg,
                orderblocks=orderblocks,
                candles=candles,
                structure=entry_structure,
                trendline_liquidity=trendline_liquidity,
                exclude_targets_through=target_exclusion_price,
            )
            if any(refreshed_targets.get(key) is not None for key in ("tp1", "tp2", "tp3")):
                dynamic_tp = refreshed_targets
                entry["tp_rebased_after_target_touch"] = True
                entry["tp_target_exclusion_price"] = target_exclusion_price
                entry.setdefault("checks", []).append(
                    "! TP1 önceden görüldü; LIMIT korunarak kalan yapısal hedefler yeniden hesaplandı"
                )
            else:
                entry["valid"] = False
                entry["reason"] = "TP1 reached before LIMIT fill and no remaining structural target"
                entry["entry_reason_code"] = "TP1_ALREADY_REACHED_NO_REMAINING_TARGET"
                entry.setdefault("checks", []).append(
                    "✗ TP1 geçildi ve kalan yapısal hedef yok; LIMIT geçersiz"
                )
                confirmation["confirmed"] = False
                confirmation["reason"] = entry["reason"]

        risk = self._calculate_risk(entry, dynamic_tp, volume_profile, institutional, candles=candles)

        # Profesyonel SMC kalitesi: SL otomatik olarak genişletildiyse (AUTO_EXPAND)
        # ilk TP hesabı orijinal/dar SL'e göre yapılmıştı; yeni mesafe ile gerçek
        # RR bozulur. TP'ler yeni SL'e göre yeniden kurulur ve risk yeniden hesaplanır,
        # böylece SL ile TP arasındaki asimetri (çoğunlukla 1R vs 3R) korunur.
        if isinstance(risk, dict) and risk.get("risk_setup_valid") is True and risk.get("stop_adjusted"):
            expanded_stop = risk.get("stop_loss")
            original_stop = entry.get("stop_loss")
            if expanded_stop is not None and original_stop is not None and abs(expanded_stop - original_stop) > 1e-12:
                dynamic_tp = self._calculate_dynamic_tp(
                    entry=entry,
                    liquidity=liquidity,
                    fvg=tp_fvg,
                    orderblocks=tp_orderblocks,
                    candles=candles,
                    structure=tp_structure,
                    trendline_liquidity=trendline_liquidity,
                    stop_price=expanded_stop,
                    exclude_targets_through=target_exclusion_price,
                )
                risk = self._calculate_risk(entry, dynamic_tp, volume_profile, institutional, candles=candles)
                self.logger.info(
                    "Dynamic TP rebuilt after stop expand | stop=%s tp1=%s tp2=%s tp3=%s",
                    expanded_stop,
                    dynamic_tp.get("tp1"),
                    dynamic_tp.get("tp2"),
                    dynamic_tp.get("tp3"),
                )
        # The main authority reconciles the structural stop, final risk stop and
        # selected structural TP ladder before any quality gate or signal consumes them.
        final_geometry = self.main_engine.finalize_setup_geometry(entry, risk, dynamic_tp)
        entry = final_geometry["entry"]
        risk = final_geometry["risk"]
        dynamic_tp = final_geometry["targets"]

        rr = self.rr.evaluate(risk) if risk is not None else None

        trade_quality = self.trade_quality.evaluate(
            entry=entry,
            confirmation=confirmation,
            mtf=mtf,
            trend=trend,
            liquidity_sweep=liquidity_sweep,
            ote=ote,
            market_regime=market_regime,
            dynamic_tp=dynamic_tp,
            risk=risk,
            current_price=candles[-1].close if candles else None,
            candles=candles,
            minimum_rr=float(getattr(Config, "MINIMUM_RR", 3.0)),
            smt=smt,
            unicorn=unicorn,
            cisd=cisd,
            volume_profile=volume_profile,
            institutional=institutional,
            market_phase=market_phase,
            setup_quality=setup_quality,
            entry_structure=entry_structure,
            liquidity_layers=liquidity_layers,
            eqh_eql=eqh_eql,
        )

        # Candidate reasoning replaces vote/score aggregation.
        setup_consensus = {}

        analysis_for_signal = {
            "entry": entry,
            "setup_consensus": setup_consensus,
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
            "trade_quality": trade_quality,
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
            "trade_quality": trade_quality,
            "setup_consensus": setup_consensus,
            "setup_candidates": setup_candidates,
            "orderbook": orderbook,
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
        market_regime_state=None,
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
            "market_regime": market_regime_state or context_state.get("market_regime", {}),
            "trade_quality": execution_state.get("trade_quality", {}),
            "setup_consensus": execution_state.get("setup_consensus", {}),
            "setup_candidates": execution_state.get("setup_candidates", []),
            "setup_reasoning": (execution_state.get("entry") or {}).get("setup_reasoning", {}),
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
            "setup": {
                "fingerprint": (execution_state.get("setup_quality") or {}).get("setup_fingerprint"),
                "features": (execution_state.get("setup_quality") or {}).get("features", []),
                "type": (execution_state.get("setup_quality") or {}).get("setup") or None,
            },
            "motor_diagnostics": {
                "entry_optimizer": (execution_state.get("entry") or {}).get("entry_optimizer", {}),
                "confirmation_profile": (execution_state.get("entry") or {}).get("confirmation_profile", {}),
                "motor_outputs": {
                    "mtf": {
                        "entry": (context_state.get("mtf") or {}).get("entry"),
                        "weekly": (context_state.get("mtf") or {}).get("weekly"),
                        "daily": (context_state.get("mtf") or {}).get("daily"),
                        "h4": (context_state.get("mtf") or {}).get("h4"),
                        "entry_source": (context_state.get("mtf") or {}).get("entry_source"),
                    },
                    "trend": context_state.get("trend") or {},
                    "liquidity_sweep": structure_state.get("liquidity_sweep") or {},
                    "smt": {
                        "active": (smt_state or {}).get("active"),
                        "direction": (smt_state or {}).get("direction"),
                        "confidence": (smt_state or {}).get("confidence"),
                        "timeframes": (smt_state or {}).get("timeframes"),
                    },
                    "unicorn": {
                        "active": (unicorn_state or {}).get("active"),
                        "direction": (unicorn_state or {}).get("direction"),
                        "confidence": (unicorn_state or {}).get("confidence"),
                        "best_timeframe": ((unicorn_state or {}).get("best") or {}).get("timeframe"),
                    },
                    "cisd": {
                        "active": (cisd_state or {}).get("active"),
                        "direction": (cisd_state or {}).get("direction"),
                        "confidence": (cisd_state or {}).get("confidence"),
                        "best_timeframe": ((cisd_state or {}).get("best") or {}).get("timeframe"),
                    },
                    "volume_profile": {
                        "active": (volume_profile_state or {}).get("active"),
                        "direction": (volume_profile_state or {}).get("direction"),
                        "confidence": (volume_profile_state or {}).get("confidence"),
                        "best_timeframe": ((volume_profile_state or {}).get("best") or {}).get("timeframe"),
                        "source": ((volume_profile_state or {}).get("best") or {}).get("source"),
                        "is_proxy": ((volume_profile_state or {}).get("best") or {}).get("is_proxy"),
                    },
                    "institutional": {
                        "active": (institutional_state or {}).get("active"),
                        "direction": (institutional_state or {}).get("direction"),
                        "confidence": (institutional_state or {}).get("confidence"),
                        "cvd_source": ((institutional_state or {}).get("cvd") or {}).get("source"),
                        "cvd_is_proxy": ((institutional_state or {}).get("cvd") or {}).get("is_proxy"),
                        "cvd_timestamp_validated": ((institutional_state or {}).get("cvd") or {}).get("timestamp_validated"),
                        "open_interest_active": ((institutional_state or {}).get("open_interest") or {}).get("active"),
                        "funding_active": ((institutional_state or {}).get("funding_rate") or {}).get("active"),
                    },
                    "orderbook": {
                        "active": ((execution_state.get("entry") or {}).get("orderbook") or {}).get("active"),
                        "imbalance": ((execution_state.get("entry") or {}).get("orderbook") or {}).get("imbalance"),
                        "spread_pct": ((execution_state.get("entry") or {}).get("orderbook") or {}).get("spread_pct"),
                        "trade_count": ((execution_state.get("entry") or {}).get("orderbook") or {}).get("trade_count"),
                    },
                },
                "data_sources": {
                    "institutional_cvd": ((institutional_state or {}).get("cvd") or {}).get("source"),
                    "institutional_cvd_is_proxy": ((institutional_state or {}).get("cvd") or {}).get("is_proxy"),
                    "volume_profile": ((volume_profile_state or {}).get("best") or volume_profile_state or {}).get("source"),
                    "orderbook": (execution_state.get("entry") or {}).get("orderbook", {}).get("source"),
                },
            },
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
        payload["analysis_timestamp_ms"] = int(time.time() * 1000)

        # Build peer-asset context from the same timestamp-aligned SMT universe.
        # In backtests, future peer candles are trimmed before they reach the
        # institutional multi-asset confirmation motor.
        smt_universe = data.get("smt_universe") or {}
        primary = data.get("symbol", "UNKNOWN")
        primary_15m = data.get("15m") or []
        if primary_15m:
            from timing import closed_htf_candles
            reference_ms = int(primary_15m[-1].time) + 15 * 60 * 1000
            peers = {}
            for peer_symbol, frames in smt_universe.items():
                if peer_symbol == primary or not isinstance(frames, dict):
                    continue
                peer_candles = closed_htf_candles(frames.get("4h") or [], reference_ms, "4h")
                if peer_candles:
                    peers[peer_symbol] = {"candles": peer_candles}
            if peers:
                payload["peer_assets"] = peers

        return self.institutional.analyze(payload)

    def _build_volume_profile_state(self, data):
        """Çoklu zaman diliminde volume profile durumunu üretir."""
        payload = {}

        for timeframe in self.VOLUME_PROFILE_TIMEFRAMES:
            candles = data.get(timeframe) or data.get(timeframe.upper())
            if candles:
                payload[timeframe] = candles

        return self.volume_profile.detect_multi(payload)

    def _timeframe_structure_direction(self, structure):
        """Yalnızca ilgili zaman diliminin kendi onaylı yapısından yön çıkarır."""
        for item in reversed(structure or []):
            if not isinstance(item, dict) or not (item.get("bos") or item.get("choch")):
                continue
            direction = str(item.get("direction", "")).upper()
            if direction in {"BULLISH", "BEARISH"}:
                return direction
        labels = [str(item.get("label", "")).upper() for item in (structure or []) if isinstance(item, dict)][-6:]
        bullish = sum(label in {"HH", "HL"} for label in labels)
        bearish = sum(label in {"LH", "LL"} for label in labels)
        if bullish >= 2 and bullish > bearish:
            return "BULLISH"
        if bearish >= 2 and bearish > bullish:
            return "BEARISH"
        return "NONE"

    def _timeframe_mtf_context(self, direction, timeframe):
        direction = str(direction or "NONE").upper()
        valid = direction in {"BULLISH", "BEARISH"}
        neutral = "NEUTRAL"
        return {
            "valid": valid,
            "entry": "LONG" if direction == "BULLISH" else "SHORT" if direction == "BEARISH" else "NONE",
            "weekly": neutral,
            "daily": direction if valid and timeframe == "1d" else neutral,
            "h4": direction if valid and timeframe == "4h" else neutral,
        }

    def _timeframe_smt_state(self, smt_state, timeframe):
        """SMT yalnızca aynı TF'de oluşan divergence'ları kullanır."""
        state = smt_state if isinstance(smt_state, dict) else {}
        divergences = [
            item for item in (state.get("divergences") or [])
            if isinstance(item, dict) and str(item.get("timeframe", "")).lower() == timeframe
        ]
        best = max(divergences, key=lambda item: float(item.get("confidence", 0) or 0), default=None)
        return {
            "active": best is not None,
            "direction": best.get("type", "NONE") if best else "NONE",
            "confidence": best.get("confidence", 0) if best else 0,
            "best": best,
            "divergences": divergences,
            "timeframes": [timeframe],
            "source": "timeframe_scoped_smt",
        }

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

            local_direction = self._timeframe_structure_direction(structure)
            local_mtf = self._timeframe_mtf_context(local_direction, timeframe)
            local_trend = self.trend.calculate(local_mtf, structure=structure)
            local_fvg = self.fvg.detect(candles)
            local_orderblocks = self.mitigation.detect(candles, self.orderblocks.detect(candles, structure))
            local_high, local_low, local_price = self._price_context(candles)
            local_premium_discount = self.premium_discount.calculate(local_high, local_low, local_price)
            local_phase = self.market_phase.detect(
                structure=structure, trend=local_trend, liquidity_sweep=liquidity_sweep,
                fvg=local_fvg, orderblocks=local_orderblocks,
                premium_discount=local_premium_discount,
                mtf=local_mtf, candles=candles, timeframe=timeframe,
            )
            payload[timeframe] = {
                "candles": candles,
                "structure": structure,
                "liquidity_sweep": liquidity_sweep,
                "market_phase": local_phase,
                "smt": self._timeframe_smt_state(smt_state, timeframe),
            }

        return self.cisd.detect_multi(payload)

    def _build_unicorn_state(self, data, tf_analysis, context_state, structure_state, smt_state):
        """Unicorn setup tespiti için MTF payload üretir ve sonucu döndürür."""
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

            local_direction = self._timeframe_structure_direction(structure)
            local_mtf = self._timeframe_mtf_context(local_direction, timeframe)
            local_trend = self.trend.calculate(local_mtf, structure=structure)
            swing_high, swing_low, current_price = self._price_context(candles)
            local_premium_discount = self.premium_discount.calculate(swing_high, swing_low, current_price)
            local_phase = self.market_phase.detect(
                structure=structure, trend=local_trend, liquidity_sweep=liquidity_sweep,
                fvg=fvg, orderblocks=orderblocks,
                premium_discount=local_premium_discount,
                mtf=local_mtf, candles=candles, timeframe=timeframe,
            )
            ote = self.ote.detect(
                swing_high=swing_high,
                swing_low=swing_low,
                current_price=current_price,
                direction="LONG" if local_direction == "BULLISH" else "SHORT" if local_direction == "BEARISH" else "NONE",
            )

            payload[timeframe] = {
                "structure": structure,
                "breaker": breaker,
                "fvg": fvg,
                "market_phase": local_phase,
                "liquidity_sweep": liquidity_sweep,
                "smt": self._timeframe_smt_state(smt_state, timeframe),
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

        # Align every comparison series to the last fully closed primary 15m
        # candle. This is essential in historical replay: comparison candles
        # from the future must never leak into an earlier SMT decision.
        smt_universe = dict(smt_universe)
        smt_universe[primary_symbol] = primary_timeframes
        reference_ms = None
        primary_15m = primary_timeframes.get("15m") or []
        if primary_15m:
            reference_ms = int(primary_15m[-1].time) + 15 * 60 * 1000
        if reference_ms is not None:
            from timing import closed_htf_candles
            aligned_universe = {}
            for comparison_symbol, frames in smt_universe.items():
                frames = frames if isinstance(frames, dict) else {}
                aligned_universe[comparison_symbol] = {
                    timeframe: closed_htf_candles(frames.get(timeframe) or [], reference_ms, timeframe)
                    for timeframe in self.SMT_TIMEFRAMES
                }
            smt_universe = aligned_universe

        return self.smt.detect(
            primary_symbol=primary_symbol,
            primary_timeframes=primary_timeframes,
            smt_universe=smt_universe,
            selected_symbols=selected_altcoins,
            timeframes=self.SMT_TIMEFRAMES,
        )

    def _validate_market_data(self, data):
        """Reject missing, malformed, non-finite, or out-of-order OHLCV data."""
        if not isinstance(data, dict):
            raise ValueError("Market data must be a dictionary")

        missing = [
            tf for tf in self.REQUIRED_TIMEFRAMES
            if not isinstance(data.get(tf), (list, tuple)) or not data.get(tf)
        ]
        if missing:
            raise ValueError(f"Missing or empty market data timeframes: {', '.join(missing)}")

        timeframes = list(self.REQUIRED_TIMEFRAMES)
        if isinstance(data.get("1h"), (list, tuple)) and data.get("1h"):
            timeframes.append("1h")

        for timeframe in timeframes:
            candles = data[timeframe]
            previous_time = None
            for index, candle in enumerate(candles):
                try:
                    timestamp = float(candle.time)
                    open_price = float(candle.open)
                    high = float(candle.high)
                    low = float(candle.low)
                    close = float(candle.close)
                    volume = float(candle.volume)
                except (AttributeError, TypeError, ValueError, OverflowError) as exc:
                    raise ValueError(
                        f"Malformed OHLCV candle: timeframe={timeframe} index={index}"
                    ) from exc

                values = (timestamp, open_price, high, low, close, volume)
                if not all(math.isfinite(value) for value in values):
                    raise ValueError(
                        f"Non-finite OHLCV value: timeframe={timeframe} index={index}"
                    )
                if timestamp < 0 or not timestamp.is_integer():
                    raise ValueError(
                        f"Invalid candle timestamp: timeframe={timeframe} index={index}"
                    )
                if min(open_price, high, low, close) <= 0 or volume < 0:
                    raise ValueError(
                        f"Invalid OHLCV range: timeframe={timeframe} index={index}"
                    )
                if high < max(open_price, close, low) or low > min(open_price, close, high):
                    raise ValueError(
                        f"Inconsistent OHLC prices: timeframe={timeframe} index={index}"
                    )
                if previous_time is not None and timestamp <= previous_time:
                    raise ValueError(
                        f"Candle timestamps must be strictly increasing: timeframe={timeframe} index={index}"
                    )
                previous_time = timestamp

    def _h4_ote_range(self, structure, direction):
        """Return the latest confirmed 4H impulse leg for OTE, or (None, None)."""
        if not isinstance(structure, list):
            return None, None

        def _index(item):
            try:
                return int(item.get("index"))
            except (TypeError, ValueError):
                return None

        if direction == "LONG":
            highs = [
                item for item in structure
                if str(item.get("kind", "")).upper() == "HIGH"
                and str(item.get("label", "")).upper() == "HH"
                and _index(item) is not None
            ]
            if not highs:
                return None, None
            high = max(highs, key=_index)
            prior_lows = [
                item for item in structure
                if str(item.get("kind", "")).upper() == "LOW"
                and str(item.get("label", "")).upper() == "HL"
                and _index(item) is not None
                and _index(item) < _index(high)
            ]
            if not prior_lows:
                return None, None
            low = max(prior_lows, key=_index)
            try:
                high_price, low_price = float(high.get("price")), float(low.get("price"))
            except (TypeError, ValueError):
                return None, None
            if not high_price > low_price > 0:
                return None, None
            # A later lower-low below the selected HL invalidates this impulse leg.
            invalidated = any(
                str(item.get("kind", "")).upper() == "LOW"
                and str(item.get("label", "")).upper() == "LL"
                and _index(item) is not None
                and _index(item) > _index(high)
                and self._safe_float(item.get("price")) is not None
                and float(item.get("price")) < low_price
                for item in structure
            )
            return (None, None) if invalidated else (high_price, low_price)

        if direction == "SHORT":
            lows = [
                item for item in structure
                if str(item.get("kind", "")).upper() == "LOW"
                and str(item.get("label", "")).upper() == "LL"
                and _index(item) is not None
            ]
            if not lows:
                return None, None
            low = max(lows, key=_index)
            prior_highs = [
                item for item in structure
                if str(item.get("kind", "")).upper() == "HIGH"
                and str(item.get("label", "")).upper() == "LH"
                and _index(item) is not None
                and _index(item) < _index(low)
            ]
            if not prior_highs:
                return None, None
            high = max(prior_highs, key=_index)
            try:
                high_price, low_price = float(high.get("price")), float(low.get("price"))
            except (TypeError, ValueError):
                return None, None
            if not high_price > low_price > 0:
                return None, None
            # A later higher-high above the selected LH invalidates this impulse leg.
            invalidated = any(
                str(item.get("kind", "")).upper() == "HIGH"
                and str(item.get("label", "")).upper() == "HH"
                and _index(item) is not None
                and _index(item) > _index(low)
                and self._safe_float(item.get("price")) is not None
                and float(item.get("price")) > high_price
                for item in structure
            )
            return (None, None) if invalidated else (high_price, low_price)

        return None, None

    @staticmethod
    def _safe_float(value):
        try:
            number = float(value)
            return number if math.isfinite(number) else None
        except (TypeError, ValueError, OverflowError):
            return None

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
                indices = sorted({
                    int(index)
                    for entry in entries
                    for index in (entry.get("indices") or [])
                    if index is not None
                })
                source_ids = sorted({
                    str(entry["event_id"])
                    for entry in entries
                    if entry.get("event_id")
                })
                event_id = (
                    f"{level_tag.lower()}:" + "|".join(source_ids)
                    if source_ids else None
                )
                result.append(
                    {
                        "type": "SELL_SIDE" if level_tag == "EQL" else "BUY_SIDE",
                        "level": level_tag,
                        "event_id": event_id,
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

        active = direction is not None and eqh_eql.get("active", False)
        relevant_pools = (
            eqh_eql.get("eql", []) if direction == "LONG"
            else eqh_eql.get("eqh", []) if direction == "SHORT"
            else []
        )
        pool_ids = sorted({
            str(item["event_id"])
            for item in relevant_pools
            if isinstance(item, dict) and item.get("event_id")
        })
        sweep_id = liquidity_sweep.get("event_id")
        event_id = (
            f"inducement:{sweep_id}:" + "|".join(pool_ids)
            if active and sweep_id and pool_ids else None
        )
        return {
            "active": active,
            "event_id": event_id,
            "direction": direction,
            "reason": "Liquidity sweep after equal highs/lows" if direction else "No inducement",
            "recent_structure": structure[-3:] if structure else [],
        }

    def _calculate_dynamic_tp(self, entry, liquidity, fvg, orderblocks, candles=None, structure=None, trendline_liquidity=None, stop_price=None, exclude_targets_through=None):
        """Entry yoksa boş TP şablonu, varsa dinamik hedefler döndürür."""
        if entry.get("entry") is None:
            return {"tp1": None, "tp2": None, "tp3": None}

        stop_value = entry.get("stop_loss") if stop_price is None else stop_price

        try:
            payload = self.dynamic_tp.calculate(
                direction=entry["direction"],
                entry=entry["entry"],
                stop_loss=stop_value,
                liquidity=list(liquidity or []) + list(trendline_liquidity or []),
                fvg=fvg,
                orderblocks=orderblocks,
                structure=structure,
                candles=candles,
                allow_rr_fallback=bool(getattr(Config, "DYNAMIC_TP_ALLOW_SYNTHETIC_FALLBACK", False)),
                exclude_targets_through=exclude_targets_through,
            )
            self.logger.info(
                "TP calculated | direction=%s stop=%s tp1=%s tp2=%s tp3=%s reason=%s",
                entry.get("direction"),
                stop_value,
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
            entry_type=entry.get("entry_type", "LIMIT"),
            direction=entry.get("direction"),
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
        live_learning = (manual_quality.get("learning") or {}).get("matched")
        if live_learning:
            self.logger.info(
                "LEARNING LIVE END | symbol=%s manual_score=%s confidence=%s decision_score=%s",
                data.get("symbol", "UNKNOWN"),
                manual_quality.get("score"),
                signal.get("confidence"),
                (decision or {}).get("score"),
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
        signal_id = None
        if self.trade_journal is not None:
            try:
                signal_id = self.manual_trade_service.resolve_signal_id(
                    symbol=symbol,
                    direction=action_for_message,
                )
            except Exception:
                signal_id = None

        reply_markup = None
        if hasattr(bot_class, "trade_feedback_keyboard"):
            reply_markup = bot_class.trade_feedback_keyboard(symbol, action_for_message, signal_id=signal_id)

        if bool(getattr(Config, "CONSOLE_SIGNAL_PRINT_ENABLED", True)):
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
