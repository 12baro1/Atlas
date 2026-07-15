from dataclasses import dataclass

@dataclass
class MarketState:

    trend:str="UNKNOWN"

    internal_trend:str="UNKNOWN"

    external_trend:str="UNKNOWN"

    last_hh=None
    last_hl=None
    last_lh=None
    last_ll=None

    bos=False

    choch=False

    mss=False

    liquidity=False

    displacement=False

    orderblock=False

    breaker=False

    mitigation=False

    fvg=False

    ifvg=False

    premium=False

    discount=False

    confidence=0

    score=0
