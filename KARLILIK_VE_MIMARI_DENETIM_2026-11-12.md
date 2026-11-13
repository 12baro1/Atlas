# ATLAS — KÂRLILIK VE MİMARİ GELİŞTİRME DENETİMİ

Tarih: 2026-11-12 | Denetim kodu: main @ `ee6c838` (PR #110 dahil) | Kod değişikliği: **YAPILMADI**

Ölçüm ortamı: mevcut backtest altyapısı (`backtest.py` + `backtest_runner.py`, değiştirilmeden), BTC/USDT:USDT 28 gün + ETH/USDT:USDT 12 gün, 15m TF, gerçek Bybit verisi, üretim ücret modeli (maker 0.02%, taker 0.055%, spread 0.02%, slippage 0.03%). Test süiti: **836 passed / 3 skipped (92 sn)**.

> **PR #110 durumu:** Üç P0 düzeltmesi (P0-1 `reconcile_final_geometry_payload`, P0-2 aynı-mum journal-parite simülasyonu, P0-3 imzalı TP yön doğrulaması) **main'e merge edilmiş** (ee6c838, 2026-11-12 03:26 +03). Rapor mevcut main'i esas alır; PR #110'ın getirdiği düzeltmeler doğrulandı ve regresyon testleri suite'te mevcut (`test_finalize_geometry_risk_reconciliation.py`, `test_backtest_journal_be_parity.py`, `test_tp_rr_consistency_direction.py`).

---

## 0. YÖNETİCİ ÖZETİ

Atlas artık **matematiksel olarak tutarlı** bir sistem: ücretler tek kez sayılıyor (PR #110 P0-1), backtest ↔ journal aynı kural setiyle simüle ediyor (P0-2), yanlış yönlü TP'ler imzalı doğrulamayla eleniyor (P0-3), look-ahead disiplini güçlü ve test edilmiş. **Ancak ölçümler karar mimarisinde kalıcı kârlılığı belirleyen üç yapısal sorunu teyit etti:**

1. **Tek karar otoritesi resmi olarak var, fiilen esnetilmiş durumda.** `quality_gate_active` canlı akışta her zaman true olduğu için DecisionEngine'in skor eşikleri, override'ı ve kalite blocker zinciri **ölü kod**; fiilen kural "geometri+risk+trade-quality geçen her kurulum EXECUTE"tur. Setup kalitesi puanla değil, geometri geçerliliğiyle belirleniyor.
2. **Aynı kanıt 5–7 ayrı motorda yeniden puanlanıyor.** Sweep 6 yerde, MTF uyumu 6 yerde, RR eşiği 5 farklı eşikle 5 yerde, stale-TP1 mantığı 4 kopya halinde. Bu hem çift sayım hem de motorlar arası çelişki (bir motorun açtığı kapıyı diğerinin kapatması) üretiyor.
3. **Ölçülebilir segmentasyon ve kalibrasyon döngüsü yok.** Backtest yalnızca yön+MTF bağlamı kırılımı veriyor; MARKET/LIMIT P&L, rejim, volatilite, setup tipi, TP-davranışı kırılımı yok. Parametre kararları ölçümsüz alınıyor; walk-forward/OOS altyapısı hiç yok.

**Ölçüm (35 işlem, 4 kazanan):** ETH 12g (n=19) ve BTC 28g (n=16) — winrate %15.8 / %6.2, PF 0.445 / 0.016, expectancy −1.38R / −3.18R, maliyet 1.76R / 2.33R-işlem. Kayıpların tamamı sürtünme kaynaklı: stop mesafesi adayların ~%85'inde 0.50 ATR altında ve 13/16+13/19 işlemde bacak sürtünmesinin (≈%0.125) altında → her stop-out brüt −1.0R iken net −1.2R…−7.6R. **Kabul kapısının maliyet modeli stop bacağını dışlıyor; gerçekleşen R içeriyor; boyutlandırma telafi ediyor** — üç katman üç farklı maliyet birimi. Ham SHORT sinyallerinin ~%99.9'u SKIP (SHORT-only sweep gate); 15m-reversal yolu hiç ateşlemedi. Bu üç ölçüm, raporun öncelik sırasını belirlemektedir (P0-0: maliyet-farkındalıklı stop tabanı + tek maliyet birimi).

---

## 1. MOTOR ENVANTERİ

Her motor için: görev / veri / çıktı / final karara etki / çakışma / ölü kod / yanlış-pozitif-yanıltı (FP/FN) riski.

### 1.1 AtlasMainEngine (`atlas_main_engine.py`)
- **Görev:** Orkestratör; `build_setup` (aday seçimi), `finalize_setup_geometry` (SL/TP merdiveni kilidi), `decide` (DecisionEngine sarmalayıcı), `apply_operational_gates` (haber/cooldown hard gate; correlation uyarı).
- **Veri:** Tüm motor çıktıları (MotorProxy üzerinden; motor hatası analizi durdurur — güvenli default).
- **Çıktı:** Tek setup + final karar (`decision_authority: ATLAS_MAIN_ENGINE`).
- **Final karara etki:** Post-decision geometri guard'ı (`_validate_execution_geometry`) SKIP; operasyonel gate SKIP. İkisi de karar sonrası — geçerli.
- **Çakışma:** `candidate_rank` SetupReasoningEngine.rank ile aynı tuple'ın kopyası (drift riski). `max_limit_distance_pct` parametresi imzada var, gövdede hiç kullanılmıyor — LIMIT mesafe limiti sadece etiket/uyarı.
- **Ölü kod:** `_validate_execution_geometry.max_limit_distance_pct`.
- **FP/FN:** "işlem ver" TUI'sı `pending_limit` adaylarında `decision_action` kontrolü yapmıyor (`atlas_tui.py:411`) — SKIP kararı verilmiş LIMIT kurulumu "geçerli kurulum" sayılıp 1. sıraya seçilebiliyor (kartta "İŞLEME GİRME" yazar, talimat sızmez; ama sayaç/sıralama kararı bypass eder). FN: MARKET >0.35 ATR / >0.3% uzaktaysa geçerli retest kurulumu bloke (`config.py:127-128`).

### 1.2 SetupReasoningEngine (`setup_reasoning_engine.py`)
- **Görev:** Tüm yön başına POI adaylarını üretir (OB/HTF-OB/FVG/HTF-FVG/Breaker/IFVG/Unicorn), mesafe/geçerlilik/ RR eleme yapar, tek aday seçer, gerekçe üretir.
- **Veri:** 15m yapı durumu, HTF POI'ler, sweep, OTE, ATR, RiskEngine ön-hesap, entry_optimizer ortak POI fiyatı.
- **Çıktı:** Seçili aday (entry/stop/TP ladder/entry_type/poi_source/evidence) + `entry_reason_code`.
- **Final karara etki:** Kritik — aday yoksa WAIT (`NO_MAIN_ENGINE_SETUP`); `NET_RR_BELOW_MINIMUM`, `ENTRY_TOO_FAR` kodlarıyla filtre.
- **Çakışma:** (a) Kendi POI'si "destekleyici kanıt" olarak kanıt havuzuna geri ekleniyor → kendini doğrulayan sıralama (`setup_reasoning_engine.py:510`); (b) `getattr(Config, "PARTIAL_EXIT_WEIGHTS", None)` **yok** → aday-öncesi maliyet eşit ağırlıkla (1/n), RiskEngine ise 0.5/0.3/0.2 kullanıyor → ön-eleme ve final maliyeti tutarsız (`setup_reasoning_engine.py:574` vs `config.py:380`).
- **Ölü kod:** Yok (rank kopyası bkz. 1.1).
- **FP/FN:** FP: self-referential kanıt sıralamayı şişirebilir. FN: >2 ATR veya >5% uzak POI → WAIT (üç motor daha bu mesafeyi ayrı ayrı ölçüyor).

### 1.3 DecisionEngine (`decision_engine.py`)
- **Görev:** Tek skor+karar noktası; kritik blocker'ları toplayıp EXECUTE/CAUTION/WAIT/SKIP üretir.
- **Veri:** 20 girdi (signal, confluence, entry, risk, mtf, ote, htf_ob, sweep, cisd, vp, institutional, unicorn, smt, phase, regime, trade_quality, setup_consensus…).
- **Çıktı:** `action`, `reason`, `total_score`, `critical_blockers`, `soft_blockers`.
- **Final karara etki:** Nominal otorite; **fiilen etkisiz kalan bölümler:** skor eşikleri (80/45/35), `_high_quality_mismatch_override`, `_collect_quality_blockers`, legacy confidence gate — hepsi `quality_gate_active` (canlıda her zaman true) dalının arkasında ölü. `news_filter/correlation/cooldown` girdileri `_normalize_context`'te yutuluyor (sonradan `apply_operational_gates` kapsıyor).
- **Çakışma:** SHORT-only sweep hard gate (`:116-130`) — LONG karşılığı yok (bkz. §2.5).
- **Ölü kod:** `_extract_confidence` (hiç çağrılmıyor), `modules/_discover_modules` (normalize edilir, tüketilmez), eşik/override blokları.
- **FP/FN:** FP: "EXECUTE = kritik blocker yok" kuralı yüzünden zayıf kanıtlı ama geometrik olarak temiz kurulumlar geçebiliyor (1 güçlü karşı motor ≤85 conf yalnızca uyarı; Ranging faz engel değil). FN: H4-bear trend-devam SHORT'ları (15m buy-side sweep + teyidi yoksa) hiç yayımlanamıyor.

### 1.4 SignalEngine (`signal_engine.py`)
- **Görev:** Yön/kalite/wait_reason/konfidence/grade üretimi.
- **Veri:** Tüm motor çıktıları + setup_quality (0.45/0.55 blend).
- **Çıktı:** signal payload (yön, konfidence, grade, wait_reason, reasons).
- **Final karara etki:** WAIT yolu (yön WAIT → karar `waiting_for_setup` kısayolu).
- **Çakışma:** `quality_gate_active` trueyken setup_quality veto dalı (`:88-90`) atlanıyor → SetupQualityEngine "trade_allowed=False" herhangi bir şeyi engelleyemiyor (yalnız confidence blend'ini düşürüyor). TradeQuality veto yönü WAIT'e çeviriyor (`:92-94`) → DecisionEngine'in SKIP + blocker zinciri devre dışı kalıyor, veto "WAIT" olarak yeniden etiketleniyor.
- **Ölü kod:** veto dalları (canlı akışta).
- **FP/FN:** Konfidence üçlü sayım (confluence + modül deltaları + setup_quality alt skorları) → puan şişkin ama tek karar noktasına yön etkisi sınırlı.

### 1.5 EntryEngine (`entry_engine.py`)
- **Görev:** POI tabanlı MARKET/LIMIT seçimi, mesafe/stop temel geometri.
- **Veri:** POI bölgesi, sweep teyit yaş (≤2 bar), OTE sınırları, ATR.
- **Çıktı:** entry/stop/entry_type + score/checks + poi_zone/poi_source.
- **Final karara etki:** Zayıf — final setup SetupReasoningEngine adayından geliyor; EntryEngine çıktısından yalnız kanıt alanları tüketiliyor (`config.py:114-116` "evidence-only").
- **Çakışma:** "High probability setup" etiketi (`entry_engine.py:549`) — puan = olasılık izlenimi veriyor (kontrat ihlali riski, kozmetik).
- **Ölü kod:** structure-direction fallback (config off), `_structure_fallback_levels` (teşhis amaçlı, asla uygulanabilir değil).
- **FP/FN:** MARKET aynı mumda sweep+giriş imkânsız (2 bar teyit gecikmesi dürüst). OTE `valid=False` iken bile OTE sınırları giriş fiyatını şekillendiriyor (`entry_engine.py:120-146`).

### 1.6 EntryConfirmationEngine (`entry_confirmation_engine.py`)
- **Görev:** Giriş teyidi (MTF+POI geçerlilik + 15m çelişki takibi).
- **Veri:** mtf, poi, 15m çelişki durumu.
- **Çıktı:** `confirmed`, `confirmation_profile`, `requirements`.
- **Final karara etki:** confluence'a sabit +10.
- **Çakışma/Çift sayım:** `confirmed=True` MTF+POI geçerliyse **koşulsuz** — `15m_conflict=True` iken bile (`:83-96`); bu +10 tüm geçerli kurulumlarda sabit, ayırt edici değil ve MTF/POI geçerliliğinin confluence'taki +15 ile çift sayımı.
- **Ölü kod:** Yok ama "conflict retained as execution input" pratiğe hiç bağlanmamış.
- **FP:** Çelişkiyi maskeleyen sabit +10.

### 1.7 EntryOptimizer (`entry_optimizer.py`)
- **Görev:** Kanıt ağırlıklı ortak POI fiyatı (ünicorn bölgesi dahil).
- **Çıktı:** POI fiyat/bölge + kalite faktörleri.
- **Final karara etki:** Aday üretimine giriş fiyatı olarak.
- **Çakışma:** Kalite faktörleri yalnızca küçültücü (down-weight) — büyütücü yönü yok; EntryEngine ile POI seçimi tekrarlanıyor.
- **Ölü/kusur:** `except (TypeError, TypeError, ...)` kopya hata sınıfı (`:329`).
- **FP/FN:** Düşük.

### 1.8 MTFEngine (`mtf_engine.py`)
- **Görev:** 4H otorite yön; weekly/daily bağlam; 4H nötrken 15m sweep-reversal yolu.
- **Çıktı:** `{entry, entry_source, trend, weekly/daily/h4, valid, conflicts}`.
- **Final karara etki:** 6 yerde tüketiliyor (confluence, decision, setup_quality, trade_quality, F1, entry_confirmation) → çift sayım.
- **FN riski:** `_confirmed_ltf_reversal` son olayın **etiketli** CHoCH olmasını şart koşuyor; sweep-reclaim + iki CHoCH (sonuncusu etiketsiz) → None. Kod tabanının en katı kapısı; tersine kilitlenme (FN) riski yüksek.

### 1.9 Structure / CHoCH / BOS (`core/market_structure_engine.py`, `choch_engine.py`, `bos_engine.py`)
- **Görev:** 5×5 teyitli pivotlar; BOS/CHoCH olayları; her TF için yeniden inşa (`_analyze_timeframe`).
- **FP/FN:** Pivot filtresi düzeltildi (CORE_FOUNDATION_AUDIT); temiz. Her TF analizi `motor_call_counts`'ı kirletiyor (teşhis gürültüsü).

### 1.10 Liquidity / Sweep / SFP (`liquidity_sweep_engine.py`)
- **Görev:** Pool öncesi wick-through + close-reject sweep; post-sweep yapı teyidi; reclaim invalidation.
- **Veri:** Likidite katmanları (EQH/EQL/session uçları), 15m mumlar.
- **Çıktı:** `is_sweep/is_breakout/ambiguous_sweep/post_structure/confirmation_age_bars`.
- **Final karara etki:** 6 motor + SHORT hard gate.
- **Çakışma/FP:** Pool referansı hiç yokken legacy fallback basit wick-through'u `is_sweep=True` olarak etiketliyor (`:131-144`) ve CISD +10, confluence puanını besliyor (kod yorumu "MARKET girişini teyit edemez" diyor ama puan akışını durdurmuyor).
- **FP/FN:** Aynı-mum sweep+MARKET imkânsız (dürüst); reclaim invalidation close-bazlı (güvenli).

### 1.11 OB / FVG / OTE (`orderblock_engine.py`, `fvg_engine.py`, `ote_engine.py`, `htf_*`)
- **Görev:** POI üretimi; tazelik/kontrol; OTE bölge hesabı.
- **Kusurlar (doğrulandı):** (a) Bearish OB `"index": idx-1` vs bullish `"index": ob_index` (`orderblock_engine.py:122` vs `:78`) → bearish breaker taraması OB'den önceki mumdan başlayabilir → SHORT breaker FP. (b) Kısmi dolum FVG "fresh" sayılıyor → 90% dolmuş bölgeye "taze" POI girişi FP. (c) `detect_inversion` docstring bozuk (mojibake).
- **Final karara etki:** Aday havuzuna POI; POI tipi `poi_source` olarak trade ledger'a işleniyor (ölçümde segmentasyon için kullanılabilir — bkz. §3).

### 1.12 CISD / Unicorn (`cisd_engine.py`, `unicorn_engine.py`)
- **Görev:** CISD = yapı kırılım teyidi; Unicorn = OB∩FVG nadir bölge.
- **Kusur/ölü:** CISD legacy no-pool sweep'ten +10 alabiliyor; Unicorn `_trade_levels` hiçbir tüketiciye bağlı değil (ölü).

### 1.13 Institutional Flow (`institutional_engine.py`)
- **Görev:** CVD/OI/funding/breadth/MM oy birliği ile kurumsal yön + boyut faktörü.
- **Kusurlar (doğrulandı):** (a) CVD puanı **+12 her iki yönde** (`:614-617`) — yön-bağımsız sabit, skor anlamı yok; (b) `confirmed_by_reclaim = (close-prev_close) != 0` — "fiyat kıpırdadı" = "reclaim onaylı" (`:371`); (c) yön 5 proxy'nin oyu — çoğu proxy; (d) `liquidity_voids/session_statistics/trade_analytics/heatmap/dynamic_engine_weighting/adaptive_signal_weighting/stop_hunt/market_maker` çıktılarının hiçbir dış tüketicisi yok (hesaplama maliyeti, karar etkisi sıfır).
- **Kontrol (iyi):** Boyut faktörü [0.65,1.0] ile küçültücü clamp — yanlış okuma boyutu büyütemez (`risk_engine.py:435-437`).

### 1.14 Trade Quality Filters / TradeQualityEngine (`trade_quality_filters.py`, `trade_quality_engine.py`)
- **Görev:** F1–F6 eleme filtreleri + nihai kalite gate (blockers → allowed).
- **Kusurlar:** (a) F1 "onaylı 15m reversal" unblock dalı **ölü** — unblock için `entry_source=="CONFIRMED_15M_REVERSAL"` şart; bu değer MTFEngine yalnız 4H **nötrken** üretilebiliyor; 4H karşıyken (unblock'un tek gerekli olduğu durum) asla üretilemez → ters-trend onaylı reversal üç motordan geçip F1'de ölüyor; test yapay mtf dict'iyle geçiyor. (b) `MINIMUM_RR=3.0` gross hedef eşiği hâlâ trade_quality_engine'de zorlanıyor (`:284-285`) — net-RR=2.0 politikasıyla çelişiyor; net 2.2 / gross 2.5 geçerli kurulum bloke. (c) Elimination sayaçları canlı akışa bağlı değil (yalnız test).
- **Ölü config:** `QUALITY_HTF_STRONG_CONFLICT_BLOCK`, `QUALITY_REQUIRE_SWEEP` hiçbir yerde okunmuyor.

### 1.15 RiskEngine / RREngine (`risk_engine.py`, `rr_engine.py`)
- **Görev:** Boyut, RR zinciri (rr_by_tp, weighted, weighted_net, execution_rr, cost_drag), kısmi çıkış ağırlıkları, tight-stop politikası; PR #110 P0-1 `reconcile_final_geometry_payload` tüm türetilmiş alanları geometri kilidi sonrası yeniden türetiyor (çift sayım yok — testli).
- **Kontrol:** Maliyet tek kaynak (`execution_costs.py`); plan (giriş bacağı + TP-exit maker) ve stop maliyeti ayrı metrikler; pozisyon boyutu zayıf edge'de `net_rr/MINIMUM_NET_RR` ile küçülüyor; boyut faktörü yalnız küçültücü.
- **Kalan boşluklar:** (a) Reconcile'da `float(getattr(Config,"INITIAL_BALANCE",...))` korumasız (bozuk değer → exception); (b) `calculate_breakdown` None dönünce boyut `net_rr=None` ile 1.0 faktörle ölçekleniyor (teori olarak erişilebilir olmayan yol; finalize önce geçersiz kılıyor); (c) degrade yolda `execution_rr` gross'a düşebiliyor (`risk_engine.py:536`, `trade_quality_filters.py:660` `weighted_net_rr or execution_rr`) → net-RR gate gross üzerinden çalışabilir (nadir).
- **Ölü kod:** `dynamic_tp_engine._select_target_for_rr`, `_nudge_level` (hiç çağrılmıyor); `PositionManager` (30/30/40 + maliyet-dahil BE — journal modeliyle (0.5/0.3/2 + BE=entry) ÇELİŞİYOR ama üretimde çağrılmıyor; dormant tuzak); `TradeManager` (inşa edilir, `build()` hiç çağrılmaz).

### 1.16 Dynamic TP Engine (`dynamic_tp_engine.py`)
- **Görev:** Yapısal hedef seçimi (likidite/FVG/OB/yapı etiketleri), min TP1-RR 0.8, küme ayrımı, yön-farkındalıklı sıralama; sentetik 1R/2R/3R fallback üretimde kapalı + kalite filtresi reddediyor.
- **Çakışma:** Yok (stop expand → TP rebuild → risk recompute → finalize reconcile zinciri tutarlı).
- **Ölü kod:** yukarıdaki iki method.

### 1.17 Trade Journal / Learning (`trade_journal.py`, `learning_engine.py`)
- **Görev:** Sinyal sonuç kaydı (SQLite), manuel/ayrı ledger, outcome çözümleme (SL öncelik, sıralı TP, TP1→BE=entry, TP2→TP1, aynı-mum muhafazakâr kapanış), MFE/MAE, arşivleme; learning: kanonik öznitelik → 4 seviyeli bucket (exact/family/global), Bayesian+Wilson, min-örneklem rampası, ±6/±10 sınırlı düzeltme.
- **Kritik bulgular:** (a) **Journal DB 782MB** — `trades` tablosunda işlem başına ~2.6MB (7.7MB'a kadar) tam `analysis` payload'ı, snapshot başına ~375KB (`modules` 2.1MB); 1.391 snapshot + 123 trade = ~777MB. Retention var ama DB fiziksel büyüyor (freelist 0). Android/UserLAnd için disk/I/O sorunu. (b) Learning deposu **boş** (`records_fed=0`) — öğrenme şu an hiç etki etmiyor; geçmiş besleme %100 teorik sinyal-sonucu (gerçek fill değil). (c) Parametre değişikliği doğrulama/rollback yok; bucket `last_reason` dışında neden-taksonomisi yok. (d) tracked/manual `pnl_rr` ücretler BRÜT — backtest/journal-signal net; üç ledger üç farklı maliyet raporlaması.
- **FP/FN:** Outcome çözümlemesi P0-2 ile parite testli; maliyet uygulaması net; `WIN` yalnız net>0 (güvenli).

### 1.18 BacktestRunner (`backtest.py`, `backtest_runner.py`, `backtest_engine.py`)
- **Görev:** Tarihsel replay; closed-candle karar + next-open MARKET fill + LIMIT touch-fill (gap-düzeltmeli, intrabar-muhafazakâr) + stop-first + journal-parite (P0-2) + segmentli/checkpoint'li çalışma.
- **Güçlü:** `timing.closed_htf_candles` tek kaynak (canlı+backtest); SMT peer re-align; listing-aware warmup; overlap dedup (`_setup_identity`); 200 işlem/PF≥1.5/≤%10 DD performans kapısı.
- **Boşluklar:** (a) Walk-forward/OOS yok (eski `BacktestEngine.walk_forward` rolling-window istatistik, parametre-optimizasyonu değil, test-only); (b) segmentasyon yalnız yön + MTF bağlamı; (c) `BacktestEngine` üretimde write-only ledger (statistiği hiçbir ürüne çıkmıyor); (d) backtest analiz snapshot'larını bellekteki `TradeJournal` nesnesine ekler, ancak `_disable_backtest_live_features()` `SIGNAL_TRACKING_ENABLED=False` yaptığı için `AtlasEngine` journal'ı `db_path=None` ile kurar; mevcut kod akışında canlı journal DB'sine yazma bulgusu doğrulanmadı; (e) üretim CLI'si `partial_exits=False` yolunu hiç kullanmıyor (non-partial simülatör dormant); (f) funding maliyeti modellenmiyor (kasıtlı, belgelenmiş).
- **Bulgu (araç uyumu):** `backtest/` adında neredeyse boş bir paket `backtest.py`'yi **gölgeliyor** (`import backtest` → boş paket); kafa karıştırıcı, silinmeli/ad değişmeli (ayrı PR).

---

## 2. KARAR MİMARİSİ DENETİMİ

### 2.1 Çift sayım envanteri (aynı kanıt birden fazla kez sayılıyor)
| Kanıt | Sayım yerleri |
|---|---|
| Sweep | confluence (≤+15), decision presence-penalty + SHORT hard gate, signal confidence, setup_quality, F2, setup_reasoning (+ MTF yön türetimi) → **≥6** |
| MTF/HTF uyumu | confluence, decision (bonus/−40), setup_quality blocker, trade_quality_engine, F1, entry_confirmation → **6** |
| Net RR eşiği | `MIN_SETUP_NET_RR=2.0` (aday), `execution_rr≥2.0` (decision risk), legacy `≥3.0` (ölü quality), F5 `≥2.0`+TP1≥0.8, TQE final `≥3.0` gross → **5 yer / 3 farklı eşik** |
| Giriş mesafesi | aday uygunluk, main geometry guard (MARKET), F3, TQE, EntryEngine etiketi → **4–5** |
| Stale-TP1 | engine, TQE, setup_reasoning, atlas_main → **4 kopya** |
| Killzone/session | confluence (+2 sabit) + setup_quality (ağırlık 0.04) |
| Motor çelişkisi | confluence, decision, signal, setup_quality `_external`, F6, TQE, setup_reasoning → **6** |
| Confluence içinde | Stack Confluence (+18) directional_sweep ve aktif SMT'yi yeniden şart koşuyor — aynı mum zaten +15/+12 almış |
| Sinyal konfidence | confluence base + modül deltaları + setup_quality alt skorları (aynı modüller 2–3 kez) |

Skor ölü eşiğin arkasında olduğundan çift sayımın ana zararı: (1) konfidence şişmesi (TUI sıralamasında 0.25 ağırlıkla), (2) `S+`/ELITE etiket güvenilmezliği, (3) bakım drifti — tek kanıt değişince 6 yeri senkron tutmak.

### 2.2 Bir motorun diğerini ezmesi / çelişen kapılar
1. **F1 ölü unblock:** SetupReasoningEngine ters-trend onaylı sweep-reversal'ı kasıtlı kabul ediyor → TradeQualityEngine engelini kaldırıyor → F1 yine de critical blocker koyuyor (unblock koşulu 4H-karşı durumda ulaşılamaz). Sonuç: üç motor onaylar, dördüncüsü sessizce öldürür.
2. **setup_quality veto ölü:** `trade_allowed=False` blocker'ları yalnız confidence'ı düşürüyor; hiçbir kurulumu durdurmuyor.
3. **Trade-quality veto SKIP→WAIT yeniden etiketleniyor:** decision blocker zinciri (risk/short-sweep/"Trade quality:" prefix'li) atlanıyor; neden yalnız `trade_quality.reason`'da kalıyor; LIMIT "BEKLE" kartında **hiç basılmıyor**.
4. **3.0 vs 2.0 RR politikası:** DecisionEngine net-RR=2.0 merkezi eşik kabul ederken TQE gross 3.0'ı yeniden dayatıyor (B sessizce A'yı iptal).
5. **MTF çelişki tavrı motora göre değişiyor:** setup_quality=blocker-skor, decision=−40 (kasıtlı yumuşak), TQE=hard blocker, F1=hard blocker, confluence=+10/−0. Tek tutarlılık yok.
6. **Correlation:** bir yerde hard block (ölü `_apply_external_risk_filters`), diğerlerinde uyarı — tesadüfen tutarlı (bloklayan kopya ölü).

### 2.3 LONG/SHORT asimetrisi
- **Ana asimetri:** `decision_engine.py:116-130` — HER SHORT için `is_sweep ∧ buy_side ∧ post.confirmed ∧ direction==BEARISH` zorunlu; LONG için karşılık yok (yalnız −4 soft). Tüm uygulanabilir LONG'ların ayna verisi olan H4-bear trend-devam SHORT'ları yayımlanamaz.
- SMT bullish/bearish `_aligned` çağrısı asimetrik (bullish `timeframe` parametresini kaçırıyor → 1h tolerans) — yönler arası FP/FN dengesizliği (`smt_engine.py:188` vs `:134`).
- Bearish OB index kusuru yalnız SHORT breaker FP üretir (yukarıda).
- Diğer risk/geometri yolları simetrik (imzalı, abs'siz — PR #110 P0-3 sonrası testli).

### 2.4 Sinyal kalitesinin yalnızca puanla mı belirlendiği / kalite gerçekten neyle belirleniyor
- Skor eşiği ölü → kalite fiilen şu zincirle belirleniyor: MTF geçerli + hizalı (F1) + giriş geçerli + risk hesaplanabilir (`execution_rr≥2.0`) + ≥1 yapısal sentetik-olmayan TP (net≥2.0 ve final gross≥3.0 + TP1≥0.8 + kümeler arası ayrım) + MARKET ise sweep-in-POI (yaş≤2) + haber/cooldown temiz. **Yani "kalite" çoğunlukla geometri/maliyet geçerliliği; kanıt zenginliği skor ama ölü.**
- TUI "işlem ver" sıralaması `quality*0.55 + confidence*0.25 + min(rr,5)*4` — setup_quality (ölü veto'lu) + şişkin confidence + RR → "en iyi" seçimin setup kalitesini yansıttığı kanıtlanamaz.

### 2.5 WAIT kararlarının gerçek nedenleri
- WAIT kodları kayıtlı: `entry_invalid`, `entry_not_confirmed`, `direction_unresolved`, `setup_quality_blocked`, `trade_quality_blocked`, `NO_MAIN_ENGINE_SETUP`, `ENTRY_TOO_FAR`, `NET_RR_BELOW_MINIMUM`, `TP1_ALREADY_REACHED*`, geometry kodları, runtime veri kapıları (`no_closed_15m_candle`, `stale_15m_market_data`).
- **Sorun:** (a) aday-üretim WAIT kodları (`NET_RR_BELOW_MINIMUM` vb.) kartta gösterilmiyor (`entry_type_reason` boş) → kullanıcıya jenerik "giriş yok"; (b) SKIP blocker'ları WAIT yoluyla bastırılıyor (§2.2.3); (c) LIMIT bekleme kartında blocker'lar hiç basılmıyor; (d) "işlem ver" tarama teşhisi yalnız sayaç, sembol-başına neden yok.

### 2.6 Tek karar otoritesi sızıntıları
1. TUI `pending_limit` aday filtresi `decision_action`'ı kontrol etmiyor (SKIP'li LIMIT sıralamaya girer).
2. TUI tek-sembol LIMIT kartı aynı şekilde (`atlas_tui.py:298-300`).
3. `engine.py:520-521` `backtest.record()` yalnız `signal∈{LONG,SHORT}` şartı — WAIT/SKIP kurulumlar backtest veri setine karışıyor (pending olarak).
4. Motor→UI doğrudan sızıntı yok (iyi); Telegram/execution üründe kapalı (kısıtlara uygun).

### 2.7 Karar mimarisinin en önemli 10 problemi (liste C)
1. Skor/kalite eşiğinin ölü olması — kalite = geometri geçerliliği, kanıt puanı karar vermiyor.
2. SHORT-only sweep hard gate (LONG karşılığı yok) — yön asimetrisi + SHORT FN.
3. F1 ölü unblock — ters-trend onaylı reversal'ların üç motordan geçip dördüncüde ölmesi.
4. Gross 3.0 RR eşiğinin net-RR 2.0 politikasıyla çelişmesi.
5. Trade-quality veto'nun SKIP→WAIT yeniden etiketlenmesi + blocker zincirinin atlanması.
6. Aynı kanıtın 5–6 yerde sayılması + 4 kopyalı stale-TP1 (bakım/çelişki üreticisi).
7. Sabit +10 confirmation ve sabit +2 killzone/session — ayırt edici olmayan puan şişmesi.
8. setup_quality veto'sunun etkisiz kalması (kalite motoru engelleyemiyor).
9. TUI pending-LIMIT sıralamasının `decision_action`'ı bypass etmesi.
10. Enstitutional/sinyal konfidence bozuk bileşenler (CVD +12 çift yön, reclaim=sabit-true, confirmation=always-true) ile şişen konfidence'ın sıralamaya girmesi.

---

## 3. KÂRLILIK DENETİMİ — ÖLÇÜM SONUÇLARI

Kurgu: ürünün kendi backtest hattı (değiştirilmeden) + işlem defteri zenginleştirme (yalnız ölçüm betiğinde; repoya kod yazılmadı). Ücret modeli üretimle aynı (maker 0.02% / taker 0.055% / spread 0.02% / slippage 0.03%, tek uygulama). `limit_expiry_bars=8`, `step=1`, katı mod (EXECUTE kapısı).

### 3.1 ETH/USDT:USDT — 12 gün (940 analiz çağrısı, 19 işlem)

| Metrik | Değer |
|---|---|
| Analiz → sinyal | 940 çağrı → 27 aday → **19 işlem** (WAIT 613, SKIP 134, EXECUTE 193 karar-instansi) |
| Winrate | **15.8%** |
| Profit Factor (net) | **0.445** |
| Expectancy | **−1.38R net** (brüt **+0.38R**) |
| Ortalama kazanç / kayıp | +7.01R / **−2.96R** |
| Max Drawdown | −26.27R |
| Toplam maliyet | 33.5R (işlem başına 1.76R!) |
| Stop-ilk oran | 16/19 (%84) |
| TP1 sonrası stop | 2/18 (%11.1) |
| Limit dolum | ~%66 kimlik-bazlı (19 dolu / 5 dolmamış / 5 süre-biti; dolum gecikmesi 0–6 bar) |
| Yön kırılımı | **19 LONG / 0 SHORT** (134 ham SHORT sinyali → 0 işlem) |
| Giriş tipi | 18 LIMIT, 1 MARKET_FALLBACK — **0 gerçek MARKET** |

Kırılımlar:

| Segment | n | Winrate | PF | Expectancy (net R) | Not |
|---|---|---|---|---|---|
| Volatilite YÜKSEK (ATR%≥0.42) | 7 | 14.3% | 1.07 | **+0.10** | sağlıklı |
| Volatilite ORTA | 6 | 16.7% | 0.06 | −1.91 | |
| Volatilite DÜŞÜK (ATR%<0.20) | 6 | 16.7% | 0.38 | **−2.59** | maliyet 21.8R (işlem başına 3.6R) |
| POI: UNICORN | 3 | 33.3% | 2.26 | **+2.00** | |
| POI: IFVG | 11 | 9.1% | 0.30 | **−2.04** | en sık kullanılan POI en kötü |
| POI: BREAKER | 2 | 50% | 0.12 | −2.78 | MARKET_FALLBACK dahil |
| POI: OB/FVG/HTF_FVG | 3 | 0% | 0.00 | −1.14..−1.84 | |
| Çıkış: STOP | 16 | 0% | 0 | **−2.96** (brüt −1.00) | tüm kayıp sürtünmeden |
| Çıkış: TRAILING/TP2 | 3 | 100% | ≥10 | +5.14/+10.76 | |

**Mekanizma (ölçülerek doğrulandı):** 19 işlemin 13'ünde stop mesafesi ≤ fiyatın %0.125'i = bacak sürtünmesi. Stop ATR tabanları (`MIN_STOP_ATR_MULTIPLIER=0.25` → ETH 15m ATR%'si ~%0.1-0.15 iken ≈ %0.03-0.04 risk) **maliyet-farkındalıklı değil**: stop mesafesi sürtünmeden küçük kalınca her stop-out 1.15R–5.88R net kayıp üretiyor (brüt −1.0R). `stop_atr_buckets`: adayların **%87'si (628/722) <0.50 ATR** stop'la üretiliyor.

**Muhasebe asimetrisi (kabul ↔ gerçekleşme ↔ boyutlandırma):**
1. Kabul kapısı (`weighted_net_rr ≥ 2.0`) `estimate_plan_cost` (giriş bacağı + TP çıkışları) ile hesaplar — **stop çıkış bacağını düşmez**.
2. Gerçekleşen R (`net_rr`) tüm bacakları düşer → stop'lar −3.4R görünür.
3. Boyutlandırma `effective_risk_per_unit = risk + stop_cost` kullanır → para kaybı hedef riskin ~1 katına sabitlenir.

Sonuç: başlık R metrikleri para gerçekliğini olduğundan kötü gösterirken, kabul kapısı ters yönde iyimser. Para-normalliğe çevrilmiş expectancy **−0.42R** (PF 0.52) — hâlâ negatif ama başlıktan çok farklı. Karşı-olgusal (n küçük, kanıt değil): stop mesafesi ≥ sürtünme (%0.125) şartıyla n=9 → **+0.07R**; ≥ %0.25 şartıyla n=4 → −0.76R. (Bu bir filtre önerisi değildir; maliyet-farkındalıklı taban gerekliliğinin ölçümüdür.)

**Yön çöküşü:** 12 günde tek H4 bağlamı (BULLISH|w=NEUTRAL|d=BEARISH), `mtf_entry_source_counts` %100 `H4_STRUCTURE` — 15m-reversal yolu hiç ateşlemedi; 134 ham SHORT sinyalinin tümü elendi. LONG tarafı günlük BEARISH'e karşı alım yapıyor (yön çatışması F1'in geçmesine rağmen — `w=NEUTRAL` weekly ile F1 yalnız H4'e bakıyor).

### 3.2 BTC/USDT:USDT — 2×14 gün (bellek-güvenli parçalı koşu)

> İlk 28-gün tek koşu ~47 dk sonra sessizce sonlandı (ortam bellek baskısı; swap kullanımı 1.1GB). Ürün CLI'sının `--chunk-days` segmented yaklaşımıyla uyumlu biçimde iki 14-gün parçası (örtüşmesiz pencere: [−28g,−14g] ve [−14g,şimdi], her biri yeni süreç) koşuldu. Parça başına 1.343 analiz çağrısı.

| Metrik | BTC (28 gün birleşik) | ETH (12 gün) |
|---|---|---|
| İşlem sayısı | **16** (9+1→10 / 6) | **19** |
| Winrate | **6.2%** (1/16) | 15.8% |
| Profit Factor (net) | **0.016** | 0.445 |
| Expectancy | **−3.18R** net (brüt −0.85R) | −1.38R net (brüt +0.38R) |
| Max Drawdown | **−50.9R** | −26.3R |
| Toplam maliyet | 37.2R (**2.33R/işlem**) | 33.5R (1.76R/işlem) |
| Çıkış dağılımı | 15 STOP + 1 TRAILING_STOP — **0 TP dolumu** | 16 STOP / 2 TRAILING / 1 TP2 |
| Yön | **15 LONG / 1 SHORT** (ham: 112 LONG / 1.262 SHORT) | 19 LONG / 0 SHORT |
| Stop mesafesi | 13/16 işlem sürtünme altı (%0.04–0.18 risk) | 13/19 sürtünme altı |
| Planlanan TP1 (gross R) | 2.7–25.4R (medyan ~9R) | 2.9–13.5R |
| Para-normalliğe çevrilmiş expectancy | **−0.95R** (PF 0.03) | −0.42R (PF 0.52) |
| Cevap veren rejim kaynağı | %100 H4_STRUCTURE (1.343/1.343) | %100 H4_STRUCTURE |
| Stop-ATR dağılımı (adaylar) | %84 (1.233/1.461) <0.50 ATR | %87 (628/722) <0.50 ATR |

İki sembolde aynı mekanizma: **tüm negatif expectancy, sürtünmenin stop-risk birimine baskın gelmesinden kaynaklanıyor** (brüt −0.85R/−1.0R → net −3.2R/−1.4R). BTC'de tek kazanan işlem bir TRAILING_STOP (+0.81R net). Ham SHORT sinyallerinin ~%99.9'u karar katmanında SKIP (SHORT sweep gate); LONG sinyalleri kabul edilip dar-stop geometrisiyle işlemeye dönüşüyor.

Ayrıca part-1 penceresinde 16 kez "TP1 reached before LIMIT fill and no remaining structural target" bayat-limit koruması tetiklendi (koruma çalışıyor; dolum ekonomisi ölçülebilir).

### 3.3 Örneklem dürüstlüğü notu
ETH 12g + BTC 28g toplam **35 işlem, 4 kazanan** — **hiçbir segment için istatistiksel güven yeterli değil** (ürünün kendi performans kapısı 200 işlem istiyor). Bu ölçümler **mekanizma kanıtı**dır (negatif expectancy'nin kaynakları), kârlılık/yenilebilirlik kanıtı değildir. Rapor hiçbir yerde bu sayıları "kâr kanıtı" olarak sunmaz.

---

## 4. BACKTEST GÜVENİLİLİĞİ

### 4.1 Look-ahead / veri sızıntısı — GÜÇLÜ
- Karar yalnız kapanmış 15m mumunda verilir (`backtest_runner.py:438-441`); HTF `timing.closed_htf_candles` ortak tek kural (canlı+backtest); MARKET bir sonraki mum açılışından dolum; oluştan mumlar tüm TF'lerde atılır. Regresyon: `test_lookahead_timing.py`, `test_mtf_lookahead.py`.
- SMT peer serileri her pencerede yeniden hizalanır (`engine.py:1991-2009`); listing-aware geçmiş; kalıntı risk: çağıran oluşan 15m mumu verirse LTF kenarı korunmaz (backtest içi değil, test/dış çağrı riski).
- Swing ATR geleceğe sızması core'da düzeltildi (CORE_FOUNDATION_AUDIT).

### 4.2 Aynı setup tekrarı — GÜÇLÜ
- `_setup_identity` ile aynı POI'li kurulumlar dedupe (`backtest_runner.py:569-617`); örtüşen pozisyonlar bağımsız işlem sayılmıyor.

### 4.3 Emir dolum gerçekçiliği — GÜÇLÜ, bilinen sınırlar ile
- MARKET: sonraki mum açılışı; TP1'i geçmiş açılışta girişin iptali (chasing yok).
- LIMIT: touch=fill; açılış boşluk geçerse fill=open; intrabar fill mumu TP simülasyonundan çıkarılır (`backtest_runner.py:906-909`); stop aynı mumdaysa stop'ta zarar (muhafazakâr). Bekleme süresi `limit_expiry_bars` (varsayılan 8 bar=2h). Kuyruk pozisyonu modellenmiyor (belgelenmiş).
- Stop gap: ilk stop açılıştan, taşınan stop journal-parite tam fiyattan (`stop_gap_r` kayıtlı).
- Bilinen sınır: OHLC replayı gerçek orderbook spread/market impact'ı kanıtlayamaz (ENGINE_INTEGRATION_AUDIT zaten işaretliyor); funding yok.

### 4.4 Mum içi fiyat sıralaması — MUHAFAZAKÂR (P0-2 sonrası)
- Stop-first politikası; parça çıkışta sıralı TP + TP1→BE, TP2→TP1 + taşınan stop aynı mum içindeyse kalan fraksiyon tam stop fiyatından kapatılır; journal ile birebir parite testli (`test_backtest_journal_be_parity.py`).

### 4.5 Ücret hesaplaması — TUTARLI, tek kaynak
- `execution_costs.py` hem backtest hem RiskEngine hem journal-signal-outcome; işlem başına bir kez (`realized_trade_cost`); çift sayım regression-testli.
- Sapma: journal **tracked/manual** `pnl_rr` ücretler BRÜT (`trade_journal.py:782-800`, `:1542-1554`) → üç farklı maliyet görünümü; legacy `BacktestEngine` sabit `round_trip` proxy (yalnız test).

### 4.6 Canlı/backtest davranış farklılıkları
- Ortak: karar zinciri, timing, maliyet modeli, BE/TP kuralları.
- Farklı: (a) canlıda orderbook/correlation/economic-news/cooldown etkin, backtestte kapatılıyor (özellik, bilinçli); (b) canlıda learning durumu etki edebilir, backtestte kapalı; (c) backtest analiz snapshot'ları bellekte tutulur; tracking kapatıldığı ve `TradeJournal(db_path=None)` kurulduğu için canlı journal DB'sine yazılmaz; (d) canlı MARKET fill gerçek spread/slippage, backtest proxy.

### 4.7 Walk-forward / OOS
- PR #111 ile `--walk-forward` eklendi: `--chunk-days` ile tarihsel parçalar ayrılır; daha eski IS ve yaklaşık en yeni %30 OOS (tam parça sınırına yuvarlanır) olarak raporlanır. Parametreler iki dönemde de sabittir; bu komut otomatik optimizasyon yapmaz, dokunulmamış son dönemde performansı ölçer. En az iki parça zorunludur.

### 4.8 Ölçüm sırasında saptanan çalıştırma güvenilirliği sorunları (yeni bulgular)
1. **Uzun tek-koşu backtest bellek baskısı:** 28-gün tek koşu ~47 dk sonra hata mesajı olmadan sonlandı (ortamda swap kullanımı, ~7.5GB RAM). Ürün CLI'sında `--chunk-days` segmented modu mevcut; **varsayılan davranış haline getirilmeli ve Android/UserLAnd için belgelenmeli.** Rapor çıktısı stdout-only; JSON/CSV kancası yok.
2. **Cache tazeliği doğrulanmıyor:** `_load_cached_candles` yalnız [since, now) penceresini filtreler, kuyruk tazeliğini kontrol etmez; `_effective_now_ms` son 15m mumunu "now" kabul ettiği için bayat cache **sessizce değerlendirme penceresini kısaltır** ve kullanıcının istediği gün sayısı sağlanmaz. Son-mum-tazeliği uyarısı/abort eklenmeli.
3. **`backtest/` boş paketi `backtest.py`'yi gölgeliyor:** `import backtest` pakete çözülür (yalnız docstring); araç/çevre karışıklığına yol açar (bu denetimde driver'ı çökertti). Paket silinmeli veya ad değişmeli.
4. **746MB journal DB canlı ortamda taşınıyor** (§1.17) — backtest koşuları journal'a yazmasa da kalıntı şişkinlik disk/I/O üzerinde etkili.

---

## 5. YENİ MİMARİ ÖNERİSİ (mevcut kodun yeniden yazımı değil, katman sözleşmeleri)

İlke: 26.2k satır çoğunlukla çalışıyor; değişim **soyutlama sınırı + sözleşme** ile, küçük PR'larla. Katmanlar mevcut motorların gruplandırılmasıdır; tek yeni bileşen "EventLedger" (kanıt kimliği) ve "DecisionGateList" (sabit kapı listesi) dir.

```
L1 Veri Katmanı (data_engine, timing, market-data validation)
   Sözleşme: {candles[tf]: ClosedCandle[], tick_size, now_ms, freshness}
   Sorumluluk: yalnız kapanmış mum, tek doğrulama kapısı, stale→WAIT.

L2 Rejim/Volatilite (market_regime_engine + market_phase_engine birleşimi)
   Girdi: L1. Çıktı: {trend_state: TREND_UP/DOWN/RANGE/UNKNOWN, vol_state, atr_pct, ref_time}
   Sorumluluk: TEK rejim sınıflandırıcısı; trend_engine "derived" kalır; volatilite stop/boyut girdisi.

L3 Yapı+Likidite (market_structure, BOS/CHoCH, sweep, OB/FVG/OTE, unicorn, CISD)
   Girdi: L1(+L2). Çıktı: Event[] {event_id, type, time, level, direction, confirmed, consumed}
   Sorumluluk: olay üretimi; PUAN YOK. Kanıt bir kez üretilir, event_id ile taşınır.

L4 Setup Üretimi (setup_reasoning_engine çekirdeği)
   Girdi: L3 Event[] + L2. Çıktı: Candidate[] {poi_id, direction, entry_zone, invalidation, evidence_ids[]}
   Sorumluluk: aday üretimi; kanıt yalnız event_id referansı (çift sayım yapısal olarak imkânsız).

L5 Entry Optimizasyonu (entry_optimizer + entry_engine seçim mantığı)
   Girdi: Candidate + L2 + güncel fiyat/spread. Çıktı: EntryPlan {type MARKET/LIMIT, price, distance_atr, expiry_bars}
   Sorumluluk: dolum gerçekçiliği (mesafe, yaş, geçerlilik süresi); kalite YOK.

L6 Risk/TP-SL Geometrisi (risk_engine + rr_engine + dynamic_tp + execution_costs)
   Girdi: EntryPlan. Çıktı: RiskPlan {stop, tps[], weights, rr_by_tp, weighted_net_rr, size, cost_model}
   Sorumluluk: maliyet bir kez; finalize sonrası reconcile (P0-1 modeli referans).

L7 TEK FINAL KARAR (decision_engine — sabit kapı listesi)
   Girdi: Candidate+EntryPlan+RiskPlan+Event özetleri+L2.
   Çıktı: Decision {action EXECUTE/WAIT/SKIP, direction, reasons[] (kod+kanıt), score=TEŞHİS}
   Kapılar (sabit sıra, her biri neden kodu yazar): yön → veri tazeliği → geometri → maliyet-net-RR →
   rejim uygunluğu → kanıt teyidi (min event sayımı) → operasyonel (haber/cooldown).
   Skor yalnız raporlama; EXECUTE = tüm kapılardan geçiş.

L8 İşlem Takibi (trade_journal — lean payload)
   Girdi: Decision kaydı + mum replay. Çıktı: outcome {r, tp_hits, exit_reason, mfe/mae, cause_code}
   Sorumluluk: lean payload (id referansları, tam analiz DEĞİL); outcome simülatörü tek modül
   (backtest_runner P0-2 mantığı buradan import edilir — çift bakım biter).

L9 Kontrollü Öğrenme (learning_engine + doğrulama hattı)
   Girdi: outcome + CauseClassifier (yeni, küçük). Çıktı: bucket metrikleri + değişiklik önerileri
   Sorumluluk: min-örneklem; öneri önce OOS backtest; onay + snapshot/rollback; canlı etki yalnız
   doğrulanmış param değişikliğiyle (skor delta'ya canlı bağlantı kapatılır).
```

---

## 6. ÖĞRENME SİSTEMİ DEĞERLENDİRMESİ

- **Mevcut durum:** depo boş (records_fed=0) — öğrenme fiilen uyuyor; geçmiş besleme %100 teorik sinyal-sonucu (gerçek manuel/tracked fill: 0). Canlı etki yolu var ama sınırlı (rampalı ±6/±10, min 20 örnek, int-trunc) ve testli.
- **Güçlü yönler:** min-örneklem rampası; Bayesian+Wilson; yön/rejim/TF izolasyonu; atomik yazım; bozulma toleransı; look-ahead `as_of_ms` filtresi testli.
- **PR #111 ile eklenen korumalar:** `rebuild_from_records` kronolojik kayıtları %70 eğitim / %30 holdout olarak böler; bucket etkisi yalnız OOS örneklemi yeterli, ortalama R pozitif, PF>1 ve Wilson alt sınırı eşiği geçerse kullanılabilir. Öğrenme dosyası atomik kaydedilir, önceki sürüm `.bak` olarak tutulur ve `rollback_last_save()` ile geri alınabilir. Journal öğrenme kayıtlarına `STOP_OUT`, `PARTIAL_PROFIT_GIVEBACK`, `TRAILING_STOP`, `TARGET_EXIT`, `TIME_EXIT` gibi cause code'lar eklenir; cause dağılımı öğrenme meta raporunda tutulur.
- **Açık eksikler:** OOS kapısı küçük örneklemde öğrenmeyi bilinçli olarak nötr bırakır; parametre otomatik optimizasyonu/rollback kararı yoktur. Event-ID tabanlı motor attribution henüz yoktur; teorik signal outcome gerçek borsa fill'i değildir.

---

## 7. TESLİM RAPORU A–H

### A. Güçlü/zayıf yönler
**Güçlü:** look-ahead disiplinli veri katmanı (testli tek timing kuralı); maliyet modeli tek kaynak ve çift-sayım-testli; journal↔backtest simülasyon paritesi (P0-2); yapısal stop + sentetik-TP reddi; boyut küçültücü containment faktörleri; operasyonel güvenlik kapıları (haber/cooldown, execution kilidi `enabled()=False`); 836-testlik regresyon duvarı; önceki denetimlerin belgelendirme disiplini.
**Zayıf:** fiilî "geometri geçen geçer" karar kuralı; kanıt çift sayımı ve 4–6 kopyalı mantık; yön asimetrisi; ölçüm/segmentasyon yokluğu; OOS yok; DB şişmesi; ölü motor/parametre kalabalığı; konfidence bütünlüğü bozuk bileşenler.

### B. Kârlılığı düşüren en önemli 10 neden (ölçümlerle destekli — §3)
1. **Maliyet-farkındalıklı olmayan stop tabanı** — `MIN_STOP_ATR_MULTIPLIER=0.25` ATR% küçükken sürtünmenin (~%0.125) altına düşüyor; ETH'de 13/19 işlemde stop ≤ sürtünme → her stop-out 1.2–5.9R net (ölçüm: §3.1). Para-normal expectancy −1.38R'dan −0.42R'ya düzelir ama hâlâ negatif; kök neden maliyet/stop uyumsuzluğu.
2. **Kabul-gerçekleşme muhasebe asimetrisi** — kabul `weighted_net_rr` stop bacağını düşmezken gerçekleşen R düşüyor; aynı sürtünme birimini üç farklı katman üç farklı şekilde uyguluyor (ölçüm: §3.1).
3. **Yön asimetrisi** — SHORT-only sweep gate + 15m-reversal yolunun pratikte ateşlememesi: 134 ham SHORT → 0 işlem (ölçüm: §3.1); yön dengesi bozuk, kısa yöndeki fırsat seti boş.
4. **TP merdiveni geometri-denaturasyonu** — 0.25–0.5 ATR stop'a karşı 6–13R TP merdivenleri → TP1 vurulma olasılığı düşük, TP1-sonrası-stop %11.1 (ölçüm: §3.1); hedef yapısal ama stop mesafesine göre ölçeklenmiyor.
5. **Gross 3.0 ↔ net 2.0 RR çelişkisi** — geçerli orta-RR kurulumların eelenmesi (kod-düzey kanıt §1.14; ölçüm etkisi ayrı ölçülmeli).
6. **F1 ölü unblock** — onaylı ters-trend dönüşlerinin kaybı (kod-düzey; §2.2).
7. **MARKET penceresinin darlığı** — sweep+yaş≤2+POI-içi şartı 12 günde 0 gerçek MARKET üretti (ölçüm: §3.1); dolum ekonomisi LIMIT'e ve MARKET_FALLBACK'e kalıyor.
8. **Konfidence şişmesi** — sabit confirmation ve killzone/session bonusları hâlâ kalibrasyon gerektiriyor. Institutional CVD +12 puanı iki yönde de yalnız akış varlığını ölçüyor; yön ise ayrı LONG/SHORT oy sayımıyla belirleniyor, bu tek başına yön asimetrisi değil. Stop-hunt reclaim koşulu PR #111'de gerçek swept-level reclaim olarak düzeltildi.
9. **Kısmi-dolum FVG "fresh" + legacy no-pool sweep FP** — zayıf POI girişleri (kod-düzey §1.11/§1.10).
10. **Ölçüm/kalibrasyon döngüsünün kapalı olması** — segmentasyon, OOS, öğrenme (depo boş, records=0) yok; parametre kararları kanıtsız (§4.7, §6).

### C. Karar mimarisinin en önemli 10 problemi → bkz. §2.7

### D. Kullanılmayan / tekrarlanan / etkisiz motorlar
- **Ölü kod:** `_apply_external_risk_filters`, F1 unblock dalı, decision eşik+override+quality_blockers, `_extract_confidence`, `modules/_discover_modules`, `setup_consensus` (her zaman {}), elimination sayaçları, EntryEngine fallback'leri, Unicorn `_trade_levels`, `premium_zone/discount_zone` çıktıları, `market_phase._volatility`, institutional ölü alt-çıktılar, `dynamic_tp._select_target_for_rr/_nudge_level`, PositionManager (dormant + model çelişkisi), TradeManager, `LearningEngine.record_closed_trade/adjustments_for/bucket_key`, `LEARNING_MIN_SIGNAL_FALLBACK_SAMPLES`, BacktestEngine `monte_carlo/walk_forward/trade_analytics/ingest_journal` (test-only), StatisticsEngine `record/record_result/ingest_journal`, non-partial simülatör, `backtest/` boş paketi (gölgeleme), scanner `reasons/grade/stars` alanları (her zaman boş), Config `QUALITY_HTF_STRONG_CONFLICT_BLOCK/QUALITY_REQUIRE_SWEEP`.
- **Tekrarlanan mantık:** aday-rank tuple (2 kopya), stale-TP1 (4 kopya), RR eşikleri (5 yer/3 eşik), giriş mesafe (4–5 yer), MTF uyum (6 yer), sweep puanlama (6 yer), üç rejim sınıflandırıcısı (regime/phase/institutional-internal).
- **Etkisiz motor:** SetupQualityEngine veto'su (yalnız confidence), EntryConfirmationEngine (always-true), institutional puan bileşenleri (bozuk), DecisionEngine skor katmanı (ölü).

### E. Yeni mimari şeması → bkz. §5
### F. Önceliklendirilmiş geliştirme yol haritası → Bölüm 8
### G. Her değişiklik için fayda/risk/doğrulama → Bölüm 8 tablosu
### H. PR bölünmesi → Bölüm 8

---

## 8. ÖNCELİKLENDİRİLMİŞ GELİŞTİRME YOL HARİTASI

| # | Değişiklik | Katman | Beklenen fayda | Risk | Doğrulama | PR |
|---|---|---|---|---|---|---|
| P0-0 | **Maliyet-farkındalıklı stop tabanı + tek maliyet birimi** | L6/L7 | Ekonomik olarak aşırı dar stopları reddeder; stop maliyeti sizing'e dahil | İşlem sayısı düşer; 2x taban OOS ile kalibre edilmeli | Aynı pencere öncesi/sonrası + OOS | PR #111 uygulandı |
| P0-1 | Gross 3.0 ↔ net 2.0 eşik birleşimi (tek eşik: net RR) | L6/L7 | Tek net-RR politikası | Zayıf kurulum sızıntısı | IS/OOS + blocker dağılımı | PR #111 uygulandı |
| P0-2 | SHORT sweep gate'i simetrikleştirme | L7 | Yön asimetrisi azaltılır; kalite kanıtı ortak kapıda | Zayıf SHORT akışı artışı | Yön kırılımı + PF/expectancy | PR #111 uygulandı |
| P0-3 | F1 reversal yolu ve sweep→CHoCH nedenselliği | L4/L7 | Onaylı ters-trend dönüşü doğru tanınır; eski CHoCH sızıntısı engellenir | Ters-trend FP artışı | Reversal kategorisi OOS ölçümü | PR #111 uygulandı |
| P0-4 | TUI pending_limit `decision_action` kontrolü | UI | Karar otoritesi sızıntısı kapanır | Yok | Test | PR #111 uygulandı |
| P0-5 | Yeni journal kayıtlarında lean payload + backup-first compaction | L8 | Yeni DB büyümesi azaltılır; mevcut DB güvenli yedek sonrası küçültülebilir | Eski DB kompaksiyonu kullanıcı onayı gerektirir | DB boyutu + outcome bütünlüğü | PR #111 uygulandı; mevcut DB'ye uygulanmadı |
| P1-1 | Yapısal event-id tabanlı kanıt dedupe (kısmi) | L3/L7 | Aynı BOS/CHoCH/sweep olayının yinelenen yapısal kanıtı bastırılır | Tüm motorlara yayılınca yeniden kalibrasyon gerekir | Kanıt→işlem eşlemesi + OOS | PR #111 kısmi; global motor attribution açık |
| P1-2 | Trade-quality veto SKIP olarak kalır (yeniden etiketleme kalkar) + blocker'lar WAIT kartına basılır | L7/UI | Şeffaf WAIT nedenleri | Davranış değişikliği | WAIT neden dağılımı | küçük PR |
| P1-3 | SMT timeframe + bearish OB index + stop-hunt reclaim düzeltmeleri | L3 | Yön/zaman hizalaması ve reclaim doğruluğu | Düşük | Birim testler | PR #111 uygulandı |
| P1-4 | Backtest LIMIT süre-bazlı expiry | L5 | Bayat tarihsel emirlerin iptali | Dolum oranı düşebilir | Runner `limit_expiry_bars` sayacı | Mevcut kodda var; CLI varsayılanı 8 bar |
| P1-5 | Segmentasyon (entry type, phase/regime, volatility, POI, TP davranışı) | L8 | Ölçülebilir kalibrasyon temeli | Yanlış alan eşlemesi raporu bozabilir | Rapor diff | PR #111 uygulandı; regime alanları şemaya göre düzeltildi |
| P2-1 | Walk-forward/OOS komutu (IS/OOS, param-frozen) + güvenli checkpoint resume | L8/L9 | Zaman çıpası ve config/kod fingerprint ile aynı pencere tekrar edilir | Hesap maliyeti | OOS raporu | PR #111 uygulandı; henüz çalıştırılmadı |
| P2-2 | Öğrenme: OOS kapısı + rollback snapshot + cause taxonomy | L9 | Overfit koruması; neden-taksonomisi | Küçük örneklemde öğrenme nötr kalır | OOS A/B | PR #111 uygulandı |
| P2-3 | Ölü kod temizliği (§D listesi) + yanıltıcı "High probability setup" etiketi kaldırma | genel | Bakım yükü düşer | regresyon | Test süiti + import grafı | `backtest/__init__.py` gölgelemesi PR #111'de kaldırıldı; geniş temizlik açık |
| P2-4 | Tek rejim sınıflandırıcısı birleşimi (regime+phase) | L2 | Çelişki biter | Kalibrasyon | Rejim uyum ölçümü | ayrı |

Her değişiklik için: önce ölçüm (IS), sonra PR, sonra aynı ölçümün OOS doğrulaması; ölçüm şablonu §3.


---

## 9. PR #111 UYGULAMA DURUMU

Bu bölüm aynı PR dalındaki kod değişikliklerini izler. Aşağıdaki maddeler kodda uygulanmıştır; testler kullanıcı talimatı doğrultusunda çalıştırılmamıştır. Kârlılık etkisi backtest/OOS ölçümü yapılmadan doğrulanmış sayılmaz.

| Bulgu | Uygulama durumu |
|---|---|
| SHORT yönünde tek taraflı sweep zorunluluğu | DecisionEngine'den kaldırıldı; iki yönün kalite kanıtı ortak TradeQuality kapısına bırakıldı. |
| Bearish Order Block indeks hatası | Aranan opposing candle indeksi kullanılıyor; break indeksi de payload'a eklendi. |
| TradeQuality veto'sunun WAIT'e çevrilmesi | LONG/SHORT yönü korunuyor; nihai veto ve blocker DecisionEngine'e taşınıyor. |
| TUI LIMIT adaylarında SKIP sızıntısı | Her iki TUI aday yolunda da yalnız EXECUTE / EXECUTE_WITH_CAUTION kabul ediliyor. |
| SMT bullish pivot zaman hizalaması | _aligned çağrısına gerçek timeframe geçiriliyor. |
| Stop-hunt reclaim kanıtı | Önceki kapanışın değişmesi yerine süpürülen seviyenin kapanışla geri alınması doğrulanıyor. |
| Brüt RR ile net RR'nin çift veto üretmesi | TradeQualityEngine brüt final-target RR'yi veto olarak kullanmıyor; maliyet sonrası weighted net RR nihai DecisionEngine kapısında kontrol ediliyor. |
| Aday net-RR maliyet ağırlıkları | SetupReasoningEngine, RiskEngine ile aynı SIGNAL_OUTCOME_PARTIAL_WEIGHTS ayarını kullanıyor. |
| Backtest journal izolasyonu bulgusu | Kod tekrar kontrol edildi: backtest tracking'i kapatıyor ve journal'ı db_path=None ile kuruyor; canlı DB'ye yazma iddiası bu akış için kaldırıldı. |

**Açık kalan işler:** event ID üretmeyen motorlara kimlik kazandırıp tam kapsamlı attribution yapmak; WAIT/SKIP blocker'larını TUI'de açıklamak; gerçek fill/fee verisi olmayan manuel kayıtlar için net-R parity kurmamak; geniş dead-code temizliği ve rejim motorlarının birleştirilmesi. LIMIT expiry backtest runner'da zaten bulunuyor; walk-forward ve öğrenme OOS kapıları eklendi ancak henüz çalıştırılmadı.


---

## 10. PR #111 — KALAN UYGULAMA DURUMU (2026-11-13)

### Uygulanan
- Maliyet farkındalıklı stop tabanı: yapısal stop, tahmini round-trip friction'ın varsayılan 2 katından dar ise reddedilir; stop yapısal seviyeden otomatik uzaklaştırılmaz. `ATLAS_MIN_STOP_COST_MULTIPLIER` ile ayarlanır.
- Net RR tek kaynağa bağlandı: setup adayı, kalite filtresi, RiskEngine ve DecisionEngine `MINIMUM_NET_RR` kullanır; `MIN_SETUP_NET_RR` ve `QUALITY_MIN_NET_RR` geriye uyumluluk alias'ıdır. Brüt final-target RR ikinci veto değildir.
- F1 reversal yolu düzeltildi: gerçek sweep + reclaim + kapanmış 15m CHoCH, 4H yönüne karşı da `CONFIRMED_15M_REVERSAL` üretebilir. Artık genel yapı listesindeki eski/alakasız CHoCH yerine sweep motorunun nedensel `confirmation_index > sweep_index` kaydı esas alınır; F1 ayrıca MTF entry yönü, setup yönü ve sweep tarafı eşleşmesini ister.
- Yapısal BOS/CHoCH, sweep, SMT, FVG/IFVG, OB, orderbook snapshot ve CVD olaylarına zaman damgalı `event_id` eklendi. AtlasMainEngine motor çıktılarındaki açık event ID'lerini toplar ve duplicate/cross-motor tekrarlarını raporlar; SetupReasoning aynı event ID'li tekrar eden uzman kanıtını bir kez sayar. Kimlik üretmeyen motorların kanıtları henüz global dedupe edilmez.
- Aynı mumda hem buy-side hem sell-side legacy wick sweep oluşursa olay `ambiguous_sweep` sayılır; rastgele tek yön atanmaz. Likidite havuzu bulunmayan iki-mum wick rejection artık gerçek sweep olarak puanlanmaz; ayrı `legacy_wick_rejection` tanısıdır. Aynı yöne gerçek sweep olup henüz post-sweep onayı yoksa kanıt yanlışlıkla karşı-yön olarak yazılmaz.
- Backtest resume checkpoint'i kaynak revision, config, ücretler, TP ağırlıkları, step ve expiry ayarlarıyla fingerprint edilir; ayrıca ilk çalıştırmanın zaman çıpası korunur. Uyumsuz/eski checkpoint parçaları yeniden kullanılmaz.
- Backtest rejim segmentleri `market_regime.regime` ve `volatility_ratio` alanlarından doğru çıkarılır; market phase rapor çıktısına da eklendi.
- Journal yeni kayıtları sadeleştirildi: tam motor/candle payload'ları yerine outcome attribution için gerekli alanlar tutulur. Eski veritabanını fiziksel küçültmek için backup-first `compact_database()` eklendi; bu metot otomatik çalıştırılmaz.
- Learning: kronolojik 70/30 eğitim/OOS holdout, bucket bazlı OOS kabul kapısı, atomik önceki-sürüm yedeği ve `rollback_last_save()` eklendi.
- Cause taxonomy: kapanan işlemlere cause code atanır ve öğrenme meta raporunda sayılır.
- Backtest: `--walk-forward` eski IS / yeni OOS raporu verir; parametreler sabittir. Entry type, market phase/regime, volatility, POI ve TP davranışı segmentleri net R/PF ile raporlanır.
- `backtest/__init__.py` kaldırıldı; boş paket artık `backtest.py` CLI modülünü gölgelemiyor.
- LIMIT expiry backtest runner'da zaten mevcuttu; varsayılan 8 adet 15m bar.

### Bilinçli olarak açık bırakılanlar
- Global event attribution: ana motor artık BOS/CHoCH, sweep, SMT, FVG/IFVG, OB, orderbook snapshot ve CVD kimliklerini toplar; SetupReasoning kimliği aynı olan modül kanıtını tek sayar. Henüz kimlik üretmeyen diğer motorlar ve event ID taşımayan kanıt yolları için tam kapsamlı tekilleştirme açık iştir; motor teşhisindeki tekrar raporu tek başına karar skorunu değiştirmez.
- Rejim/phase motorlarının tek motora birleştirilmesi ve geniş dead-code temizliği: bağımlılık/import grafı ve davranış karşılaştırması olmadan dosya silmek karar mimarisini bozabilir. Bu turda güvenli, doğrulanabilir kapsamın dışındadır.
- Eski journal DB'sinde bir defalık fiziksel küçültme: `compact_database()` backup oluşturup VACUUM çalıştırır; kullanıcı veritabanında otomatik çalıştırılmadı.
- Manual/tracked ledger net fee parity ve gerçek fill tabanlı learning: kaynak kayıtlarda gerçek execution type/fee/fill verisi bulunmayan işlemler için maliyet uydurulmadı.
- WAIT/SKIP nedenlerinin TUI'de açıklamalı gösterimi henüz eklenmedi; işlem listesinde yalnızca yürütülebilir sinyaller gösterilmeye devam ediyor.

**Doğrulama:** Nedensel sweep/CHoCH, eski CHoCH çakışması, no-pool wick, açık MTF yön çelişkisi, SMT/FVG/IFVG/OB/orderbook/CVD event ID ve modüller arası aynı event'in tek sayılması için regresyon testleri eklendi; kullanıcı talimatı gereği testler çalıştırılmadı. Bu değişikliklerin performans etkisi henüz ölçülmedi; walk-forward/OOS komutu çalıştırılmadan kârlılık iddiası yapılamaz.
