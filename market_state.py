from dataclasses import dataclass, field
from typing import Optional

@dataclass
class MarketState:
    # Trend
    trend: str = "UNKNOWN"
    internal_trend: str = "UNKNOWN"
    external_trend: str = "UNKNOWN"

    # Structure
    last_hh: Optional[float] = None
    last_hl: Optional[float] = None
    last_lh: Optional[float] = None
    last_ll: Optional[float] = None

    # Events
    bos: bool = False
    choch: bool = False
    mss: bool = False

    # Smart Money Concepts
    liquidity: bool = False
    displacement: bool = False
    orderblock: bool = False
    breaker: bool = False
    mitigation: bool = False
    fvg: bool = False
    ifvg: bool = False

    # Price Location
    premium: bool = False
    discount: bool = False

    # Signal
    symbol: str = ""
    timeframe: str = ""
    signal: str = "NONE"

    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    confidence: int = 0
    score: float = 0.0

    notes: list = field(default_factory=list)

    def reset_signal(self):
        self.signal = "NONE"
        self.entry = None
        self.stop_loss = None
        self.take_profit = None
        self.confidence = 0
        self.score = 0.0
        self.notes.clear()
