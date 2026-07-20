"""
smc_engine.py
Atlas SMC Compatibility Engine
"""

from bybit import create_public_swap_exchange

from core.market_structure_engine import MarketStructureEngine
from fvg_engine import FVGEngine
from liquidity_engine import LiquidityEngine
from orderblock_engine import OrderBlockEngine
from choch_engine import CHOCHEngine
from bos_engine import BOSEngine


class SMCEngine:
    """Geriye dönük uyumluluk için temel SMC yüzeyini korur."""

    def __init__(self, exchange=None):
        self.exchange = exchange or create_public_swap_exchange(enable_rate_limit=True)
        self.structure_engine = MarketStructureEngine()
        self.liquidity_engine = LiquidityEngine()
        self.orderblock_engine = OrderBlockEngine()
        self.fvg_engine = FVGEngine()
        self.choch_engine = CHOCHEngine()
        self.bos_engine = BOSEngine()

    def candles(self, symbol, timeframe, limit):
        return self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    def market_structure(self, candles):
        pivots = self._structure_engine(candles)
        return self._label_structure(pivots)

    def liquidity(self, candles):
        structure = self.market_structure(candles)
        return self.liquidity_engine.detect_layers(structure, candles)

    def orderblock(self, candles):
        structure = self.market_structure(candles)
        raw = self.orderblock_engine.detect(candles, structure)
        return raw

    def fvg(self, candles):
        return self.fvg_engine.detect(candles)

    def choch(self, candles):
        structure = self.market_structure(candles)
        return self.choch_engine.detect(self.bos(candles))

    def bos(self, candles):
        structure = self.market_structure(candles)
        return self.bos_engine.detect(structure)

    def score(self, candles):
        structure = self.market_structure(candles)
        liquidity = self.liquidity(candles)
        orderblocks = self.orderblock(candles)
        fvgs = self.fvg(candles)

        score = 0
        score += min(25, len([item for item in structure if item.get("bos") or item.get("choch")]) * 5)
        score += min(20, len(liquidity.get("all", [])) * 4)
        score += min(20, len(orderblocks) * 4)
        score += min(20, len(fvgs) * 3)
        score += min(15, len([item for item in structure if item.get("confirmed")]) * 3)
        return min(100, score)

    def analyze(self, candles):
        structure = self.market_structure(candles)
        return {
            "structure": structure,
            "liquidity": self.liquidity(candles),
            "orderblocks": self.orderblock(candles),
            "fvg": self.fvg(candles),
            "bos": self.bos(candles),
            "choch": self.choch(candles),
            "score": self.score(candles),
        }

    def _structure_engine(self, candles):
        self.structure_engine.find_pivots(candles)
        self.structure_engine.calculate_strength(candles)
        self.structure_engine.merge_pivots()
        self.structure_engine.filter_noise()
        return self.structure_engine.validate_sequence()

    def _label_structure(self, pivots):
        structure = []
        previous_high = None
        previous_low = None

        for pivot in pivots:
            label = "HH" if pivot.kind == "HIGH" else "LL"
            direction = "BULLISH" if pivot.kind == "HIGH" else "BEARISH"

            if pivot.kind == "HIGH" and previous_high is not None:
                label = "HH" if pivot.price >= previous_high else "LH"
            elif pivot.kind == "LOW" and previous_low is not None:
                label = "HL" if pivot.price >= previous_low else "LL"

            if pivot.kind == "HIGH":
                previous_high = pivot.price
            else:
                previous_low = pivot.price

            structure.append(
                {
                    "index": pivot.index,
                    "price": pivot.price,
                    "kind": pivot.kind,
                    "label": label,
                    "strength": getattr(pivot, "strength", 0),
                    "confirmed": getattr(pivot, "confirmed", False),
                    "direction": direction,
                    "bos": False,
                    "choch": False,
                }
            )

        if len(structure) >= 2:
            last = structure[-1]
            prev = structure[-2]
            if last["label"] in ["HH", "HL"] and prev["label"] in ["LH", "LL"]:
                last["bos"] = True
            elif last["label"] in ["LH", "LL"] and prev["label"] in ["HH", "HL"]:
                last["choch"] = True

        return structure
