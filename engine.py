"""
engine.py
Atlas SMC Engine v2

Ana orkestrasyon katmanı: alt motorları tek bir analiz akışında modüler,
test edilebilir ve mevcut import yapısıyla geriye uyumlu şekilde birleştirir.
"""

from importlib import import_module
from core.market_structure_engine import MarketStructureEngine
from utils.structure_labels import label_swings
from bos_engine import BOSEngine
from choch_engine import CHOCHEngine
from liquidity_engine import LiquidityEngine
from orderblock_engine import OrderBlockEngine
from signal_engine import SignalEngine
from mitigation_engine import MitigationEngine
from fvg_engine import FVGEngine
from trend_engine import TrendEngine
from market_phase_engine import MarketPhaseEngine
from mtf_engine import MTFEngine
from entry_engine import EntryEngine
from entry_confirmation_engine import EntryConfirmationEngine
from premium_discount_engine import PremiumDiscountEngine
from killzone_engine import KillZoneEngine
from session_filter import SessionFilter
from liquidity_sweep_engine import LiquiditySweepEngine
from confluence_engine import ConfluenceEngine
from risk_engine import RiskEngine
from rr_engine import RREngine
from position_manager import PositionManager
from trade_manager import TradeManager
from scanner_engine import ScannerEngine
from statistics_engine import StatisticsEngine
from backtest_engine import BacktestEngine
from config import Config
from breaker_block_engine import BreakerBlockEngine
from ote_engine import OTEEngine
from htf_orderblock_engine import HTFOrderBlockEngine
from htf_fvg_engine import HTFFVGEngine
from dynamic_tp_engine import DynamicTPEngine


class AtlasEngine:
    """Atlas'ın tüm SMC analiz motorlarını yöneten ana sınıf."""

    REQUIRED_TIMEFRAMES = ("1w", "1d", "4h", "15m")

    def __init__(self):
        # Çekirdek yapı motorları
        self.structure_engine = MarketStructureEngine()
        self.bos = BOSEngine()
        self.choch = CHOCHEngine()
        self.liquidity = LiquidityEngine()
        self.orderblocks = OrderBlockEngine()
        self.mitigation = MitigationEngine()
        self.fvg = FVGEngine()
        self.liquidity_sweep = LiquiditySweepEngine()

        # Bağlam ve faz motorları
        self.trend = TrendEngine()
        self.market_phase = MarketPhaseEngine()
        self.mtf = MTFEngine()
        self.premium_discount = PremiumDiscountEngine()
        self.killzone = KillZoneEngine()
        self.session = SessionFilter()
        self.breaker = BreakerBlockEngine()
        self.ote = OTEEngine()
        self.htf_orderblock = HTFOrderBlockEngine()
        self.htf_fvg = HTFFVGEngine()

        # Sinyal, risk ve operasyon motorları
        self.entry = EntryEngine()
        self.entry_confirmation = EntryConfirmationEngine()
        self.confluence = ConfluenceEngine()
        self.signal = SignalEngine()
        self.risk = RiskEngine()
        self.rr = RREngine()
        self.dynamic_tp = DynamicTPEngine()
        self.telegram = None

        # Mevcut dış API uyumluluğu için korunan yardımcılar
        self.config = Config()
        self.position = PositionManager()
        self.trade = TradeManager()
        self.scanner = ScannerEngine()
        self.statistics = StatisticsEngine()
        self.backtest = BacktestEngine()


    def analyze(self, data):
        """Çoklu zaman dilimi verisini analiz eder ve birleşik sonuç döndürür."""
        self._validate_market_data(data)

        candles = data["15m"]
        weekly = data["1w"]
        daily = data["1d"]
        h4 = data["4h"]

        entry_tf = self._analyze_timeframe(candles)
        weekly_tf = self._analyze_timeframe(weekly)
        daily_tf = self._analyze_timeframe(daily)
        h4_tf = self._analyze_timeframe(h4)

        labels = entry_tf["structure"]
        liquidity = self.liquidity.detect(labels)
        eqh_eql = self._detect_eqh_eql(liquidity)
        orderblocks = self.mitigation.detect(
            candles,
            self.orderblocks.detect(candles, labels),
        )
        breakers = self.breaker.detect(candles, orderblocks)
        fvg = self.fvg.detect(candles)
        liquidity_sweep = self.liquidity_sweep.detect(candles)
        inducement = self._detect_inducement(labels, liquidity_sweep, eqh_eql)

        swing_high, swing_low, current_price = self._price_context(candles)
        premium_discount = self.premium_discount.calculate(
            swing_high,
            swing_low,
            current_price,
        )

        timestamp = candles[-1].time
        killzone = self.killzone.detect(timestamp)
        session = self.session.check(timestamp)

        daily_orderblocks = self.orderblocks.detect(daily, daily_tf["structure"])
        h4_orderblocks = self.orderblocks.detect(h4, h4_tf["structure"])

        mtf = self.mtf.detect(
            weekly_tf["structure"],
            daily_tf["structure"],
            h4_tf["structure"],
            labels,
        )
        trend = self.trend.calculate(mtf)
        entry = self.entry.generate(mtf, labels, fvg, orderblocks)
        ote = self.ote.detect(swing_high, swing_low, current_price, entry["direction"])
        htf_orderblock = self.htf_orderblock.detect(
            current_price,
            daily_orderblocks,
            h4_orderblocks,
        )
        htf_fvg = self.htf_fvg.detect(self.fvg.detect(h4), self.fvg.detect(daily))
        dynamic_tp = self._calculate_dynamic_tp(entry, liquidity, fvg, orderblocks)
        confirmation = self.entry_confirmation.confirm(mtf, labels, fvg, entry)

        confluence = self.confluence.evaluate(
            mtf=mtf,
            trend=trend,
            entry=entry,
            confirmation=confirmation,
            premium_discount=premium_discount,
            liquidity_sweep=liquidity_sweep,
            breaker=breakers,
            ote=ote,
            htf_orderblock=htf_orderblock,
            htf_fvg=htf_fvg,
            killzone=killzone,
            session=session,
        )

        market_phase = self.market_phase.detect(
            structure=labels,
            trend=trend,
            liquidity_sweep=liquidity_sweep,
            fvg=fvg,
            orderblocks=orderblocks,
            premium_discount=premium_discount,
            mtf=mtf,
            candles=candles,
        )

        analysis = {
            "structure": labels,
            "bos": [item for item in labels if item.get("bos")],
            "choch": [item for item in labels if item.get("choch")],
            "liquidity": liquidity,
            "eqh_eql": eqh_eql,
            "orderblocks": orderblocks,
            "fvg": fvg,
            "liquidity_sweep": liquidity_sweep,
            "inducement": inducement,
            "mtf": mtf,
            "trend": trend,
            "entry": entry,
            "confirmation": confirmation,
            "ote": ote,
            "premium_discount": premium_discount,
            "killzone": killzone,
            "session": session,
            "breaker": breakers,
            "htf_orderblock": htf_orderblock,
            "htf_fvg": htf_fvg,
            "dynamic_tp": dynamic_tp,
            "confluence": confluence,
            "market_phase": market_phase,
        }

        risk = self._calculate_risk(entry, dynamic_tp)
        rr = self.rr.evaluate(risk) if risk is not None else None
        signal = self.signal.generate(analysis)
        self._notify_if_elite(data, signal, entry, risk, rr, dynamic_tp, confluence, market_phase)

        return {
            "analysis": analysis,
            "signal": signal,
            "risk": risk,
            "rr": rr,
            "dynamic_tp": dynamic_tp,
        }

    def _analyze_timeframe(self, candles):
        """Tek zaman dilimi için pivot, etiket, BOS ve CHoCH üretir."""
        engine = MarketStructureEngine()
        pivots = engine.find_pivots(candles)
        engine.calculate_strength(candles)
        engine.merge_pivots()
        engine.filter_noise()
        pivots = engine.validate_sequence()
        structure = self.choch.detect(self.bos.detect(label_swings(pivots)))
        return {"pivots": pivots, "structure": structure}

    def _validate_market_data(self, data):
        """Gerekli veri setlerinin varlığını ve boş olmadığını doğrular."""
        missing = [timeframe for timeframe in self.REQUIRED_TIMEFRAMES if not data.get(timeframe)]
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
        """Süpürme ve yakın eşit likiditeye göre basit inducement bağlamı üretir."""
        direction = None
        if liquidity_sweep.get("sell_side"):
            direction = "LONG"
        elif liquidity_sweep.get("buy_side"):
            direction = "SHORT"

        recent_structure = structure[-3:] if structure else []
        return {
            "active": direction is not None and eqh_eql.get("active", False),
            "direction": direction,
            "reason": "Liquidity sweep after equal highs/lows" if direction else "No inducement",
            "recent_structure": recent_structure,
        }

    def _calculate_dynamic_tp(self, entry, liquidity, fvg, orderblocks):
        """Entry yoksa boş TP şablonu, varsa dinamik hedefler döndürür."""
        if entry["entry"] is None:
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
        if entry["entry"] is None or entry["stop_loss"] is None:
            return None

        return self.risk.calculate(
            entry=entry["entry"],
            stop_loss=entry["stop_loss"],
            dynamic_tp=dynamic_tp,
        )

    def _notify_if_elite(self, data, signal, entry, risk, rr, dynamic_tp, confluence, market_phase):
        """Sadece yüksek güvenli sinyallerde Telegram bildirimi gönderir."""
        if signal["signal"] not in ["LONG", "SHORT"] or signal["confidence"] < 90:
            return False

        telegram_module = import_module("telegram_engine")
        telegram_engine = self.telegram or telegram_module.TelegramEngine()
        self.telegram = telegram_engine

        message = telegram_engine.format_signal({
            "symbol": data.get("symbol", "UNKNOWN"),
            "signal": signal,
            "entry": entry,
            "risk": risk,
            "rr": rr,
            "dynamic_tp": dynamic_tp,
            "confluence": confluence,
            "market_phase": market_phase,
        })

        print(message)
        return telegram_module.TelegramBot().send(message)
