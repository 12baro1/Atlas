"""
engine.py
Atlas SMC Engine v1
"""

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
from mtf_engine import MTFEngine


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
        self.mtf = MTFEngine()

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
        fvg = self.fvg.detect(candles)
        analysis = {
            "structure": labels,
            "liquidity": liquidity,
            "orderblocks": orderblocks,
            "fvg": fvg
        }
        weekly_pivots = self.structure_engine.find_pivots(weekly)
        weekly_labels = label_swings(weekly_pivots)
        weekly_labels = self.bos.detect(weekly_labels)
        weekly_labels = self.choch.detect(weekly_labels)

        daily_pivots = self.structure_engine.find_pivots(daily)
        daily_labels = label_swings(daily_pivots)
        daily_labels = self.bos.detect(daily_labels)
        daily_labels = self.choch.detect(daily_labels)

        h4_pivots = self.structure_engine.find_pivots(h4)
        h4_labels = label_swings(h4_pivots)
        h4_labels = self.bos.detect(h4_labels)
        h4_labels = self.choch.detect(h4_labels)

mtf = self.mtf.detect(
    weekly_labels,
    daily_labels,
    h4_labels,
    labels
)
        trend = self.trend.detect(
            [],
            [],
            labels
        )

        signal = self.signal.generate(analysis)

        return {
            "pivots": self.structure_engine.pivots,
            "structure": labels,
            "liquidity": liquidity,
            "orderblocks": orderblocks,
            "mitigation": orderblocks,
            "fvg": fvg,
            "signal": signal,
            "trend": trend,
            "mtf": mtf,
        }
