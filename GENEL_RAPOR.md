# ATLAS GENEL RAPORU

Tarih: 2026-08-08
Durum: **Üretime Uygun (Ready)** — detaylı audit için `PRODUCTION_AUDIT.md`

---

## 1. Proje Özeti

Atlas, Bybit swap piyasasından canlı OHLCV çekerek **çoklu zaman dilimi (15m / 1h / 4h / 1d / 1w) SMC (Smart Money Concepts) analizi** yapan, sinyal üreten, sinyalleri gerçek fiyat geçmişinde backtest eden ve Telegram üzerinden raporlayan bir ticaret motorudur.

| Alan | Uygulama |
|---|---|
| Veri | Bybit public OHLCV (ccxt, swap) |
| Analiz | SMC: yapı, likidite, FVG, order block, SMT, unicorn, CISD, trendline |
| Karar | Risk engine + decision engine (EXECUTE / WAIT / SKIP) |
| Çıktı | Telegram kartı + kalite filtresi + manuel skor |
| Backtest | Gerçek veriyle ileri sarma + SL/TP simülasyonu |
| Yürütme | Manual (by default); Bybit demo otomatik mod CLI ile |

Kod tabanı: 60+ modül, ~12.8k satır Python.

---

## 2. Genel Mimariler (modül envanteri)

| Katman | Modüller |
|---|---|
| Veri | `data_engine`, `universe_engine`, `scanner` / `scanner_engine`, `core/candle` |
| Analiz (SMC) | `engine.py`, `market_phase`, `liquidity`, `liquidity_sweep`, `orderblock`, `fvg`, `htf_orderblock`, `htf_fvg`, `bos`, `choch`, `mtf`, `trend`, `trendline`, `smt`, `unicorn`, `cisd`, `institutional`, `volume_profile`, `premium_discount`, `economic_news`, `killzone`, `session_filter`, `ote` |
| Signal | `signal_engine.py`, `confluence`, `entry`, `entry_confirmation`, `setup_quality` |
| Risk & Karar | `risk_engine.py`, `rr_engine.py`, `dynamic_tp_engine.py`, `decision_engine.py` |
| Sonuç takibi | `position_manager.py`, `trade_manager.py`, `trade_journal.py`, `statistics`, `report.py` |
| Telegram | `telegram_engine.py`, `telegram_webhook.py`, `telegram_service.py`, `telegram_auth*`, `manual_trade_quality` |
| Backtest | `backtest.py`, `backtest_runner.py`, `backtest_engine.py` |
| Yürütme | `bybit_execution_engine.py`, `execution_engine.py`, `trade_cooldown_engine.py` |
| Zeka | `learning_engine.py`, `state_engine.py`, `trade_journal` (öğrenme) |

Ana akış: `scan -> engine.analyze -> signal -> decision -> (telegram/backtest)`.

---

## 3. Test sağlığı

| Metrik | Değer |
|---|---|
| Test sayısı | 168 |
| Sonuç | **168 pass / 0 fail** |
| Süre | 38-54 sn (izolasyon sonrası) |
| Darboğaz düzeltme | `tests/conftest.py` — production `atlas_journal.db` (680 MB) testte yüklenmiyor |

Eklenen regresyon kapsamı: dinamik TP'de tekrarsız/yyonlu seviye, RR yön güvencesi, stop-expand sonrası yeniden hesaplama, FVG inversiyon koşulu (dolduru + ters itilme), backtest WIN/LOSS/OPEN semantiği, correlation ve telegram filtreleri.

---

## 3. Tarihsel analiz (Audit çıktısı)

- **4.250 analiz** gerçek veri (25 sembol, sıfır hata) — ikinci audit örneklemi 1.075 analiz.
- Sinyal (1075): LONG %8,9 · SHORT %26,7 · WAIT %64,4
- Karar (1075): EXECUTE %31,3 · SKIP %65,9 · CAUTION %2,8
- Backtest güvencesi (partial TP/SL, gerçekleşen-only): `EXECUTE` kapılı **%54,29 winrate, +0,244R beklenti, PF 1,32** (n=361). Eski %75/+1,3R raporu TP1-first full-exit modelindendir; partial model gerçekçi sonucu verir.

---

## 4. Üretim Yürütme

```bash
python3 main.py                  # tek sefer tarama
./run_bot.sh start               # sürekli (900s, otorpelti)
python3 report.py                # canlı performans
python3 backtest.py --symbol # edge doğrulama
```

Üretim opsiyonları: Telegram token (`.env`), manual mode (önerilen), cooldown, korrelasyon, ekonomi filtresi.

---

## 5. Açık Öneriler Sıralı

| # | Madde | Öncelik |
|---|---|---|
| 1 | DB büyümesi: retention + gzip arşiv + auto_vacuum fix uygulandı; mevcut 680MB DB için tek seferlik VACUUM önerilir | Tamamlandı |
| 2 | Kısmi çıkış (partial TP2/TP3) simülasyonu | Tamamlandı |
| 3 | Filtre kalibrasyonu: örneklem + pay/payda ile raporlanıyor; aşırı-engelleme düzeltildi | Tamamlandı |
| 4 | Look-ahead: HTF teknik tek kural (`timing.closed_htf_candles`) — canlı + backtest aynı | Tamamlandı |
| 5 | Gözlem: per-symbol varyans yüksek (BTC %11 → ONDO %85); sembol bazlı kalibrasyon sürekli | Sürekli |

---

## 6. Özet

**Atlas, SMC tabanlı analitik + izleme + Telegram + backtest döngüsünü uçtan uca çalıştırabilen, 168/168 testi geçen ve gerçek veriyle pozitif beklenti (partial model %54,3 WR / +0,24R / PF 1,32) üreten bir sistemdir.** Look-ahead yok, backtest data leakage yok, DB büyümesi retention + gzip arşiv + auto_vacuum fix ile kontrol altına alınmıştır.