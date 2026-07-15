from dataclasses import dataclass
from typing import List, Optional

from core.candle import Candle
from core.pivot import Pivot
from core.market_state import MarketState


@dataclass
class BOSSignal:

    bullish: bool = False
    bearish: bool = False

    pivot: Optional[Pivot] = None

    break_index: int = -1
    break_price: float = 0.0

    displacement: float = 0.0

    confidence: int = 0


class BOSDetector:

    def __init__(self):

        self.signal = BOSSignal()

    def reset(self):

        self.signal = BOSSignal()

    def detect(
        self,
        candles: List[Candle],
        pivots: List[Pivot],
        state: MarketState
    ):

        self.reset()

        if len(candles) < 20:
            return self.signal

        confirmed = [
            p
            for p in pivots
            if p.confirmed
        ]

        if len(confirmed) < 2:
            return self.signal

        last_high = None
        last_low = None

        for pivot in confirmed:

            if pivot.kind == "HIGH":
                last_high = pivot

            elif pivot.kind == "LOW":
                last_low = pivot

        if last_high is None:
            return self.signal

        if last_low is None:
            return self.signal

        return self._scan(
            candles,
            last_high,
            last_low,
            state
        )
         def _scan(
        self,
        candles: List[Candle],
        last_high: Pivot,
        last_low: Pivot,
        state: MarketState
    ):

        start = max(
            last_high.index,
            last_low.index
        )

        for index in range(
            start + 1,
            len(candles)
        ):

            candle = candles[index]

            bullish = (
                candle.close > last_high.price
            )

            bearish = (
                candle.close < last_low.price
            )

            if bullish:

                if self._validate_bullish(
                    candle,
                    last_high
                ):

                    return self._create_signal(
                        candle,
                        index,
                        last_high,
                        state,
                        True
                    )

            if bearish:

                if self._validate_bearish(
                    candle,
                    last_low
                ):

                    return self._create_signal(
                        candle,
                        index,
                        last_low,
                        state,
                        False
                    )

        return self.signal
    def _validate_bullish(
        self,
        candle: Candle,
        pivot: Pivot
    ) -> bool:

        if candle.close <= pivot.price:
            return False

        body = candle.body

        if body <= 0:
            return False

        if candle.upper_wick > body:
            return False

        if (candle.close - pivot.price) < (body * 0.30):
            return False

        return True


    def _validate_bearish(
        self,
        candle: Candle,
        pivot: Pivot
    ) -> bool:

        if candle.close >= pivot.price:
            return False

        body = candle.body

        if body <= 0:
            return False

        if candle.lower_wick > body:
            return False

        if (pivot.price - candle.close) < (body * 0.30):
            return False

        return True


    def _create_signal(
        self,
        candle: Candle,
        index: int,
        pivot: Pivot,
        state: MarketState,
        bullish: bool
    ):

        self.signal.break_index = index
        self.signal.break_price = candle.close
        self.signal.pivot = pivot
        self.signal.displacement = abs(
            candle.close - pivot.price
        )

        self.signal.bullish = bullish
        self.signal.bearish = not bullish

        state.bos = True

        if bullish:
            state.trend = "BULLISH"
            state.last_hh = candle.close
        else:
            state.trend = "BEARISH"
            state.last_ll = candle.close

        return self.signal
          def _calculate_confidence(
        self,
        candle: Candle,
        pivot: Pivot
    ) -> int:

        confidence = 50

        if candle.bullish:
            confidence += 10

        if candle.bearish:
            confidence += 10

        if candle.body > (
            candle.range * 0.60
        ):
            confidence += 15

        if pivot.strength >= 20:
            confidence += 15

        return min(confidence, 100)


    def _update_state(
        self,
        state: MarketState,
        bullish: bool,
        confidence: int
    ):

        state.bos = True

        state.confidence = confidence

        if bullish:

            state.trend = "BULLISH"

            state.notes.append(
                "Bullish BOS confirmed"
            )

        else:

            state.trend = "BEARISH"

            state.notes.append(
                "Bearish BOS confirmed"
            )

        state.score += confidence / 100
          def _create_signal(
        self,
        candle: Candle,
        index: int,
        pivot: Pivot,
        state: MarketState,
        bullish: bool
    ):

        confidence = self._calculate_confidence(
            candle,
            pivot
        )

        self.signal.break_index = index
        self.signal.break_price = candle.close
        self.signal.pivot = pivot
        self.signal.displacement = abs(
            candle.close - pivot.price
        )

        self.signal.bullish = bullish
        self.signal.bearish = not bullish
        self.signal.confidence = confidence

        self._update_state(
            state,
            bullish,
            confidence
        )

        if bullish:

            state.last_hh = candle.high

        else:

            state.last_ll = candle.low

        return self.signal
          def last_signal(self):

        return self.signal


    def reset_state(
        self,
        state: MarketState
    ):

        state.bos = False

        state.confidence = 0

        state.score = 0.0


    def has_bullish_bos(self):

        return (
            self.signal.bullish
            and
            self.signal.break_index >= 0
        )


    def has_bearish_bos(self):

        return (
            self.signal.bearish
            and
            self.signal.break_index >= 0
        )


    def summary(self):

        return {

            "bullish": self.signal.bullish,

            "bearish": self.signal.bearish,

            "break_index": self.signal.break_index,

            "break_price": self.signal.break_price,

            "confidence": self.signal.confidence,

            "displacement": self.signal.displacement,

            "pivot_price": (
                self.signal.pivot.price
                if self.signal.pivot
                else None
            )
        }
      
