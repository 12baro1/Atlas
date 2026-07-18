"""
engine.py
Atlas SMC Engine v3

Ana orkestrasyon katmanı: alt motorları modüler bir akışta birleştirir.
Kod İngilizce, açıklamalar Türkçe tutulmuştur.
"""

from importlib import import_module

from backtest_engine import BacktestEngine
from bos_engine import BOSEngine
from breaker_block_engine import BreakerBlockEngine
from choch_engine import CHOCHEngine
from config import Config
from confluence_engine import ConfluenceEngine
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
from market_phase_engine import MarketPhaseEngine
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
from smt_engine import SMTDivergenceEngine
from statistics_engine import StatisticsEngine
from trade_manager import TradeManager
from trend_engine import TrendEngine
from unicorn_engine import UnicornEngine
from utils.structure_labels import label_swings


class AtlasEngine:
    """Atlas'ın tüm analiz motorlarını yöneten ana sınıf."""

    REQUIRED_TIMEFRAMES = ("1w", "1d", "4h", "15m")
    SWEEP_TIMEFRAMES = ("15m", "1h", "4h", "1d")
    SMT_TIMEFRAMES = ("15m", "1h", "4h", "1d")
    UNICORN_TIMEFRAMES = ("15m", "1h", "4h", "1d")
    CISD_TIMEFRAMES = ("15m", "1h", "4h", "1d")

    def __init__(self, structure_engine_cls=None):
        # Testlerde sahte sınıf enjekte edebilmek için sınıf referansı tutulur.
        self.structure_engine_cls = structure_engine_cls or MarketStructureEngine

        # Structure ve seviye motorları
        self.bos = BOSEngine()
        self.choch = CHOCHEngine()
        self.liquidity = LiquidityEngine()
        self.orderblocks = OrderBlockEngine()
        self.mitigation = MitigationEngine()
        self.fvg = FVGEngine()
        self.liquidity_sweep = LiquiditySweepEngine()
        self.breaker = BreakerBlockEngine()

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
        self.decision = DecisionEngine()

        # Sinyal, risk ve operasyon motorları
        self.entry = EntryEngine()
        self.entry_confirmation = EntryConfirmationEngine()
        self.confluence = ConfluenceEngine()
        self.signal = SignalEngine()
        self.risk = RiskEngine()
        self.rr = RREngine()
        self.dynamic_tp = DynamicTPEngine()
        self.telegram = None

        # Dış API uyumluluğu için korunur
        self.config = Config()
        self.position = PositionManager()
        self.trade = TradeManager()
        self.scanner = ScannerEngine()
        self.statistics = StatisticsEngine()
        self.backtest = BacktestEngine()

    def analyze(self, data):
        """Çoklu zaman dilimi verisini analiz eder ve birleşik çıktı üretir."""
        self._validate_market_data(data)

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

        execution_state = self._build_execution_state(
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
        )

        decision_state = self.decision.decide(
            signal=execution_state["signal"],
            confluence=execution_state["confluence"],
            entry=execution_state["entry"],
            risk=execution_state["risk"],
            cisd=cisd_state,
        )

        analysis = self._compose_analysis(
            structure_state=structure_state,
            context_state=context_state,
            execution_state=execution_state,
            smt_state=smt_state,
            unicorn_state=unicorn_state,
            cisd_state=cisd_state,
            decision_state=decision_state,
        )

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
            decision=decision_state,
        )

        return {
            "analysis": analysis,
            "signal": execution_state["signal"],
            "risk": execution_state["risk"],
            "rr": execution_state["rr"],
            "dynamic_tp": execution_state["dynamic_tp"],
            "decision": decision_state,
        }

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

        return {
            "structure": structure,
            "bos": [item for item in structure if item.get("bos")],
            "choch": [item for item in structure if item.get("choch")],
            "liquidity": liquidity,
            "liquidity_layers": liquidity_layers,
            "eqh_eql": eqh_eql,
            "orderblocks": orderblocks,
            "fvg": fvg,
            "liquidity_sweep": liquidity_sweep,
            "inducement": inducement,
            "breaker": breaker,
        }

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
    ):
        """Entry, confirmation, confluence, signal, risk ve RR katmanını üretir."""
        entry = self.entry.generate(mtf, entry_structure, fvg, orderblocks)
        confirmation = self.entry_confirmation.confirm(mtf, entry_structure, fvg, entry)

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
        )

        dynamic_tp = self._calculate_dynamic_tp(entry, liquidity, fvg, orderblocks)
        risk = self._calculate_risk(entry, dynamic_tp)
        rr = self.rr.evaluate(risk) if risk is not None else None

        analysis_for_signal = {
            "entry": entry,
            "confluence": confluence,
            "market_phase": market_phase,
            "liquidity_sweep": liquidity_sweep,
            "smt": smt,
            "unicorn": unicorn,
            "cisd": cisd,
        }
        signal = self.signal.generate(analysis_for_signal)

        return {
            "entry": entry,
            "confirmation": confirmation,
            "confluence": confluence,
            "dynamic_tp": dynamic_tp,
            "risk": risk,
            "rr": rr,
            "signal": signal,
        }

    def _compose_analysis(
        self,
        structure_state,
        context_state,
        execution_state,
        smt_state,
        unicorn_state=None,
        cisd_state=None,
        decision_state=None,
    ):
        """Dış API'de beklenen analysis sözlüğünü oluşturur."""
        return {
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
            "decision": decision_state or {
                "action": "WAIT",
                "reason": "No decision",
            },
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

    def _detect_eqh_eql(self, liquidity):
        """Liquidity bölgelerini EQH/EQL çıktısına çevirir."""
        equal_highs = [level for level in liquidity if level.get("type") == "BUY_SIDE"]
        equal_lows = [level for level in liquidity if level.get("type") == "SELL_SIDE"]

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

    def _calculate_dynamic_tp(self, entry, liquidity, fvg, orderblocks):
        """Entry yoksa boş TP şablonu, varsa dinamik hedefler döndürür."""
        if entry.get("entry") is None:
            return {"tp1": None, "tp2": None, "tp3": None}

        return self.dynamic_tp.calculate(
            direction=entry["direction"],
            entry=entry["entry"],
            liquidity=liquidity,
            fvg=fvg,
            orderblocks=orderblocks,
        )

    def _calculate_risk(self, entry, dynamic_tp):
        """Geçerli entry/SL için risk çıktısını hesaplar."""
        if entry.get("entry") is None or entry.get("stop_loss") is None:
            return None

        return self.risk.calculate(
            entry=entry["entry"],
            stop_loss=entry["stop_loss"],
            dynamic_tp=dynamic_tp,
        )

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
        decision,
    ):
        """Yüksek güvenli sinyallerde Telegram bildirimi gönderir."""
        if signal.get("signal") not in ["LONG", "SHORT"]:
            return False

        if signal.get("confidence", 0) < 90:
            return False

        telegram_module = import_module("telegram_engine")
        telegram_engine = self.telegram or telegram_module.TelegramEngine()
        self.telegram = telegram_engine

        message = telegram_engine.format_signal(
            {
                "symbol": data.get("symbol", "UNKNOWN"),
                "signal": signal,
                "entry": entry,
                "risk": risk,
                "rr": rr,
                "dynamic_tp": dynamic_tp,
                "confluence": confluence,
                "market_phase": market_phase,
                "unicorn": unicorn,
                "cisd": cisd,
                "decision": decision,
            }
        )

        print(message)
        return telegram_module.TelegramBot().send(message)
