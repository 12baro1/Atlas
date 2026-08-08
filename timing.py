"""
timing.py
Atlas için ORTAK zamanlama / look-ahead kuralları.

HTF mumsal kullanım kuralý:
  Bir üst zaman dilimi mumu, ancak ve ancak tamamen kapandığında analize girer.
      kapandý = (c.time + periyot) <= referans_zaman_ms

Backtest ve canlý analiz AYNI bu fonksiyonu kullanýr. Böylece canlý taramanýn
oluþmakta olan HTF mumunun OHLC'sini geçmiş karara sýz dýrmadýðý garanti edilir
ve backtest ile üretim davranýþý arasýnda zamanlama farký kalmaz.
"""

TF_PERIOD_MS = {
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
    "1w": 7 * 24 * 60 * 60 * 1000,
}


def closed_htf_candles(candles, reference_time_ms, timeframe=None):
    """Bir üst zaman dilimi serisinden referans ana kadar TAMAMEN KAPANMIS mumleri dondurur.

    Kural: yalnizca `c.time + periyot <= reference_time_ms` mumlari dahil edilir.
    Hala olusturmada olan HTF mumunun OHLC'si ileriye donuk bilgi saklar;
    analize alinmaz. Eger timeframe bilinmiyorsa (0 periyot) yalnizca
    `c.time <= ref` sarti uygulanir (eski davranis guvenlik agi olarak korunur).
    """
    if not candles:
        return []
    period_ms = TF_PERIOD_MS.get(str(timeframe).lower(), 0) if timeframe else 0
    out = []
    for c in candles:
        if c.time > reference_time_ms:
            break
        if period_ms > 0 and (c.time + period_ms - reference_time_ms) > 0:
            break
        out.append(c)
    return out