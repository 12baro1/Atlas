"""End-to-end analysis trace context.

Her piyasa analizi için tek ve kararlı bir "trace_id" üretir. Bu kimlik veri
kaynağından (Bybit REST/WebSocket), DataEngine normalizasyonuna, ortak piyasa
kanıtlarına, uzman motorlara, yedi bağımsız stratejinin setup üretimine, ortak
filtreye ve nihai karar + TUI çıktısına kadar taşınır.

Trace yalnızca gözlemlenebilirlik amaçlıdır: hiçbir strateji ya da karar
mekanizması trace verisini okumaz, trace verisi stratejilerin bağımsız karar
mantığını birbirine bağlamaz.
"""

from __future__ import annotations

import time
import uuid

TRACE_ID_KEY = "trace_id"
TRACE_KEY = "trace"

# Aşama adları: veriden karara sabit pipeline adımları.
STAGE_DATA_SOURCE = "DATA_SOURCE"
STAGE_DATA_COLLECTION = "DATA_COLLECTION"
STAGE_DATA_NORMALIZATION = "DATA_NORMALIZATION"
STAGE_SHARED_MARKET_EVIDENCE = "SHARED_MARKET_EVIDENCE"
STAGE_SPECIALIST_MOTORS = "SPECIALIST_MOTORS"
STAGE_STRATEGY_SETUP = "STRATEGY_SETUP"
STAGE_COMMON_FILTER = "COMMON_FILTER"
STAGE_FINAL_DECISION = "FINAL_DECISION"
STAGE_SIGNAL_OUTPUT = "SIGNAL_OUTPUT"

# Tek analizde makul aşama sayısı; savunmacı üst sınır.
MAX_STAGES = 256

_STAGE_FIELDS = (
    "source", "freshness", "availability", "reason", "strategy",
    "setup_id", "filter_result", "decision",
)


def new_trace_id(now_ms=None):
    """Benzersiz bir trace kimliği üretir: yeni analiz her zaman yeni kimlik alır."""
    try:
        stamp = int(now_ms) if now_ms is not None else int(time.time() * 1000)
    except (TypeError, ValueError, OverflowError):
        stamp = int(time.time() * 1000)
    return "trace-{}-{}".format(stamp, uuid.uuid4().hex[:8])


def ensure_trace(data):
    """Analiz payload'ının trace kimliğini döndürür; yoksayıp yeniden üretmez.

    - data'da zaten trace_id varsa aynı kimlik korunur (aynı analizde sabit).
    - Yoksa yeni bir kimlik üretilir (yeni analiz, yeni kimlik).
    Trace kaydı dict olmayan payload'larda sessizce yok sayılır.
    """
    if not isinstance(data, dict):
        return None
    trace = data.get(TRACE_KEY)
    existing_id = data.get(TRACE_ID_KEY)
    if isinstance(trace, dict) and trace.get("trace_id"):
        trace_id = str(trace["trace_id"])
    elif existing_id:
        trace_id = str(existing_id)
        trace = {"trace_id": trace_id, "stages": list(trace.get("stages") or []) if isinstance(trace, dict) else []}
    else:
        trace_id = new_trace_id()
        trace = {"trace_id": trace_id, "stages": []}
    trace["trace_id"] = trace_id
    trace.setdefault("stages", [])
    data[TRACE_ID_KEY] = trace_id
    data[TRACE_KEY] = trace
    return trace


def trace_id(data):
    """Trace kimliğini oluşturmadan okur; yoksa None döner."""
    if not isinstance(data, dict):
        return None
    trace = data.get(TRACE_KEY)
    if isinstance(trace, dict) and trace.get("trace_id"):
        return str(trace["trace_id"])
    existing = data.get(TRACE_ID_KEY)
    return str(existing) if existing else None


def record_stage(data, stage, *, source=None, timestamp_ms=None, freshness=None,
                 availability=None, reason=None, strategy=None, setup_id=None,
                 filter_result=None, decision=None, detail=None):
    """Tek bir pipeline aşamasını izlenebilir kayıt olarak ekler.

    Zorunlu alanlar: trace_id, sembol, zaman damgası. Diğer alanlar aşamaya
    göre opsiyoneldir ve yalnızca gözlemlenebilirlik içindir.
    """
    trace = ensure_trace(data)
    if trace is None or not stage:
        return None
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)
    try:
        timestamp_ms = int(timestamp_ms)
    except (TypeError, ValueError, OverflowError):
        timestamp_ms = int(time.time() * 1000)
    symbol = data.get("symbol") if isinstance(data, dict) else None
    entry = {
        "stage": str(stage),
        "trace_id": trace["trace_id"],
        "symbol": symbol,
        "timestamp_ms": timestamp_ms,
    }
    for key, value in (
        ("source", source), ("freshness", freshness),
        ("availability", availability), ("reason", reason),
        ("strategy", strategy), ("setup_id", setup_id),
        ("filter_result", filter_result), ("decision", decision),
    ):
        if value is not None:
            entry[key] = value
    if isinstance(detail, dict) and detail:
        entry["detail"] = detail
    stages = trace.setdefault("stages", [])
    if len(stages) < MAX_STAGES:
        stages.append(entry)
    return entry
