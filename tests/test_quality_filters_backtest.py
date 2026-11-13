import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest_engine import BacktestEngine
from trade_quality_filters import TradeQualityFilters


def _candle(time, open_price, high, low, close, volume=1.0):
    from core.candle import Candle
    return Candle(time=time, open=open_price, high=high, low=low, close=close, volume=volume)


def _tp_for(entry, stop, direction):
    risk = abs(entry - stop)
    step = max(risk, risk * 0.5, 1e-9)
    if direction == "LONG":
        return [entry + step, entry + step * 2, entry + step * 3]
    return [entry - step, entry - step * 2, entry - step * 3]


def base_ctx(direction="LONG", atr=2.0, **overrides):
    if direction == "LONG":
        entry, stop, current = 100.0, 98.0, 100.5
        h4 = "BULLISH"
    else:
        entry, stop, current = 100.0, 102.0, 99.5
        h4 = "BEARISH"
    ctx = {
        "direction": direction,
        "entry": {
            "valid": True, "direction": direction, "entry": entry,
            "stop_loss": stop, "entry_type": "LIMIT", "ote_confluence": True,
        },
        "risk": {
            "risk_setup_valid": True, "entry": entry, "stop_loss": stop,
            "weighted_net_rr": 3.0, "execution_rr": 3.0,
        },
        "current_price": current,
        "candles": [],
        "atr_value": atr,
        "mtf": {"valid": True, "entry": direction, "h4": h4},
        "liquidity_sweep": {
            "is_sweep": False, "buy_side": False, "sell_side": False,
            "ambiguous_sweep": False,
            "post_structure": {"confirmed": False, "direction": None},
        },
        "liquidity_layers": {"swing": [], "internal": [], "all": []},
        "eqh_eql": {"eqh": [], "eql": []},
        "smt": None, "cisd": None, "volume_profile": None,
        "institutional": None, "unicorn": None,
    }
    ctx.update(overrides)
    # dynamic_tp son giriş/stop değerlerinden türetilir; override edilmediyse
    # giriş değişikliğine göre otomatik olarak güncellenir.
    if "dynamic_tp" not in overrides:
        e = ctx["entry"]["entry"]
        s = ctx["entry"]["stop_loss"]
        ctx["dynamic_tp"] = {
            "tp1": _tp_for(e, s, direction)[0],
            "tp2": _tp_for(e, s, direction)[1],
            "tp3": _tp_for(e, s, direction)[2],
            "sources": ["market_structure", "market_structure", "market_structure"],
            "synthetic_targets": False,
        }
    return ctx


def _trade(ctx_overrides, outcome, net_rr):
    """Bir geçmiş aday işlemi: filtre bağlamı + gerçekleştirilen sonuç."""
    return {
        "ctx": ctx_overrides,
        "outcome": outcome,          # "WIN" / "LOSS"
        "net_rr": net_rr,            # işlem başına net R (komisyon+spread sonrası)
    }


def _blocked_trade(direction, outcome, net_rr, **overrides):
    """Belirtilen yönde geçerli bir taban bağlam oluşturup verilen geçersizliği ekler."""
    ctx = base_ctx(direction=direction)
    ctx.update(overrides)
    if "dynamic_tp" not in overrides:
        e = ctx["entry"]["entry"]
        s = ctx["entry"]["stop_loss"]
        ctx["dynamic_tp"] = {
            "tp1": _tp_for(e, s, direction)[0],
            "tp2": _tp_for(e, s, direction)[1],
            "tp3": _tp_for(e, s, direction)[2],
            "sources": ["market_structure", "market_structure", "market_structure"],
            "synthetic_targets": False,
        }
    return _trade(ctx, outcome, net_rr)


def _build_trades():
    """Aynı veri aralığında 26 aday işlem. LONG/SHORT simetrik; kaliteli kurallar
    geçer, kalitesizler tek bir filtreyle engellenebilir."""
    trades = []

    # --- Kaliteli kurallar (tüm filtreler geçer): 4 LONG, 4 SHORT ---
    good = [
        ("LONG", "WIN", 2.5), ("LONG", "WIN", 3.0),
        ("SHORT", "WIN", 2.8), ("SHORT", "WIN", 3.2),
        ("LONG", "WIN", 2.2), ("SHORT", "WIN", 2.6),
        ("LONG", "LOSS", -1.5), ("SHORT", "LOSS", -1.2),
    ]
    for direction, outcome, net_rr in good:
        trades.append(_trade(base_ctx(direction=direction), outcome, net_rr))

    # --- F4: aşırı dar stop (2 LONG + 2 SHORT, hepsi kaybeden) ---
    for i in range(2):
        trades.append(_blocked_trade(
            "LONG", "LOSS", -1.0 - i * 0.1,
            entry={"entry": 100.0, "stop_loss": 99.9, "entry_type": "LIMIT"},
            risk={"risk_setup_valid": True, "entry": 100.0, "stop_loss": 99.9,
                  "weighted_net_rr": 3.0, "execution_rr": 3.0},
        ))
    for i in range(2):
        trades.append(_blocked_trade(
            "SHORT", "LOSS", -1.0 - i * 0.1,
            entry={"entry": 100.0, "stop_loss": 100.05, "entry_type": "LIMIT"},
            risk={"risk_setup_valid": True, "entry": 100.0, "stop_loss": 100.05,
                  "weighted_net_rr": 3.0, "execution_rr": 3.0},
        ))

    # --- F3: geç MARKET girişi (2 LONG + 1 SHORT, hepsi kaybeden) ---
    trades.append(_blocked_trade(
        "LONG", "LOSS", -1.5,
        entry={"entry": 106.0, "stop_loss": 98.0, "entry_type": "MARKET"},
        current_price=100.0,
    ))
    trades.append(_blocked_trade(
        "LONG", "LOSS", -1.6,
        entry={"entry": 107.0, "stop_loss": 98.0, "entry_type": "MARKET"},
        current_price=100.0,
    ))
    trades.append(_blocked_trade(
        "SHORT", "LOSS", -1.4,
        entry={"entry": 94.0, "stop_loss": 102.0, "entry_type": "MARKET"},
        current_price=100.0,
    ))

    # --- F5: net RR minimumin altında (2 LONG + 1 SHORT, hepsi kaybeden) ---
    trades.append(_blocked_trade(
        "LONG", "LOSS", -0.6,
        risk={"risk_setup_valid": True, "entry": 100.0, "stop_loss": 98.0,
              "weighted_net_rr": 0.8, "execution_rr": 0.8},
    ))
    trades.append(_blocked_trade(
        "LONG", "LOSS", -0.7,
        risk={"risk_setup_valid": True, "entry": 100.0, "stop_loss": 98.0,
              "weighted_net_rr": 0.7, "execution_rr": 0.7},
    ))
    trades.append(_blocked_trade(
        "SHORT", "LOSS", -0.5,
        risk={"risk_setup_valid": True, "entry": 100.0, "stop_loss": 102.0,
              "weighted_net_rr": 0.6, "execution_rr": 0.6},
    ))

    # --- F1: HTF/LTF güçlü çetelişi (1 LONG + 1 SHORT, hepsi kaybeden) ---
    trades.append(_blocked_trade(
        "LONG", "LOSS", -2.0,
        mtf={"valid": True, "entry": "LONG", "h4": "BEARISH"},
        liquidity_sweep={"is_sweep": True, "buy_side": False, "sell_side": False,
                         "ambiguous_sweep": False,
                         "post_structure": {"confirmed": False, "direction": None}},
    ))
    trades.append(_blocked_trade(
        "SHORT", "LOSS", -1.8,
        mtf={"valid": True, "entry": "SHORT", "h4": "BULLISH"},
        liquidity_sweep={"is_sweep": True, "buy_side": False, "sell_side": False,
                         "ambiguous_sweep": False,
                         "post_structure": {"confirmed": False, "direction": None}},
    ))

    # --- F6: iki güçlü karşı motor (1 LONG + 1 SHORT, hepsi kaybeden) ---
    trades.append(_blocked_trade(
        "LONG", "LOSS", -1.5,
        smt={"active": True, "direction": "BEARISH", "confidence": 88},
        institutional={"active": True, "direction": "SHORT", "confidence": 86},
    ))
    trades.append(_blocked_trade(
        "SHORT", "LOSS", -1.3,
        smt={"active": True, "direction": "LONG", "confidence": 88},
        institutional={"active": True, "direction": "LONG", "confidence": 85},
    ))

    # --- F2: zayıf/çatışan likidite (2 LONG + 1 SHORT; 1 kazanan, 2 kaybeden) ---
    trades.append(_blocked_trade(
        "LONG", "WIN", 1.0,  # filtre bir kazananı çıkarır
        liquidity_sweep={"is_sweep": True, "buy_side": True, "sell_side": False,
                         "ambiguous_sweep": False,
                         "post_structure": {"confirmed": True, "direction": "BEARISH"}},
        eqh_eql={"eqh": [], "eql": [
            {"price": 90.0, "touches": 3}, {"price": 89.0, "touches": 3},
            {"price": 88.0, "touches": 3},
        ]},
    ))
    trades.append(_blocked_trade(
        "LONG", "LOSS", -1.0,
        liquidity_sweep={"is_sweep": True, "buy_side": True, "sell_side": False,
                         "ambiguous_sweep": False,
                         "post_structure": {"confirmed": True, "direction": "BEARISH"}},
        eqh_eql={"eqh": [], "eql": [
            {"price": 90.0, "touches": 3}, {"price": 89.0, "touches": 3},
            {"price": 88.0, "touches": 3},
        ]},
    ))
    trades.append(_blocked_trade(
        "SHORT", "LOSS", -1.2,
        liquidity_sweep={"is_sweep": True, "buy_side": False, "sell_side": True,
                         "ambiguous_sweep": False,
                         "post_structure": {"confirmed": True, "direction": "BULLISH"}},
        eqh_eql={"eqh": [
            {"price": 110.0, "touches": 3}, {"price": 111.0, "touches": 3},
            {"price": 112.0, "touches": 3},
        ], "eql": []},
    ))

    # --- F5: sentetik TP (1 LONG kazanan çıkarır) ---
    trades.append(_blocked_trade(
        "LONG", "WIN", 2.0,
        dynamic_tp={"tp1": 103.0, "tp2": 106.0, "tp3": 109.0,
                    "sources": ["rr_fallback"], "synthetic_targets": True},
    ))

    # Kaliteli işlemleri her iki veri yarısına dağıt: ilk yarının sonraki
    # yarısı out-of-sample olarak kullanılabilir ve her iki yarıda da
    # filtreden geçen işlemler bulunur.
    good_trades = trades[:8]
    blocked_trades = trades[8:]
    trades = good_trades[:4] + blocked_trades[:9] + good_trades[4:] + blocked_trades[9:]

    return trades


def _stats(trades):
    engine = BacktestEngine()
    for trade in trades:
        engine.record({
            "result": trade["outcome"],
            "rr": abs(trade["net_rr"]),
            "net_rr": trade["net_rr"],
            "side": trade["ctx"].get("direction", "LONG"),
        })
    return engine.statistics(), engine.performance_gate()


def _passes_all_filters(filters, trade):
    """Tüm filtreler çalıştırılır; her engelleyen filtre sayaçlara yansıtılır."""
    result = filters.evaluate_all(**trade["ctx"])
    was_winner = trade["outcome"] == "WIN"
    for name, f in result["filters"].items():
        filters.record_elimination(name, was_winner, was_blocked=not f["passed"])
    return result["allowed"]


def test_filters_do_not_veto_independently_and_report_elimination():
    filters = TradeQualityFilters()
    trades = _build_trades()
    assert len(trades) == 26

    before_stats, before_gate = _stats(trades)

    after_trades = [t for t in trades if _passes_all_filters(filters, t)]
    after_stats, after_gate = _stats(after_trades)

    # Filtreler işlem sayısını gereksiz yere sıfırlamaz.
    assert 0 < len(after_trades) < len(trades)
    # Kaliteli kurallar (ilk 8) kaldı.
    assert len(after_trades) == 8

    # Profit Factor, Net RR (expectancy) ve Max Drawdown değerlendirilir.
    assert after_stats["profit_factor"] > before_stats["profit_factor"], (
        f"PF: before={before_stats['profit_factor']} after={after_stats['profit_factor']}"
    )
    assert after_stats["avg_rr"] > before_stats["avg_rr"], (
        f"expectancy: before={before_stats['avg_rr']} after={after_stats['avg_rr']}"
    )
    assert after_gate["max_drawdown_pct"] <= before_gate["max_drawdown_pct"], (
        f"DD: before={before_gate['max_drawdown_pct']} after={after_gate['max_drawdown_pct']}"
    )

    # Filtre bazlı kazanan/kaybeden çıkarma raporu.
    report = filters.elimination_report()
    assert set(report) == {
        "htf_ltf_alignment", "liquidity_quality", "poi_quality", "entry_distance",
        "stop_quality", "tp_rr_consistency", "motor_conflict",
    }
    for name, item in report.items():
        assert item["evaluated"] == len(trades), name

    total_winners_blocked = sum(item["winners_blocked"] for item in report.values())
    total_losers_blocked = sum(item["losers_blocked"] for item in report.values())

    # Kalite filtresi kaybedenden daha çok kazanan çıkarmamalıdır.
    assert total_losers_blocked >= total_winners_blocked, (
        f"winners_blocked={total_winners_blocked} losers_blocked={total_losers_blocked}"
    )

    # Beklenen eşlemeler: 4 tight stop + 3 wide (4.0-4.5 ATR) MARKET girişi
    # stop kalitesi filtresi ile engellenir.
    assert report["stop_quality"]["blocked"] == 7
    assert report["stop_quality"]["losers_blocked"] == 7
    assert report["entry_distance"]["blocked"] == 3
    assert report["entry_distance"]["losers_blocked"] == 3
    assert report["tp_rr_consistency"]["blocked"] == 4   # 3 düşük net RR + 1 sentetik TP
    assert report["tp_rr_consistency"]["winners_blocked"] == 1
    assert report["tp_rr_consistency"]["losers_blocked"] == 3
    assert report["htf_ltf_alignment"]["blocked"] == 2
    assert report["htf_ltf_alignment"]["losers_blocked"] == 2
    assert report["motor_conflict"]["blocked"] == 2
    assert report["motor_conflict"]["losers_blocked"] == 2
    assert report["liquidity_quality"]["blocked"] == 3
    assert report["liquidity_quality"]["winners_blocked"] == 1
    assert report["liquidity_quality"]["losers_blocked"] == 2


def test_out_of_sample_improvement_holds():
    """İkinci yarı (out-of-sample) önce/sonra karşılaştırması."""
    filters = TradeQualityFilters()
    trades = _build_trades()
    oos = trades[len(trades) // 2:]

    before_stats, _ = _stats(oos)
    after_trades = [t for t in oos if _passes_all_filters(filters, t)]
    after_stats, _ = _stats(after_trades)

    assert len(after_trades) > 0
    assert after_stats["profit_factor"] >= before_stats["profit_factor"], (
        f"OOS PF: before={before_stats['profit_factor']} after={after_stats['profit_factor']}"
    )
    assert after_stats["avg_rr"] >= before_stats["avg_rr"], (
        f"OOS expectancy: before={before_stats['avg_rr']} after={after_stats['avg_rr']}"
    )


def test_long_short_symmetric_elimination():
    filters = TradeQualityFilters()
    trades = _build_trades()
    long_trades = [t for t in trades if t["ctx"].get("direction") == "LONG"]
    short_trades = [t for t in trades if t["ctx"].get("direction") == "SHORT"]

    def blocked_count(group):
        n = 0
        for t in group:
            if not filters.evaluate_all(**t["ctx"])["allowed"]:
                n += 1
        return n

    long_blocked = blocked_count(long_trades)
    short_blocked = blocked_count(short_trades)
    assert long_blocked > 0 and short_blocked > 0
    # Her iki yönde de filtreler etkin; tek tarafa keyfi avantaj yok.
    assert abs(long_blocked - short_blocked) <= 6
