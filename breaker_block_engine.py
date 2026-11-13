"""
breaker_block_engine.py
Atlas Breaker Block Engine v1
"""

class BreakerBlockEngine:

    def detect(self, candles, orderblocks):

        breakers = []

        for ob in orderblocks:

            broken = False

            for candle_index, candle in enumerate(candles[ob["index"] + 1:], start=ob["index"] + 1):

                # Bullish OB kırıldı
                if (
                    ob["type"] == "BULLISH"
                    and candle.close < ob["low"]
                ):

                    broken = True

                # Bearish OB kırıldı
                elif (
                    ob["type"] == "BEARISH"
                    and candle.close > ob["high"]
                ):

                    broken = True

                if broken:

                    break_event_id = None
                    try:
                        break_candle = candles[candle_index]
                        break_time = break_candle.get("time", break_candle.get("timestamp")) if isinstance(break_candle, dict) else getattr(break_candle, "time", None)
                        if ob.get("event_id") and break_time is not None:
                            break_event_id = f"breaker:{ob['event_id']}:{int(break_time)}"
                    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
                        break_event_id = None

                    breakers.append({

                        "event_id": break_event_id,

                        "type": "BEARISH" if ob["type"] == "BULLISH" else "BULLISH",

                        "original_type": ob["type"],

                        "direction": "BEARISH" if ob["type"] == "BULLISH" else "BULLISH",

                        "index": ob["index"],

                        "break_index": candle_index,

                        "high": ob["high"],

                        "low": ob["low"],

                        "strength": ob.get("strength", 50),

                        "breaker": True

                    })

                    break

        return breakers
