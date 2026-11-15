"""SMC context evidence motors. Diagnostic only; never authorize a trade."""
from __future__ import annotations

import math


def _v(item, key):
    try:
        value = item.get(key) if isinstance(item, dict) else getattr(item, key)
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError, AttributeError):
        return None


def _zone(item):
    top = _v(item, "top")
    bottom = _v(item, "bottom")
    if top is None: top = _v(item, "high")
    if bottom is None: bottom = _v(item, "low")
    if top is None or bottom is None or top < bottom:
        return None
    return top, bottom


def dealing_range(candles, price, lookback=80):
    bars = list(candles or [])[-lookback:]
    highs = [_v(x, "high") for x in bars]
    lows = [_v(x, "low") for x in bars]
    if len(bars) < 20 or any(x is None for x in highs+lows) or not isinstance(price, (int,float)) or not math.isfinite(price):
        return {"state":"UNAVAILABLE"}
    high, low = max(highs), min(lows)
    if high <= low:
        return {"state":"INVALID_RANGE"}
    position = (price-low)/(high-low)
    return {"high":high,"low":low,"equilibrium":(high+low)/2,
            "position":round(position,4),
            "zone":"DISCOUNT" if position < .45 else "PREMIUM" if position > .55 else "EQUILIBRIUM"}


def liquidity_draw(candles, direction, lookback=80):
    bars = list(candles or [])[-lookback:]
    highs = [_v(x,"high") for x in bars]
    lows = [_v(x,"low") for x in bars]
    if len(bars)<10 or any(x is None for x in highs+lows):
        return {"state":"UNAVAILABLE"}
    current = _v(bars[-1],"close")
    if current is None: return {"state":"INVALID_DATA"}
    if str(direction).upper()=="LONG":
        pools=sorted(set(x for x in highs[:-1] if x>current))
        return {"state":"FOUND" if pools else "NO_EXTERNAL_POOL","side":"BUY_SIDE","target":pools[0] if pools else None}
    if str(direction).upper()=="SHORT":
        pools=sorted(set(x for x in lows[:-1] if x<current),reverse=True)
        return {"state":"FOUND" if pools else "NO_EXTERNAL_POOL","side":"SELL_SIDE","target":pools[0] if pools else None}
    return {"state":"UNKNOWN_DIRECTION"}


def poi_freshness(zones, current_price, recent_candles=None):
    results=[]
    for z in list(zones or []):
        bounds=_zone(z)
        if bounds is None: continue
        top,bottom=bounds
        mitigated=bool(z.get("mitigated",False) if isinstance(z,dict) else getattr(z,"mitigated",False))
        touches=z.get("tested_count",z.get("touches",0)) if isinstance(z,dict) else getattr(z,"tested_count",getattr(z,"touches",0))
        try: touches=max(0,int(touches or 0))
        except (ValueError,TypeError,OverflowError): touches=0
        age=None
        idx=z.get("end_index",z.get("index")) if isinstance(z,dict) else getattr(z,"end_index",getattr(z,"index",None))
        if idx is not None and recent_candles is not None:
            try: age=max(0,len(recent_candles)-1-int(idx))
            except (ValueError,TypeError,OverflowError): age=None
        in_zone=isinstance(current_price,(int,float)) and bottom<=current_price<=top
        results.append({"top":top,"bottom":bottom,"mitigated":mitigated,
                        "touches":touches,"age_bars":age,"price_inside":in_zone,
                        "fresh":not mitigated and touches==0})
    return {"state":"AVAILABLE" if results else "NO_VALID_ZONES","zones":results,
            "fresh_count":sum(x["fresh"] for x in results)}


def breaker_validation(zones, candles):
    bars=list(candles or [])
    validated=[]
    if len(bars)<2: return {"state":"UNAVAILABLE","validated":[]}
    last_close=_v(bars[-1],"close")
    previous_close=_v(bars[-2],"close")
    if last_close is None or previous_close is None: return {"state":"INVALID_DATA","validated":[]}
    for z in list(zones or []):
        bounds=_zone(z)
        if bounds is None: continue
        top,bottom=bounds
        kind=str(z.get("kind",z.get("direction","")) if isinstance(z,dict) else getattr(z,"kind",getattr(z,"direction",""))).upper()
        # A bullish OB becomes a bearish breaker only after a close below its
        # lower boundary; bearish OB becomes bullish only after a close above.
        if kind in ("BULLISH","BULL","LONG") and previous_close>=bottom and last_close<bottom:
            validated.append({"kind":"BEARISH_BREAKER","top":top,"bottom":bottom})
        elif kind in ("BEARISH","BEAR","SHORT") and previous_close<=top and last_close>top:
            validated.append({"kind":"BULLISH_BREAKER","top":top,"bottom":bottom})
    return {"state":"FOUND" if validated else "NONE","validated":validated}


def reclaim_acceptance(candles, level, direction, lookback=3):
    bars=list(candles or [])[-lookback:]
    closes=[_v(x,"close") for x in bars]
    if level is None or not bars or any(x is None for x in closes): return {"state":"UNAVAILABLE"}
    side=str(direction).upper()
    if side=="LONG":
        ok=closes[-1]>float(level) and any(x<=float(level) for x in closes[:-1])
    elif side=="SHORT":
        ok=closes[-1]<float(level) and any(x>=float(level) for x in closes[:-1])
    else: return {"state":"UNKNOWN_DIRECTION"}
    return {"state":"ACCEPTED" if ok else "NOT_ACCEPTED","level":float(level)}


def inducement_proxy(candles, direction, lookback=24):
    bars=list(candles or [])[-lookback:]
    if len(bars)<8: return {"state":"UNAVAILABLE"}
    # Proxy only: a local internal pivot is swept and price closes back through it.
    for i in range(len(bars)-3,2,-1):
        high=_v(bars[i],"high"); low=_v(bars[i],"low")
        if high is None or low is None: return {"state":"INVALID_DATA"}
        left=[_v(x,"high") for x in bars[i-2:i]]
        right=[_v(x,"high") for x in bars[i+1:i+3]]
        left_l=[_v(x,"low") for x in bars[i-2:i]]
        right_l=[_v(x,"low") for x in bars[i+1:i+3]]
        if any(x is None for x in left+right+left_l+right_l): return {"state":"INVALID_DATA"}
        last=bars[-1]; close=_v(last,"close"); last_high=_v(last,"high"); last_low=_v(last,"low")
        if close is None or last_high is None or last_low is None: return {"state":"INVALID_DATA"}
        if str(direction).upper()=="SHORT" and high>max(left+right) and last_high>high and close<high:
            return {"state":"POSSIBLE_BEARISH_INDUCEMENT","level":high,"proxy":True}
        if str(direction).upper()=="LONG" and low<min(left_l+right_l) and last_low<low and close>low:
            return {"state":"POSSIBLE_BULLISH_INDUCEMENT","level":low,"proxy":True}
    return {"state":"NONE","proxy":True}


def narrative(direction, structure, range_info, draw, displacement_info, poi):
    side=str(direction).upper()
    aligned_structure=(structure or {}).get("state") in (("BULLISH",) if side=="LONG" else ("BEARISH",))
    range_aligned=(range_info or {}).get("zone") == ("DISCOUNT" if side=="LONG" else "PREMIUM")
    draw_available=(draw or {}).get("state")=="FOUND"
    displacement_aligned=(displacement_info or {}).get("direction")==("BULLISH" if side=="LONG" else "BEARISH")
    fresh=(poi or {}).get("fresh_count",0)>0
    return {"direction":side,"structure_aligned":aligned_structure,
            "dealing_range_aligned":range_aligned,"liquidity_draw_available":draw_available,
            "displacement_aligned":displacement_aligned,"fresh_poi_available":fresh,
            "evidence_count":sum((aligned_structure,range_aligned,draw_available,displacement_aligned,fresh)),
            "authority":"DIAGNOSTIC_ONLY"}
