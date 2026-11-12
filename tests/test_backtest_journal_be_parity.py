"""P0-2 regresyon testleri: backtest <-> trade_journal aynı-mum BE paritesi.

trade_journal.resolve_signal_outcome ile backtest_runner.simulate_trade_partial
aynı mum değerlendirmesini kullanmalıdır:
- Mum başında taşınan stop önce kontrol edilir (SL önceliği).
- TP'ler sırayla dolar; her dolumdan sonra taşınan koruyucu stop AYNI mumun
  aralığındaysa kalan pay konservatif biçimde o mumda kapanır ve sonraki
  hedefler sayılmaz (OHLC mum içi sırayı kanıtlayamaz).
- Taşınan stop journal gibi tam stop fiyatından dolar; yalnızca İLK stopta
  gap modellemesi (mum açılışı) backteste özgüdür — parite testleri gap'siz
  mumlar kullanır.

Karşılaştırma: journal gross_realized_r (maliyet öncesi R) <-> backtest net_rr.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from backtest_runner import simulate_trade_partial
from core.candle import Candle
from trade_journal import TradeJournal

SYMBOL = "BTC/USDT:USDT"
BASE_TIME = 1_700_000_000_000
DEFAULT_WEIGHTS = {"tp1": 0.5, "tp2": 0.3, "tp3": 0.2}


def _candle(index, open_, high, low, close):
    return Candle(
        time=BASE_TIME + index * 60_000,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=120.0,
    )


def _run_parity(tmp_path, direction, entry, stop_loss, targets, candles, weights):
    """Aynı mum serisini journal ve backtest üzerinde koşturur; (gross, out) döner."""
    journal = TradeJournal(db_path=tmp_path / "j.sqlite")
    outcome = journal.register_signal_outcome(
        symbol=SYMBOL,
        direction=direction,
        entry=entry,
        stop_loss=stop_loss,
        tp1=targets[0],
        tp2=targets[1] if len(targets) > 1 else None,
        tp3=targets[2] if len(targets) > 2 else None,
        opened_at=BASE_TIME,
    )
    outcome["partial_weights"] = dict(weights)

    resolved = journal.resolve_signal_outcome(outcome, candles)
    assert resolved is not None, "Journal pozisyonu kapatmalıydı"

    backtest = simulate_trade_partial(
        entry,
        stop_loss,
        list(targets),
        candles,
        direction,
        tp_weights=dict(weights),
    )
    return resolved, backtest


def test_parity_long_tp1_and_be_same_candle(tmp_path):
    """TP1 ve taşınan BE aynı mumda: kalan pay konservatif kapanır (0.5R).

    TP2 (102.0) mum aralığında olsa da sayilmaz — journal ile birebir.
    """
    candles = [_candle(1, 100.0, 102.5, 99.9, 100.4)]
    resolved, backtest = _run_parity(
        tmp_path, "LONG", 100.0, 99.0, [101.0, 102.0, 103.0], candles, DEFAULT_WEIGHTS
    )

    assert resolved["tps_hit"] == [1]
    assert resolved["hit_sl"] is True
    assert resolved["gross_realized_r"] == pytest.approx(0.5, abs=1e-6)
    assert backtest["levels"] == resolved["tps_hit"] == [1]
    assert backtest["net_rr"] == pytest.approx(resolved["gross_realized_r"], abs=1e-6)
    assert backtest["net_rr"] == pytest.approx(0.5, abs=1e-6)
    assert backtest["exit_reason"] == "TRAILING_STOP"
    assert backtest["exit_offset"] == 0
    assert backtest["exit_price"] == pytest.approx(100.0, abs=1e-9)


def test_parity_long_tp1_then_be_next_candle(tmp_path):
    """TP1 bir mumda, taşınan BE stopu sonraki mumda tetiklenir (0.5R)."""
    candles = [
        _candle(1, 100.0, 101.2, 100.1, 100.6),  # TP1 dolar; BE(100) aralıkta değil
        _candle(2, 100.4, 100.7, 99.9, 100.0),   # BE stop tetiklenir
    ]
    resolved, backtest = _run_parity(
        tmp_path, "LONG", 100.0, 99.0, [101.0, 102.0, 103.0], candles, DEFAULT_WEIGHTS
    )

    assert resolved["tps_hit"] == [1]
    assert resolved["gross_realized_r"] == pytest.approx(0.5, abs=1e-6)
    assert backtest["levels"] == [1]
    assert backtest["net_rr"] == pytest.approx(0.5, abs=1e-6)
    assert backtest["exit_reason"] == "TRAILING_STOP"
    assert backtest["exit_offset"] == 1


def test_parity_long_same_candle_sl_and_tp1_is_conservative(tmp_path):
    """Aynı mumda SL ve TP1: stop önce kontrol edilir -> -1.0R, TP sayilmaz."""
    candles = [_candle(1, 100.0, 101.3, 98.6, 99.0)]
    resolved, backtest = _run_parity(
        tmp_path, "LONG", 100.0, 99.0, [101.0, 102.0, 103.0], candles, DEFAULT_WEIGHTS
    )

    assert resolved["tps_hit"] == []
    assert resolved["hit_sl"] is True
    assert resolved["gross_realized_r"] == pytest.approx(-1.0, abs=1e-6)
    assert backtest["levels"] == []
    assert backtest["tp"] == 0
    assert backtest["net_rr"] == pytest.approx(-1.0, abs=1e-6)
    assert backtest["exit_reason"] == "STOP"
    assert backtest["exit_offset"] == 0


def test_parity_short_tp1_and_be_same_candle(tmp_path):
    """SHORT ayna senaryosu: TP1 + BE aynı mumda; TP2 dokunsa da sayilmaz (0.5R)."""
    candles = [_candle(1, 100.0, 100.1, 97.5, 98.5)]
    resolved, backtest = _run_parity(
        tmp_path, "SHORT", 100.0, 101.0, [99.0, 98.0, 97.0], candles, DEFAULT_WEIGHTS
    )

    assert resolved["tps_hit"] == [1]
    assert resolved["hit_sl"] is True
    assert resolved["gross_realized_r"] == pytest.approx(0.5, abs=1e-6)
    assert backtest["levels"] == [1]
    assert backtest["net_rr"] == pytest.approx(0.5, abs=1e-6)
    assert backtest["exit_reason"] == "TRAILING_STOP"
    assert backtest["exit_offset"] == 0
    assert backtest["exit_price"] == pytest.approx(100.0, abs=1e-9)


def test_parity_short_same_candle_sl_and_tp1_is_conservative(tmp_path):
    """SHORT: aynı mumda SL ve TP1 -> stop önceliği, -1.0R."""
    candles = [_candle(1, 100.0, 101.4, 98.7, 100.5)]
    resolved, backtest = _run_parity(
        tmp_path, "SHORT", 100.0, 101.0, [99.0, 98.0, 97.0], candles, DEFAULT_WEIGHTS
    )

    assert resolved["tps_hit"] == []
    assert resolved["gross_realized_r"] == pytest.approx(-1.0, abs=1e-6)
    assert backtest["net_rr"] == pytest.approx(-1.0, abs=1e-6)
    assert backtest["exit_reason"] == "STOP"
    assert backtest["exit_offset"] == 0


def test_parity_multi_tp_same_candle_then_tp1_stop(tmp_path):
    """Aynı mumda TP1+TP2, ardından TP1 seviyesine taşınan stop doldurulur.

    TP1: +0.5*1R; TP2: +0.3*2R; kalan 0.2 pay TP1 stopundan (101) +0.2*1R
    -> toplam 1.3R (journal ile birebir).
    """
    candles = [_candle(1, 100.0, 102.5, 100.5, 102.2)]
    resolved, backtest = _run_parity(
        tmp_path, "LONG", 100.0, 99.0, [101.0, 102.0, 103.0], candles, DEFAULT_WEIGHTS
    )

    assert resolved["tps_hit"] == [1, 2]
    assert resolved["hit_sl"] is True
    assert resolved["gross_realized_r"] == pytest.approx(1.3, abs=1e-6)
    assert backtest["levels"] == [1, 2]
    assert backtest["net_rr"] == pytest.approx(1.3, abs=1e-6)
    assert backtest["exit_reason"] == "TRAILING_STOP"
    assert backtest["exit_offset"] == 0
    assert backtest["exit_price"] == pytest.approx(101.0, abs=1e-9)


def test_parity_full_ladder_same_candle(tmp_path):
    """Merdiven tam dolar (BE/TP1 stopları mum aralığının dışında): 1.7R, TP3 çıkışı.

    0.5*1R + 0.3*2R + 0.2*3R = 1.7R; hit_sl yok, journal ve backtest eşit.
    """
    candles = [_candle(1, 101.6, 103.5, 101.2, 103.0)]
    resolved, backtest = _run_parity(
        tmp_path, "LONG", 100.0, 99.0, [101.0, 102.0, 103.0], candles, DEFAULT_WEIGHTS
    )

    assert resolved["tps_hit"] == [1, 2, 3]
    assert resolved["hit_sl"] is False
    assert resolved["gross_realized_r"] == pytest.approx(1.7, abs=1e-6)
    assert backtest["levels"] == [1, 2, 3]
    assert backtest["tp"] == 3
    assert backtest["net_rr"] == pytest.approx(1.7, abs=1e-6)
    assert backtest["exit_reason"] == "TP3"
    assert backtest["exit_offset"] == 0


def test_parity_partial_remainder_two_tp_weights(tmp_path):
    """2 TP'li sinyal: ağırlıklar aktif seviyelere normalize edilir (0.625/0.375).

    TP1 (1R) -> kalan 0.375 pay sonraki mumda BE'den (0R) çıkar -> 0.625R.
    """
    candles = [
        _candle(1, 100.0, 102.4, 100.2, 101.5),
        _candle(2, 100.6, 101.0, 99.8, 100.2),
    ]
    weights = {"tp1": 0.5, "tp2": 0.3}
    resolved, backtest = _run_parity(
        tmp_path, "LONG", 100.0, 98.0, [102.0, 104.0], candles, weights
    )

    assert resolved["tps_hit"] == [1]
    assert resolved["gross_realized_r"] == pytest.approx(0.625, abs=1e-6)
    assert backtest["levels"] == [1]
    assert backtest["net_rr"] == pytest.approx(0.625, abs=1e-6)
    assert backtest["exit_reason"] == "TRAILING_STOP"
    assert backtest["exit_offset"] == 1
