# FINAL PRODUCTION AUDIT v2 — Atlas Sinyal Motoru

Tarih: 2026-08-08 (ikinci inceleme)
Kapsam: look-ahead bias, backtest gerçekçiliği, filtre kalibrasyonu, DB büyüme kontrolü

---

## 0. Karar

**PRODUCTION AUDIT PASSED** (kritik sorun kalmadı — gözlem maddeleri dipnotta).

---

## 1. Test durumu

| Metrik | Değer |
|---|---|
| Test sayısı | **168** |
| Sonuç | **168 pass / 0 fail** |
| Süre | ~38-54 sn (production DB yüklemesi izole) |

Kapsanan regresyonlar:
- **Look-ahead**: `test_lookahead_timing.py` (HTF kapanış kuralı), `test_mtf_lookahead.py` (oluşmakta olan HTF fütüristik OHLC eklenince analiz değişmemeli)
- **MTF timing**: engine canlı + backtest `timing.closed_htf_candles` ortak kod (tek kaynak)
- **Backtest**: partial TP1→breakeven→TP2→TP3, SL-first, OPEN = istatistiğe girmez
- **RR/risk**: `test_risk_engine.py` (dinamik TP tekrarsız seviye, RR yön güvencesi, stop-expand sonrası yeniden hesaplama)
- **Telegram**: `test_telegram_signal_consistency.py`, `test_telegram_service.py`
- **Signal decision**: `test_decision_engine.py` (EXECUTE/WAIT/SKIP eşikleri, blocker sayımı)

---

## 2. Look-ahead bias: **YOK**

- `timing.py::closed_htf_candles(candles, ref_ms, timeframe)` tek kuraldır:
  HTF mumu ancak `c.time + periyot <= ref_ms` ise kullanılır.
- **Canlı** (`engine.py` `analyze`): `ref_ms = son 15m mumunun time`; HTF serisi bu fonksiyonla kırpılır.
- **Backtest** (`backtest_runner._window_up_to`): **aynı** `timing.closed_htf_candles` çağırır — ayrı kod yok.
- Kanıt: test `test_lookahead_timing` (23:45'te 23:00 1h mumu hariç), `test_mtf_lookahead` (fütüristik OHLC 9999/99999 eklenmesi analiz çıktısını boş: baseline == with_future).

## 3. Backtest data leakage: **YOK**

- Sinyal anı : `15m` penceresi `candles[:i]` (tarih bitmez), HTF yalnızca `_window_up_to` (kapanmış) ile.
- Giriş mumu analiz mumunun **sonrası** (`future = candles[i:]`); kapanıştan girişe fütüristik bilgi taşmaz`.
- TP/SL ancak girişinden SONRAKİ mumlarda taranır.

## 4. Filtre kalibrasyonu (pay/payda)

Örneklem: **1075 analiz** — 25 sembol, 320.mumdan 16-mum adımla, gerçek veri (dataset.pkl), `engine.analyze()` çalıştırarak.

### Sinyal dağılımı — payda = tüm analizler (1075)
| Sinyal | Pay/Payda | % |
|---|---|---|
| LONG | 96 / 1075 | %8,9 |
| SHORT | 287 / 1075 | %26,7 |
| WAIT | 692 / 1075 | %64,4 |

### Karar dağılımı — payda = tüm analizler (1075)
| Aksiyon | PAY/PAYDA | % |
|---|---|---|
| EXECUTE | 337 / 1075 | %31,3 |
| EXECUTE_WITH_CAUTION | 30 / 1075 | %2,8 |
| SKIP | 708 / 1075 | %65,9 |

### EXECUTE/kandayda — payda = LONG+SHORT aday sinyaller (383)
| Metrik | Değer |
|---|---|
| LONG+SHORT aday | 383 / 1075 |
| EXECUTE/CAUTION'a geçen | 367 / 383 (%95,8) |
| Sinyalli olup SKIP'e düşen | 16 / 383 |

> Yorum: Karar kapısı adayların **%95,8'ini geçiriyor**; sadece %4,2 SKIP — filtre aşırı sinyal kesmiyor (geçen oturumda korrelasyon TOTAL3 blok düzeltilirken aşırı-engelleme kapatıldı). Filtreleri gevşetmek yerine payda ile birlikte rapor ediliyor; eşiklerde kullanım-açıcı gevşetme yok.

## 5. Backtest gerçek performansı (partial TP/SL, fee dahil, yalnızca KAPANAN işlemler)

| Metrik | STRICT (EXECUTE/CAUTION) | LENIENT (ham LONG/SHORT) |
|---|---|---|
| Analiz | 1075 | 1075 |
| İşlem (kapanan) | **361** | **376** |
| Win | 196 | 204 |
| Loss | 165 | 172 |
| **Win rate** | **%54,29** | %54,26 |
| **Expectancy (R)** | **+0,244R** | +0,246R |
| **Ortalama R** | **+0,244R** | +0,246R |
| **Max drawdown (R)** | **65,15R** | 68,83R |
| **Profit factor** | **1,32** | 1,32 |
| Net R | +88,07 | +92,66 |
| TP1/TP2/TP3 vuruş | 271 / 223 / 196 | 280 / 231 / 203 |

- **EXECUTE kapalı (lenient) sonuçları gerçek performans değil**: yukarıda ayrı sütunda "yalnızca araştırma" olarak sunulur. Gerçek performans tablosu **strict** (EXECUTE/CAUTION) sütunudur.
- WINRATE/R yalnızca **gerçekleşen (kapanan)** işlemlerden hesaplanır; pencere sonunda pozisyonu "OPEN" kalanlar istatistiğe alınmaz (payda açıkça 361 işlem).

> Geçmiş rapordaki "%75 WR / +1,3R" eski **TP1-ilk full-exit** simülasyonundan geliyordu — çıkışsız tek-TP modeli winrate'i şişiriyordu. Partial modelle (TP1→breakeven→TP2→TP3) **gerçekçi edge +0,24R, PF 1,32** ile pozitiftir.

---

## 6. Veritabanı (atlas_journal.db)

| Kalem | Değer |
|---|---|
| DB boyutu | **680.755.200 byte (~649 MB)** |
| Tablo sayısı | 2 |
| Toplam satır | 5.349 (5.141 snapshot + 208 trade) |
| En büyük tablo | `analysis_snapshots` (~592 MB payload) |
| İkinci tablo | `trades` (~83 MB payload) |
| WAL/SHM | **yok** (journal_mode=delete — eski dosya yok) |
| auto_vacuum (db) | 0 (eski DB) |
| freelist | 0 |
| Index | sadece PK (id) — ek index yok |

Büyüme hızı: günde ~6.370 snapshot (~115 KB ort) → günde ~840 MB'ye çıkan yazma. 0,8 günde 680 MB.

### Çözümler
1. **Retention/arşivleme eklendi** (`trade_journal._enforce_retention`): eski snapshot'lar silinmez, `analysis_snapshots_archive` tablosuna **gzip'li** (≈%12 boyut) taşınır.
2. **Varsayılan** `JOURNAL_RETENTION_MAX_SNAPSHOTS` **30000 → 5000** (aktif tablo ~575 MB sınırı; geçmiş gzip arşivde).
3. **auto_vacuum bug'ı düzeltildi**: önceleri `incremental_vacuum` no-op'du (auto_vacuum=0); yeni DB'ler INCREMENTAL olarak açılmakla arşiv sonrası dosya fiziksel olarak küçülür. (Mevcut 680MB DB'de etki için bir kez `VACUUM` gerekir — otomatik değil.)
4. **Öneri (gözlem)**: mevcut 680MB DB'de tek seferlik `VACUUM` + `PRAGMA optimize` ile dosya verimli hale gelir; veri silen PRAGMA kullanılmaz.

---

## 7. Özet — kalan kritik sorunlar

- **Yok** — kritik doğrulama maddelerinin tamamı kapandı:
  ✓ LOOK-AHEAD: YOK (canlı+backtest ortak kural, regression testleri)
  ✓ BACKTEST: YOK (partial TP/SL, gerçekleşen-only, lenient ayrı)
  ✓ FİLTRE: raporlanan (sıkılaştırma yok, pay-denominatorlu), aşık-engelleme düzeltildi
  ✓ DB: boyut sınırlama + gzip arşiv + auto_vacuum fix
  ✓ 168/168 test

- **Gözlem / öneriler (kritik değil)**:
  1. Mevcut 680MB DB'ye tek seferlik VACUUM önerilir (üretim DB'sine elle dokunmadan önce kopyada deneyin).
  2. Edge pozitif ama dar: partial modelde %54,29 WR / +0,244R; per-symbol varyans yüksek (BTC %11 → ONDO %85). Sembol-bazlı filtre gözden geçirilebilir.
  3. spread/fee varsayımı %0,2 (double-side); gerçek likiditeye göre net sonuç değişebilir.