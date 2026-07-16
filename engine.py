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


class AtlasEngine:

    def __init__(self):
        self.structure_engine = MarketStructureEngine()
        self.bos = BOSEngine()
        self.choch = CHOCHEngine()
        self.liquidity = LiquidityEngine()
        self.orderblocks = OrderBlockEngine()

    def analyze(self, candles):

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

        return {
            "pivots": self.structure_engine.pivots,
            "structure": labels,
            "liquidity": liquidity,
            "orderblocks": orderblocks
        }
        if __name__ == "__main__":
    print("Atlas Engine OK")
