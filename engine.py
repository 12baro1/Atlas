"""
engine.py
Atlas SMC Engine v1
"""

from telegram_engine import TelegramEngine, TelegramBot
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
from telegram_engine import TelegramEngine
from statistics_engine import StatisticsEngine
from backtest_engine import BacktestEngine
from config import Config
from breaker_block_engine import BreakerBlockEngine
from ote_engine import OTEEngine
from htf_orderblock_engine import HTFOrderBlockEngine
from htf_fvg_engine import HTFFVGEngine
from dynamic_tp_engine import DynamicTPEngine

class AtlasEngine:

    def __init__(self):
        self.structure_engine = MarketStructureEngine()
        self.bos = BOSEngine()
        self.choch = CHOCHEngine()
        self.liquidity = LiquidityEngine()
        self.orderblocks = OrderBlockEngine()
        self.signal = SignalEngine()
        self.mitigation = MitigationEngine()
        self.fvg = FVGEngine()
        self.trend = TrendEngine()
        self.market_phase = MarketPhaseEngine()
        self.mtf = MTFEngine()
        self.entry = EntryEngine()
        self.entry_confirmation = EntryConfirmationEngine()
        self.config = Config()
        self.premium_discount = PremiumDiscountEngine()
        self.killzone = KillZoneEngine()
        self.session = SessionFilter()
        self.liquidity_sweep = LiquiditySweepEngine()
        self.confluence = ConfluenceEngine()
        self.risk = RiskEngine()
        self.rr = RREngine()
        self.position = PositionManager()
        self.trade = TradeManager()
        self.scanner = ScannerEngine()
        self.telegram = TelegramEngine()
        self.statistics = StatisticsEngine()
        self.backtest = BacktestEngine()
        self.breaker = BreakerBlockEngine()
        self.ote = OTEEngine()
        self.htf_orderblock = HTFOrderBlockEngine()
        self.htf_fvg = HTFFVGEngine()
        self.dynamic_tp = DynamicTPEngine()

    def analyze(self, data):
        weekly = data["1w"]
        daily = data["1d"]
        h4 = data["4h"]
        m15 = data["15m"]

        candles = m15

        pivots = self.structure_engine.find_pivots(candles)
        self.structure_engine.calculate_strength(candles)
        self.structure_engine.merge_pivots()
        self.structure_engine.filter_noise()
        self.structure_engine.validate_sequence()

        labels = label_swings(self.structure_engine.pivots)

        labels = self.bos.detect(labels)
        labels = self.choch.detect(labels)

        liquidity = self.liquidity.detect(labels)
        orderblocks = self.orderblocks.detect(candles, labels)
        orderblocks = self.mitigation.detect(candles, orderblocks)
        breakers = self.breaker.detect(
            candles,
            orderblocks
        )
        fvg = self.fvg.detect(candles)
        liquidity_sweep = self.liquidity_sweep.detect(candles)

        swing_high = max(c.high for c in candles)
        swing_low = min(c.low for c in candles)
        current_price = candles[-1].close

        premium_discount = self.premium_discount.calculate(
               swing_high,
               swing_low,
               current_price
        )

        timestamp = candles[-1].time

        killzone = self.killzone.detect(timestamp)
        session = self.session.check(timestamp)
        
        weekly_pivots = self.structure_engine.find_pivots(weekly)
        weekly_labels = label_swings(weekly_pivots)
        weekly_labels = self.bos.detect(weekly_labels)
        weekly_labels = self.choch.detect(weekly_labels)

        daily_pivots = self.structure_engine.find_pivots(daily)
        daily_labels = label_swings(daily_pivots)
        daily_labels = self.bos.detect(daily_labels)
        daily_labels = self.choch.detect(daily_labels)
        daily_orderblocks = self.orderblocks.detect(
            daily,
            daily_labels
        )

        h4_pivots = self.structure_engine.find_pivots(h4)
        h4_labels = label_swings(h4_pivots)
        h4_labels = self.bos.detect(h4_labels)
        h4_labels = self.choch.detect(h4_labels)
        h4_orderblocks = self.orderblocks.detect(
            h4,
            h4_labels
        )

        mtf = self.mtf.detect(
            weekly_labels,
            daily_labels,
            h4_labels,
            labels
        )

        trend = self.trend.calculate(mtf)

        entry = self.entry.generate(
            mtf,
            labels,
            fvg,
            orderblocks
        )

        ote = self.ote.detect(
            swing_high,
            swing_low,
            current_price,
            entry["direction"]
        )

        htf_orderblock = self.htf_orderblock.detect(
            current_price,
            daily_orderblocks,
            h4_orderblocks
        )

        h4_fvg = self.fvg.detect(h4)
        daily_fvg = self.fvg.detect(daily)

        htf_fvg = self.htf_fvg.detect(
            h4_fvg,
            daily_fvg
        )

        if entry["entry"] is not None:
            dynamic_tp = self.dynamic_tp.calculate(
                direction=entry["direction"],
                entry=entry["entry"],
                liquidity=liquidity,
                fvg=fvg,
                orderblocks=orderblocks
            )
        else:
            dynamic_tp = {
                "tp1": None,
                "tp2": None,
                "tp3": None
            }
        

        confirmation = self.entry_confirmation.confirm(
            mtf,
            labels,
            fvg,
            entry
        )

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
            session=session
        )

        market_phase = self.market_phase.detect(
            structure=labels,
            trend=trend,
            liquidity_sweep=liquidity_sweep,
            fvg=fvg,
            orderblocks=orderblocks,
            premium_discount=premium_discount,
            mtf=mtf
        )

        analysis = {
            "structure": labels,
            "liquidity": liquidity,
            "orderblocks": orderblocks,
            "fvg": fvg,
            "mtf": mtf,
            "trend": trend,
            "entry": entry,
            "confirmation": confirmation,
            "ote": ote,
            "liquidity_sweep": liquidity_sweep,
            "premium_discount": premium_discount,
            "killzone": killzone,
            "session": session,
            "breaker": breakers,
            "htf_orderblock": htf_orderblock,
            "htf_fvg": htf_fvg,
            "dynamic_tp": dynamic_tp,
            "market_phase": market_phase,
        }

        risk = None

        if entry["entry"] is not None and entry["stop_loss"] is not None:
            risk = self.risk.calculate(
                entry=entry["entry"],
                stop_loss=entry["stop_loss"],
                dynamic_tp=dynamic_tp
            )

        rr = None

        if risk is not None:
            rr = self.rr.evaluate(risk)

        analysis["confluence"] = confluence

        signal = self.signal.generate(analysis)

        if signal["signal"] in ["LONG", "SHORT"] and signal["confidence"] >= 90:

            message = self.telegram.format_signal({
                "symbol": data.get("symbol", "UNKNOWN"),
                "signal": signal,
                "entry": entry,
                "risk": risk,
                "rr": rr,
                "dynamic_tp": dynamic_tp,
                "confluence": confluence
            })

            print(message)
            TelegramBot().send(message)     
            return {
                "analysis": analysis,
                "signal": signal,
                "risk": risk,
                "rr": rr,
                "dynamic_tp": dynamic_tp
            }
