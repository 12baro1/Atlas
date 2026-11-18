# Atlas uçtan uca denetimi

Referans sürüm `952dad8`. İnceleme önceliği kalıcı iş kaybı, zaman hizalaması ve setup yaşam döngüsüydü. Aşağıdaki tablonun ardından 326 izlenen Python dosyasının statik bağımlılık envanteri yer alır. Envanterdeki çağrılar import edilen isimlere AST üzerinden çözülebilen çağrılardır. MotorProxy, nesne enjeksiyonu, callback ve koşullu importların çalışma sırasını tek başına kanıtlamaz.

## Bulgular ve karşılaştırma

| Önem | Önce | Değişiklik ve kontrol |
|---|---|---|
| Kritik | Runtime başlangıcı, ilk N sıralamasından çıkan tek bir sembolde yeni dönem açabiliyordu. Günlük görev de koşulsuz dönem açıyordu. Worker yalnızca son dönemi tükettiği için eski pending satırlar erişilemez kalıyordu. | Günlük, manuel ve başlangıç çağrılarında aktif dönem kontrolü, dönem numarası ve ilk işler aynı SQLite yazma işleminde. İki bağımsız bağlantı üzerinde yarış ve yeniden başlatma testleri. |
| Kritik | SQLite açılışında her DatabaseError dosya silme yoluna gidiyordu. Geçiş DDL işlemleri autocommit modundaydı. | Açılış hatası kaynağı koruyarak çağırana iletilir. Şema geçişi transaction içinde. Lock hatasından sonra işlerin okunabilirliği test edildi. |
| Yüksek | Geç yanıt veren worker başka workera verilmiş lease'i kapatabiliyordu. | Worker sonucu sembol, generation ve monoton deneme sayısıyla eşleşmelidir. Süresi geçmiş lease regresyon testi. |
| Yüksek | İstanbul günü değişince havuzdaki adaylar ve doğrulanmış setuplar EXPIRED yapılıyordu. | Günlük SQLite yedeği canlı kayıtları koruyor. Yeniden açılan havuzda adayın varlığı doğrulandı. |
| Yüksek | Gate.io tarihsel mum isteği limit ile tarih aralığını karıştırdığı için HTTP 400 dönüyordu. | Aralık ve adet sorguları ayrıldı. Sonraki sayfanın başındaki önceki mum dışlanıyor. Canlı BTC sorgusunda beş zaman dilimi indirildi. |
| Yüksek | Haftalık kapanış bütün zaman dilimlerinin kapsam sonu olarak seçiliyordu. BTC denemesinde 395 adet 15m mum varken başlangıç 6,44 gün eksik raporlandı. | Üç replay yolu istek zamanını kullanıyor. Runner BTC/ETH ve sektör karşılaştırmalarını strateji callback'inden önce karar anına kırpıyor. |
| Yüksek | Boş funding snapshot sıfır, zaman damgası da yerel saat olabiliyordu. | Tarihsel ve son funding ortak normalizasyondan geçiyor. Eksik ve sonlu olmayan oranlar bilinmiyor, gerçek sıfır korunuyor. |
| Orta | Tarihsel workflow serbest metin girdisini doğrudan shell kaynak koduna yerleştiriyordu. | Girdiler process environment üzerinden tırnaklı argümanlara aktarılıyor. Sağlayıcı etiketi Gate.io olarak düzeltildi. |

## Veri ve karar zinciri

| Üretici | Girdi ve işlem | Tüketici ve çıkış |
|---|---|---|
| GateFuturesExchange | Public USDT contracts, candles, book, trades, ticker, contract_stats ve funding_rate. Sembol kontrat kimliğine, kontrat miktarı baz varlığa çevrilir. Geçici HTTP ve taşıma hatalarında sınırlı exponential backoff. | data_engine mum, defter, işlem, OI ve funding serilerini kurar. market_inventory turnover sıralaması üretir. |
| GatePublicStream ve microstructure_archive | Canlı işlemler, book ve likidasyon olayları; yerel arşiv replay için as-of snapshot sağlar. | shared.market_data_services CVD, footprint, spread, taraf hacmi ve veri durumu döndürür. Eksik geçmiş replay kapsamını sınırlar. |
| core.swing_engine, yapı motorları ve SMC alt motorları | Onay pencereli pivot, BOS/CHoCH, sweep, EQH/EQL, POI, mitigation, OTE ve zaman dilimi bağlamı | engine, AtlasMainEngine ve SMC adaptörü yön, zone ve olay kanıtlarını kullanır. Son H4 CHoCH yönü ve aktif OB/FVG içinde entry zorunlu; OTE danışman niteliğinde. |
| shared.analysis_context, market_structure_services, specialist_evidence | Aynı analiz içindeki hesapları yeniden kullanır. Yapı, momentum, volatilite ve bölge metrikleri üretir. | Strateji paketleri kanıtı kendi giriş koşullarında kullanır. |
| SevenStrategyLab.analyze | Yedi generate çağrısı, neden kodları, yapısal stop/hedef seçimi, tick yuvarlama, maliyet ve RR kontrolü | DecisionEngine uygun adaylar arasından seçim yapar. Generator istisnaları ilgili stratejide ERROR olarak tutulur. |
| AtlasRuntime, ScanService, ScanQueue | Sembol analizi, sıralanmış envanter, atomik claim, lease, retry, kalıcı iş durumu | Fırsat havuzu ve runtime ilerleme bilgisi. Telegram komut servisi aynı runtime'a erişir. |
| OpportunityPool, PoolStore | Aday, doğrulanmış ve kabul edilmiş setup, geçmiş ve yedek | Mevcut işlemler, yeniden doğrulama ve terminal/Telegram sunumu. Manuel trade journal ayrı depolama yoludur. |
| BacktestRunner, strategy_backtest | Karar saatine kadar kapanmış mumlar, tarihsel türev verileri, varsa arşiv L2; LIMIT expiry, kısmi çıkış ve işlem maliyetleri | İşlem sonuçları ve strateji tanılama raporları. İşlem örneği yetersiz olduğunda kazanma olasılığı çıkarılamaz. |

## Strateji girişleri

| Paket | Giriş kanıtı |
|---|---|
| trend | H4 EMA eğimi ve yönlü hareket, H1 pullback ve kapanış teyidi |
| breakout | Volatilite sıkışması, aralıktan çıkış ve kabul |
| mean_reversion | Rejim, istatistiksel sapma ve geri dönüş koşulları |
| liquidation | Likidasyon baskısı ve OI bağlamı |
| orderflow | Yönlü işlem akışı, footprint, absorpsiyon ve karşı likidite |
| relative_strength | Ortak zaman damgalarındaki BTC/ETH getirilerine göre beta düzeltilmiş göreli güç ve varsa sektör karşılaştırması |
| smc | Yönlü H4 yapı değişimi ve aktif fiyat bölgesi, entry/invalidation geometrisi |

## Ölçüm ve sınırlar

BTC/USDT:USDT, Gate.io, bir günlük istek. Katı birleşik replay 94 karar çağrısında iki SHORT dolumu üretti. MARKET −1,2576 R, beş mum sonra dolan LIMIT −1,4493 R. LONG dolumu yoktu. Kazanma oranı %0, PF 0, toplam −2,7069 R, ortalama gerçekleşen net sonuç −1,3535 R ve maksimum düşüş 2,7069 R. Bunlar model maliyetleriyle simüle edilmiş sonuçlardır.

Ayrı yedi strateji replay'i aynı sembolde her dört mumda bir 24 karar anını değerlendirdi (0,96 gün). Trend 4 ham aday üretti, 4'ü ortak filtreden elendi. SMC 2 aday üretti, 1'i elendi, 1'i seçildi. Seçilen SMC işlemi OOS bölümünde −1,4493 R ile kapandı. Breakout, mean reversion, liquidation ve relative strength 24 kez koşul sağlanmadığını, order flow ise 24 kez veri eksikliğini bildirdi. Diğer altı stratejide kapanmış işlem olmadığı için işlem başına metrikler tanımsızdır. Bu örnek strateji başarısını veya kârlılığını tahmin etmeye yetmez.

Aktif havuzda dolum sonrası eski giriş süresi dolsa da pozisyon izlenir. Kullanıcının kabulü diske hemen yazılır.

Aynı makinede 300 satırlık 15 SQLite generation oluşturma işleminin medyanı 7,22 ms'den 4,11 ms'ye indi. Deneyde geçici veritabanları kullanıldı. Canlı 300 sembollük tarama, üretim CPU/RAM, WS yeniden bağlanma gecikmesi ve Telegram teslim süresi bu ölçümün kapsamı dışındadır.

### Takip denetimi

300 sembol, beş zaman dilimi ve istek başına 100 sentetik mum ile çevrimdışı bellek ölçümünde veri sağlayıcısı 1.500 seri sakladı. 15m serileri tekrar okunmamasına rağmen bellekte kalıyordu. Yüksek zaman dilimlerinde 64 serilik LRU sınırı ve 15m yazımlarının kaldırılmasıyla aynı deneyde tutulan bellek 19.756.002 bayttan 844.040 bayta düştü (`tracemalloc`, süreç RSS'sinden ayrı). Sıcak serinin yeniden kullanılması, kapasite dolduğunda eski serinin çıkarılması ve 15m için her istekte yeni veri alınması regresyon testiyle doğrulandı.

- Aday, doğrulanmış, aktif ve geçmiş kayıtları artık tek SQLite transaction'ında yazılıyor. Geçmiş serileştirmesini son adımda bozarak eski adayın korunması ve kısmi aktif kaydın görülmemesi test edildi. Bellek içi geçmiş limiti dolduğunda yeni arşiv satırlarının kaybolmasına karşı da regresyon testi var.
- Manuel kuyruk genişletmesinde yeni işler, yeniden doğrulama, sıra ve sıralama kaynağı birlikte kaydediliyor. Generation açılırken sıralama yazımı hata verirse dönem numarası ve işler de geri alınıyor.
- BTC public WebSocket gözleminde 30 saniyelik 17 örnek boyunca bağlantı ve yeni işlemler görüldü. Dördüncü örnekten hemen sonra bağlantı test amacıyla kapatıldı; beşinci örnekte ikinci bağlantı ve son 30 saniyede 181 işlem vardı. Kesin yeniden bağlanma süresi bu örnekleme sıklığıyla ölçülemez. EOF sonrası L2 geçersizleştirme, sonsuz fiyat ve gelecekteki işlemlerin CVD'ye girmemesi ayrıca çevrimdışı test edildi.
- İzole 300 sembollük gerçek Gate.io kuyruğunun ilk 16 analizi 702 saniyede tamamlandı (kuyruğa yazımdan itibaren 1,37 sembol/dakika). Bu noktada 283 iş bekliyor, bir iş çalışıyordu. Gözlenen tepe RSS 217.860 KiB. Bu ara ölçüm üretim kapasitesi veya tam tarama süresi olarak yorumlanamaz.
- Telegram komut yanıtı gönderilirken ağ hatasındaki bot URL'si ve özel mesaj metninin loglara çıkması önlendi. Canlı uçtan uca teslim için yetkili test sohbeti ve yapılandırılmış bot gerekli. Üretim journal'ı kullanılmadı. Canlı L2 arşiv kapsamı hâlâ sembol ve tarihe bağlıdır.

## Mevcut VPS kurulumu için operatör adımları

CI başarılı olduktan sonra önce çalışan commit'i kaydedin. Mevcut kullanıcı servisini `systemctl --user stop atlas.service` ile durdurun. Çalışma dizinindeki SQLite veritabanları, WAL/SHM yan dosyaları, havuz, journal ve yerel yapılandırmanın erişim kontrollü yedeğini alın. Onaylanan commit'i ayrı checkout'ta test edin, servis çalışma ağacını o commit'e güncelleyin, ardından `systemctl --user start atlas.service` çalıştırın. Servis durumunu, generation kimliğini, pending/running sayılarını ve havuz kayıtlarını doğrulayın. Geri dönüşte servisi durdurup kaydedilen uygulama sürümüne geçin. Güncel veriyi koruyun; eski bir yedeği geri yüklemeden önce aradaki yeni kayıtların mutabakatını yapın.

## Dosya, yerel import ve çözülebilen çağrılar

| Dosya | Yerel import | Doğrudan çözülen çağrı |
|---|---|---|
| __init__.py | — | — |
| ai/__init__.py | — | — |
| ai/atlas_chat_agent.py | ai.openai_compat, config | ai.openai_compat.OpenAICompatClient, ai.openai_compat.OpenAICompatConfig, config.Config.refresh_from_env |
| ai/local_llama_server.py | — | — |
| ai/openai_compat.py | — | — |
| atlas_app.py | atlas_runtime, atlas_tui, config | atlas_runtime.AtlasRuntime, atlas_tui.AtlasTUIApp, config.Config.refresh_from_env |
| atlas_assistant.py | ai.atlas_chat_agent | ai.atlas_chat_agent.AtlasChatAgent |
| atlas_entry.py | atlas_app | atlas_app.main |
| atlas_main_engine.py | price_precision, risk_engine, shared.specialist_evidence | price_precision.normalize_tick_size, price_precision.snap_price_to_tick, risk_engine.RiskEngine, shared.specialist_evidence.build_strategy_evidence |
| atlas_runtime.py | config, daily_refresh, data_engine, engine, manual_trade_service, market_inventory, opportunity_pool, scan_queue, scan_service, shared.market_data_services, strategy_outcome_journal, timing | daily_refresh.DailyPoolRefresh, data_engine.exchange.load_markets, data_engine.get_correlation_universe, data_engine.get_market_data, data_engine.get_smt_universe, engine.AtlasEngine, manual_trade_service.ManualTradeService, market_inventory.get_market_inventory, opportunity_pool.SetupCandidate, opportunity_pool.get_opportunity_pool, scan_queue.ScanQueue, scan_service.ScanService, shared.market_data_services.build_shared_market_evidence, strategy_outcome_journal.StrategyOutcomeJournal, timing.closed_htf_candles |
| atlas_service.py | atlas_runtime, config, data_engine, market_inventory, telegram_botfather, telegram_command_service, universe_engine | atlas_runtime.AtlasRuntime, market_inventory.get_market_inventory, telegram_botfather.auto_register_on_startup, telegram_command_service.create_telegram_command_service, universe_engine.select_symbols |
| atlas_tui.py | data_engine, universe_engine, utils.signal_card | data_engine.exchange.fetch_ohlcv, data_engine.exchange.fetch_ticker, data_engine.exchange.fetch_tickers, data_engine.exchange.load_markets, universe_engine.select_symbols, utils.signal_card.build_selected_strategy_card, utils.signal_card.build_signal_card, utils.signal_card.format_card_text |
| backtest.py | backtest_runner, config, core.candle, data_engine, engine, historical_derivatives, sector_universe | backtest_runner.BacktestRunner, config.Config.refresh_from_env, core.candle.Candle, data_engine.TIMEFRAMES.items, data_engine.exchange.fetch_ohlcv, data_engine.exchange.load_markets, engine.AtlasEngine, historical_derivatives.load_historical_derivatives, sector_universe.configured_sector_peers |
| backtest_engine.py | — | — |
| backtest_runner.py | config, execution_costs, microstructure_archive, segmentation_report, timing | execution_costs.adverse_funding_cost_r, execution_costs.estimate_plan_cost, execution_costs.realized_trade_cost, microstructure_archive.snapshot_at, segmentation_report.segment_breakdown, timing.closed_htf_candles |
| bos_engine.py | — | — |
| breaker_block_engine.py | — | — |
| bybit_execution_engine.py | config | config.Config.refresh_from_env |
| canonical_features.py | — | — |
| choch_engine.py | — | — |
| cisd_engine.py | — | — |
| config.py | — | — |
| confluence_engine.py | — | — |
| core/__init__.py | — | — |
| core/analysis_utils.py | — | — |
| core/candle.py | — | — |
| core/market_state.py | — | — |
| core/market_structure_engine.py | core.pivot | core.pivot.Pivot |
| core/pivot.py | — | — |
| core/plugin.py | — | — |
| core/plugin_manager.py | — | — |
| core/swing_engine.py | — | — |
| correlation_engine.py | config, utils.atr | utils.atr.atr |
| daily_refresh.py | — | — |
| data_engine.py | config, core.candle, gateio_futures, microstructure_archive, price_precision, sector_universe, shared.market_data_services, strategies.orderflow.gateio_public_stream, trace_context | core.candle.Candle, gateio_futures.GateFuturesExchange, microstructure_archive.record_snapshot, price_precision.normalize_fee_rate, price_precision.normalize_tick_size, sector_universe.configured_sector_peers, shared.market_data_services.build_shared_market_evidence, strategies.orderflow.gateio_public_stream.GatePublicStream.for_symbol, trace_context.ensure_trace, trace_context.record_stage |
| decision_engine.py | config, rr_engine | rr_engine.RREngine |
| dynamic_tp_engine.py | config, utils.atr | utils.atr.atr |
| economic_news_engine.py | config | — |
| engine.py | atlas_main_engine, backtest_engine, bos_engine, breaker_block_engine, choch_engine, cisd_engine, config, confluence_engine, core.market_structure_engine, correlation_engine, decision_engine, dynamic_tp_engine, economic_news_engine, entry_confirmation_engine, entry_engine, entry_optimizer, fvg_engine, htf_fvg_engine, htf_orderblock_engine, institutional_engine, killzone_engine, learning_engine, liquidity_engine, liquidity_sweep_engine, manual_trade_quality, manual_trade_service, market_phase_engine, market_regime_engine, mitigation_engine, mtf_engine, orderblock_engine, orderbook_engine, ote_engine, position_manager, premium_discount_engine, risk_engine, rr_engine, scanner_engine, session_filter, setup_quality_engine, setup_reasoning_engine, signal_engine, smt_engine, state_engine, statistics_engine, strategy_lab, timing, trace_context, trade_cooldown_engine, trade_journal, trade_manager, trade_quality_engine, trend_engine, trendline_engine, unicorn_engine, utils.structure_labels, volume_profile_engine | atlas_main_engine.AtlasMainEngine, backtest_engine.BacktestEngine, bos_engine.BOSEngine, breaker_block_engine.BreakerBlockEngine, choch_engine.CHOCHEngine, cisd_engine.CISDEngine, config.Config, config.Config.refresh_from_env, confluence_engine.ConfluenceEngine, correlation_engine.CorrelationEngine, decision_engine.DecisionEngine, dynamic_tp_engine.DynamicTPEngine, economic_news_engine.EconomicNewsFilter, entry_confirmation_engine.EntryConfirmationEngine, entry_engine.EntryEngine, entry_optimizer.EntryOptimizer, fvg_engine.FVGEngine, htf_fvg_engine.HTFFVGEngine, htf_orderblock_engine.HTFOrderBlockEngine, institutional_engine.InstitutionalAnalysisEngine, killzone_engine.KillZoneEngine, learning_engine.LearningEngine, liquidity_engine.LiquidityEngine, liquidity_sweep_engine.LiquiditySweepEngine, manual_trade_quality.ManualTradeQualityGate, manual_trade_service.ManualTradeService, market_phase_engine.MarketPhaseEngine, market_regime_engine.MarketRegimeEngine, mitigation_engine.MitigationEngine, mtf_engine.MTFEngine, orderblock_engine.OrderBlockEngine, orderbook_engine.OrderBookEngine, ote_engine.OTEEngine, position_manager.PositionManager, premium_discount_engine.PremiumDiscountEngine, risk_engine.RiskEngine, rr_engine.RREngine, scanner_engine.ScannerEngine, session_filter.SessionFilter, setup_quality_engine.SetupQualityEngine, setup_reasoning_engine.SetupReasoningEngine, signal_engine.SignalEngine, smt_engine.SMTDivergenceEngine, state_engine.StateEngine, statistics_engine.StatisticsEngine, strategy_lab.SevenStrategyLab, timing.closed_htf_candles, trace_context.ensure_trace, trace_context.record_stage, trace_context.trace_id, trade_cooldown_engine.TradeCooldownEngine, trade_journal.TradeJournal, trade_manager.TradeManager, trade_quality_engine.TradeQualityEngine, trend_engine.TrendEngine, trendline_engine.TrendlineEngine, unicorn_engine.UnicornEngine, utils.structure_labels.label_swings, volume_profile_engine.VolumeProfileEngine |
| entry_confirmation_engine.py | — | — |
| entry_engine.py | config, utils.atr | utils.atr.atr |
| entry_optimizer.py | — | — |
| execution_costs.py | — | — |
| execution_engine.py | bybit_execution_engine | — |
| fvg_engine.py | — | — |
| gateio_futures.py | — | — |
| historical_derivatives.py | data_engine | — |
| htf_fvg_engine.py | — | — |
| htf_orderblock_engine.py | — | — |
| institutional_engine.py | core.analysis_utils | core.analysis_utils.clamp, core.analysis_utils.normalize_direction |
| killzone_engine.py | config | — |
| learning_engine.py | canonical_features, config | canonical_features.fingerprint_features, canonical_features.normalize_features |
| liquidity_engine.py | — | — |
| liquidity_sweep_engine.py | — | — |
| main.py | atlas_app | atlas_app.main |
| manual_trade_quality.py | — | — |
| manual_trade_service.py | — | — |
| market_inventory.py | gateio_futures | gateio_futures.GateFuturesExchange |
| market_phase_engine.py | — | — |
| market_regime_engine.py | — | — |
| microstructure_archive.py | — | — |
| microstructure_submotors.py | shared.microstructure_services | — |
| mitigation_engine.py | — | — |
| motor_ablation.py | backtest, backtest_runner, engine, historical_derivatives, microstructure_archive | backtest._disable_backtest_live_features, backtest.load_historical, backtest_runner.BacktestRunner, engine.AtlasEngine, historical_derivatives.load_historical_derivatives, microstructure_archive.snapshot_at |
| mtf_engine.py | — | — |
| opportunity_pool.py | pool_store | pool_store.PoolStore |
| orderblock_engine.py | — | — |
| orderbook_engine.py | — | — |
| ote_engine.py | — | — |
| plugins/__init__.py | — | — |
| plugins/bos/__init__.py | — | — |
| plugins/bos/detector.py | core.candle, core.market_state, core.pivot | — |
| plugins/bos/engine.py | core.plugin | — |
| plugins/choch/__init__.py | — | — |
| plugins/choch/engine.py | core.plugin | — |
| plugins/fvg/__init__.py | — | — |
| plugins/fvg/detector.py | core.candle | — |
| plugins/fvg/engine.py | core.plugin | — |
| plugins/liquidity/__init__.py | — | — |
| plugins/liquidity/detector.py | core.candle | — |
| pool_store.py | — | — |
| position_manager.py | config, execution_costs | execution_costs.estimate_stop_cost |
| premium_discount_engine.py | — | — |
| price_precision.py | — | — |
| report.py | trade_journal | trade_journal.TradeJournal |
| risk_engine.py | config, core.analysis_utils, execution_costs, price_precision, rr_engine, utils.atr | core.analysis_utils.clamp, execution_costs.estimate_plan_cost, execution_costs.estimate_stop_cost, price_precision.snap_price_to_tick, rr_engine.RREngine, utils.atr.atr |
| rr_engine.py | — | — |
| scan_queue.py | — | — |
| scan_service.py | — | — |
| scanner.py | atlas_app | atlas_app.main |
| scanner_engine.py | utils.signal_card | utils.signal_card.build_selected_strategy_card, utils.signal_card.build_signal_card |
| sector_universe.py | — | — |
| segmentation_report.py | — | — |
| session_filter.py | config | — |
| setup_quality_engine.py | canonical_features, core.analysis_utils, utils.atr | canonical_features.build_fingerprint, canonical_features.normalize_features, core.analysis_utils.clamp, utils.atr.atr |
| setup_reasoning_engine.py | config, dynamic_tp_engine, execution_costs, utils.atr | dynamic_tp_engine.DynamicTPEngine, execution_costs.estimate_plan_cost, execution_costs.estimate_stop_cost, utils.atr.atr |
| shared/analysis_context.py | — | — |
| shared/analysis_services.py | shared.analysis_context | — |
| shared/market_data_services.py | shared.microstructure_services | shared.microstructure_services.cumulative_volume_delta |
| shared/market_structure_services.py | shared.analysis_context | — |
| shared/microstructure_services.py | shared.analysis_context | — |
| shared/specialist_evidence.py | — | — |
| signal_engine.py | core.analysis_utils | core.analysis_utils.clamp, core.analysis_utils.direction_matches, core.analysis_utils.extract_confidence, core.analysis_utils.extract_direction, core.analysis_utils.is_active, core.analysis_utils.normalize_direction |
| smc_submotors.py | strategies.smc.submotors | — |
| smt_engine.py | — | — |
| state_engine.py | — | — |
| statistics_engine.py | — | — |
| strategies/__init__.py | — | — |
| strategies/breakout/__init__.py | — | — |
| strategies/breakout/strategy.py | strategy_lab | strategy_lab._atr, strategy_lab._attach_strategy_specialist_evidence, strategy_lab._bollinger, strategy_lab._candle_quality, strategy_lab._current_price, strategy_lab._entry_reference, strategy_lab._raw_candidate, strategy_lab._relative_volume, strategy_lab._series, strategy_lab._strategy_specialist_evidence, strategy_lab._value, strategy_lab.breakout_acceptance, strategy_lab.volatility_regime |
| strategies/liquidation/__init__.py | — | — |
| strategies/liquidation/strategy.py | strategy_lab | strategy_lab._atr, strategy_lab._attach_strategy_specialist_evidence, strategy_lab._candle_quality, strategy_lab._current_price, strategy_lab._entry_reference, strategy_lab._raw_candidate, strategy_lab._relative_volume, strategy_lab._strategy_specialist_evidence, strategy_lab._trade_flow, strategy_lab._value, strategy_lab.liquidation_events |
| strategies/mean_reversion/__init__.py | — | — |
| strategies/mean_reversion/strategy.py | strategy_lab | strategy_lab._atr, strategy_lab._attach_strategy_specialist_evidence, strategy_lab._bollinger, strategy_lab._candle_quality, strategy_lab._current_price, strategy_lab._entry_reference, strategy_lab._raw_candidate, strategy_lab._rsi, strategy_lab._series, strategy_lab._strategy_specialist_evidence, strategy_lab._value, strategy_lab._vwap, strategy_lab.rsi_divergence, strategy_lab.statistical_deviation |
| strategies/orderflow/__init__.py | — | — |
| strategies/orderflow/analytics.py | shared.analysis_context | — |
| strategies/orderflow/gateio_public_stream.py | — | — |
| strategies/orderflow/strategy.py | strategies.orderflow.analytics, strategy_lab | strategies.orderflow.analytics.footprint_directional_evidence, strategies.orderflow.analytics.liquidation_pressure, strategies.orderflow.analytics.opposing_liquidity_wall, strategy_lab._ORDERBOOK_ENGINE.analyze, strategy_lab._atr, strategy_lab._attach_strategy_specialist_evidence, strategy_lab._candle_quality, strategy_lab._current_price, strategy_lab._entry_reference, strategy_lab._raw_candidate, strategy_lab._strategy_specialist_evidence, strategy_lab._value, strategy_lab.build_orderflow_evidence, strategy_lab.cumulative_volume_delta, strategy_lab.displacement |
| strategies/relative_strength/__init__.py | — | — |
| strategies/relative_strength/strategy.py | strategy_lab | strategy_lab._atr, strategy_lab._attach_strategy_specialist_evidence, strategy_lab._current_price, strategy_lab._ema, strategy_lab._entry_reference, strategy_lab._raw_candidate, strategy_lab._series, strategy_lab._strategy_specialist_evidence, strategy_lab._value, strategy_lab.beta_stability, strategy_lab.relative_volume, strategy_lab.volatility_regime |
| strategies/smc/__init__.py | — | — |
| strategies/smc/strategy.py | strategy_lab | strategy_lab._configured_partial_tp_weights, strategy_lab._value, strategy_lab.breaker_validation, strategy_lab.dealing_range, strategy_lab.displacement, strategy_lab.inducement_proxy, strategy_lab.liquidity_draw, strategy_lab.math.isfinite, strategy_lab.poi_freshness, strategy_lab.reclaim_acceptance, strategy_lab.smc_narrative, strategy_lab.trend_structure |
| strategies/smc/submotors.py | — | — |
| strategies/trend/__init__.py | — | — |
| strategies/trend/strategy.py | strategy_lab | strategy_lab._adx, strategy_lab._atr, strategy_lab._attach_strategy_specialist_evidence, strategy_lab._candle_quality, strategy_lab._current_price, strategy_lab._directional_movement, strategy_lab._efficiency_ratio, strategy_lab._ema, strategy_lab._entry_reference, strategy_lab._raw_candidate, strategy_lab._series, strategy_lab._strategy_specialist_evidence, strategy_lab._value, strategy_lab.displacement, strategy_lab.trend_structure |
| strategy_backtest.py | backtest, backtest_runner, engine, execution_costs, historical_derivatives, microstructure_archive, strategy_outcome_journal | backtest.TIMEFRAME_DURATION_MS.items, backtest._configured_partial_tp_weights, backtest._disable_backtest_live_features, backtest._market_listing_time_ms, backtest._validate_backtest_coverage, backtest._validate_backtest_history, backtest.attach_historical_smt_universe, backtest.load_historical, backtest_runner.market_fallback_check, backtest_runner.rebase_remaining_targets, backtest_runner.simulate_trade_partial, engine.AtlasEngine, execution_costs.adverse_funding_cost_r, execution_costs.realized_trade_cost, historical_derivatives.load_historical_derivatives, microstructure_archive.snapshot_at, strategy_outcome_journal.StrategyOutcomeJournal |
| strategy_lab.py | config, decision_engine, orderbook_engine, price_precision, risk_engine, shared.analysis_context, shared.analysis_services, shared.market_data_services, shared.market_structure_services, shared.microstructure_services, shared.specialist_evidence, strategies.breakout, strategies.liquidation.strategy, strategies.mean_reversion, strategies.orderflow.analytics, strategies.orderflow.strategy, strategies.relative_strength.strategy, strategies.smc.strategy, strategies.smc.submotors, strategies.trend, trace_context | decision_engine.DecisionEngine, orderbook_engine.OrderBookEngine, price_precision.normalize_tick_size, price_precision.snap_price_to_tick, risk_engine.RiskEngine, shared.analysis_services._adx, shared.analysis_services._atr, shared.analysis_services._bollinger, shared.analysis_services._candle_quality, shared.analysis_services._efficiency_ratio, shared.analysis_services._ema, shared.analysis_services._rsi, shared.analysis_services._series, shared.analysis_services._valid_ohlc, shared.analysis_services._value, shared.market_data_services.build_shared_market_evidence, shared.specialist_evidence.STRATEGY_SPECIALIST_MOTORS.get, shared.specialist_evidence.attach_strategy_evidence, shared.specialist_evidence.evidence_for_strategy, strategies.orderflow.analytics.build_footprint, strategies.orderflow.analytics.footprint_directional_evidence, strategies.orderflow.analytics.liquidation_pressure, strategies.orderflow.analytics.opposing_liquidity_wall, strategies.orderflow.strategy._absorption_proxy, strategies.smc.strategy.generate, trace_context.ensure_trace, trace_context.record_stage, trace_context.trace_id |
| strategy_outcome_journal.py | — | — |
| strategy_performance.py | — | — |
| strategy_submotors.py | shared.market_structure_services | — |
| telegram_auth.py | config, telegram_auth_store | config.Config.refresh_from_env, telegram_auth_store.TelegramAuthStore |
| telegram_auth_store.py | — | — |
| telegram_botfather.py | telegram_commands | telegram_commands.get_botfather_commands |
| telegram_command_service.py | atlas_tui, opportunity_pool, telegram_commands, utils.signal_card | atlas_tui.AtlasTUIApp._format_liquidity, atlas_tui.AtlasTUIApp._format_performance, atlas_tui._is_report_command, atlas_tui._is_symbol_input, atlas_tui._parse_liquidity_command, atlas_tui._parse_scan_command, opportunity_pool.get_opportunity_pool, telegram_commands.format_help_text, telegram_commands.get_botfather_commands, telegram_commands.get_command_by_name, utils.signal_card.build_selected_strategy_card, utils.signal_card.build_signal_card |
| telegram_commands.py | — | — |
| telegram_engine.py | config, telegram_auth_store | config.Config.refresh_from_env, telegram_auth_store.TelegramAuthStore |
| telegram_service.py | config, manual_trade_service | config.Config.refresh_from_env, manual_trade_service.ManualTradeService |
| telegram_webhook.py | config, telegram_auth_store | config.Config.refresh_from_env, telegram_auth_store.TelegramAuthStore |
| test_microstructure_submotors.py | microstructure_submotors | microstructure_submotors.beta_stability, microstructure_submotors.cumulative_volume_delta, microstructure_submotors.liquidation_events, microstructure_submotors.relative_volume |
| test_smc_submotors.py | smc_submotors | smc_submotors.breaker_validation, smc_submotors.dealing_range, smc_submotors.inducement_proxy, smc_submotors.liquidity_draw, smc_submotors.narrative, smc_submotors.poi_freshness, smc_submotors.reclaim_acceptance |
| test_strategy_submotors.py | strategy_submotors | strategy_submotors.breakout_acceptance, strategy_submotors.displacement, strategy_submotors.rsi_divergence, strategy_submotors.statistical_deviation, strategy_submotors.trend_structure, strategy_submotors.volatility_regime |
| tests/__init__.py | — | — |
| tests/conftest.py | config | — |
| tests/test_active_setup_parallel_analysis.py | config, core.candle, engine, state_engine, strategy_lab | core.candle.Candle, engine.AtlasEngine, state_engine.StateEngine |
| tests/test_active_setup_persistence.py | state_engine | state_engine.StateEngine |
| tests/test_adaptive_entry_flow.py | entry_confirmation_engine, entry_engine, entry_optimizer | entry_confirmation_engine.EntryConfirmationEngine, entry_engine.EntryEngine, entry_optimizer.EntryOptimizer |
| tests/test_ai_chat_agent.py | ai.atlas_chat_agent | ai.atlas_chat_agent.AtlasChatAgent |
| tests/test_atlas_app_cli.py | atlas_app | atlas_app.build_parser, atlas_app.install_cli, atlas_app.main |
| tests/test_atlas_assistant.py | ai.atlas_chat_agent, atlas_assistant | atlas_assistant.AtlasAssistant |
| tests/test_atlas_main_engine.py | atlas_main_engine | atlas_main_engine.AtlasMainEngine, atlas_main_engine.AtlasMainEngine.finalize_setup_geometry |
| tests/test_atlas_runtime_manual_mode.py | atlas_runtime | atlas_runtime.AtlasRuntime |
| tests/test_atlas_scan_quality.py | atlas_tui | atlas_tui._best_symbols, atlas_tui._finite_number, atlas_tui._normalize_scan_limit |
| tests/test_atlas_service.py | atlas_service | atlas_service.configured_max_symbols, atlas_service.load_startup_symbols, atlas_service.select_live_symbols |
| tests/test_atlas_terminal_commands.py | atlas_tui | atlas_tui._best_symbols, atlas_tui._is_supported_input, atlas_tui._is_symbol_input, atlas_tui._parse_scan_command |
| tests/test_atr.py | core.candle, utils.atr | core.candle.Candle, utils.atr.atr |
| tests/test_backtest_aggregation.py | — | — |
| tests/test_backtest_data.py | core.candle | core.candle.Candle |
| tests/test_backtest_engine.py | backtest_engine | backtest_engine.BacktestEngine |
| tests/test_backtest_history.py | config | — |
| tests/test_backtest_journal_be_parity.py | backtest_runner, core.candle, trade_journal | backtest_runner.simulate_trade_partial, core.candle.Candle, trade_journal.TradeJournal |
| tests/test_backtest_runner.py | backtest_runner, config, core.candle | backtest_runner.BacktestRunner, backtest_runner._num, backtest_runner.simulate_trade, backtest_runner.simulate_trade_partial, core.candle.Candle |
| tests/test_backtest_zero_execution_repairs.py | config, dynamic_tp_engine, risk_engine, trade_quality_engine | dynamic_tp_engine.DynamicTPEngine, risk_engine.RiskEngine, trade_quality_engine.TradeQualityEngine |
| tests/test_bos_confirmation.py | bos_engine, core.candle, mitigation_engine, orderblock_engine | bos_engine.BOSEngine, core.candle.Candle, mitigation_engine.MitigationEngine, orderblock_engine.OrderBlockEngine |
| tests/test_breaker_direction.py | breaker_block_engine, core.candle | breaker_block_engine.BreakerBlockEngine, core.candle.Candle |
| tests/test_bybit_execution_engine.py | bybit_execution_engine, execution_engine | bybit_execution_engine.BybitExecutionEngine, bybit_execution_engine.OrderResult |
| tests/test_candle.py | core.candle | core.candle.convert |
| tests/test_choch_engine.py | choch_engine | choch_engine.CHOCHEngine |
| tests/test_cisd_confluence_signal_integration.py | confluence_engine, signal_engine | confluence_engine.ConfluenceEngine, signal_engine.SignalEngine |
| tests/test_cisd_engine.py | cisd_engine, core.candle | cisd_engine.CISDEngine, core.candle.Candle |
| tests/test_config_validation.py | config | config.Config.refresh_from_env, config.Config.validate, config.Config.validate_or_raise |
| tests/test_confluence_event_identity.py | confluence_engine | confluence_engine.ConfluenceEngine |
| tests/test_confluence_new_features.py | confluence_engine | confluence_engine.ConfluenceEngine |
| tests/test_confluence_signal_stack.py | confluence_engine, signal_engine | confluence_engine.ConfluenceEngine, signal_engine.SignalEngine |
| tests/test_core_analysis_utils.py | core.analysis_utils | core.analysis_utils.clamp, core.analysis_utils.direction_matches, core.analysis_utils.extract_confidence, core.analysis_utils.normalize_direction |
| tests/test_core_plugin_manager.py | core.plugin_manager | core.plugin_manager.PluginManager |
| tests/test_correlation_engine.py | core.candle, correlation_engine | core.candle.Candle, correlation_engine.CorrelationEngine |
| tests/test_data_engine.py | core.candle, data_engine, strategies.orderflow.gateio_public_stream | core.candle.Candle, data_engine._fetch, data_engine.get_market_data |
| tests/test_decision_engine.py | decision_engine, rr_engine | decision_engine.DecisionEngine, rr_engine.RREngine |
| tests/test_decision_engine_quality_filters.py | decision_engine | decision_engine.DecisionEngine |
| tests/test_dynamic_tp_quality.py | dynamic_tp_engine | dynamic_tp_engine.DynamicTPEngine |
| tests/test_economic_news_engine.py | economic_news_engine | economic_news_engine.EconomicNewsFilter |
| tests/test_engine.py | core.candle, core.market_structure_engine | core.candle.Candle, core.market_structure_engine.MarketStructureEngine |
| tests/test_engine_new_features.py | config, core.candle, engine | core.candle.Candle, engine.AtlasEngine |
| tests/test_engine_payload_recording.py | backtest_engine, scanner_engine, statistics_engine | backtest_engine.BacktestEngine, scanner_engine.ScannerEngine, statistics_engine.StatisticsEngine |
| tests/test_engine_smt_integration.py | atlas_main_engine, core.candle, engine | core.candle.Candle, engine.AtlasEngine |
| tests/test_entry_confirmation_engine.py | entry_confirmation_engine | entry_confirmation_engine.EntryConfirmationEngine |
| tests/test_entry_engine_fallback.py | entry_engine | entry_engine.EntryEngine |
| tests/test_entry_engine_quality.py | entry_engine | entry_engine.EntryEngine |
| tests/test_entry_optimizer.py | entry_optimizer | entry_optimizer.EntryOptimizer |
| tests/test_entry_optimizer_correlation.py | entry_optimizer | entry_optimizer.EntryOptimizer |
| tests/test_entry_optimizer_structural_motors.py | entry_optimizer | entry_optimizer.EntryOptimizer |
| tests/test_event_identity_engines.py | breaker_block_engine, core.candle, fvg_engine, orderblock_engine | breaker_block_engine.BreakerBlockEngine, core.candle.Candle, fvg_engine.FVGEngine, orderblock_engine.OrderBlockEngine |
| tests/test_execution_backtest_diagnostics.py | backtest_runner, core.candle | backtest_runner.BacktestRunner, core.candle.Candle |
| tests/test_execution_costs.py | config, execution_costs, position_manager | execution_costs.estimate_plan_cost, execution_costs.estimate_stop_cost, execution_costs.realized_trade_cost, position_manager.PositionManager |
| tests/test_execution_quality_improvements.py | config, core.candle, risk_engine, trade_quality_engine, utils.atr | core.candle.Candle, risk_engine.RiskEngine, trade_quality_engine.TradeQualityEngine |
| tests/test_external_motor_policy.py | atlas_main_engine | — |
| tests/test_finalize_geometry_risk_reconciliation.py | atlas_main_engine | atlas_main_engine.AtlasMainEngine.finalize_setup_geometry |
| tests/test_fvg_inversion.py | core.candle, fvg_engine | core.candle.Candle, fvg_engine.FVGEngine |
| tests/test_fvg_mitigation.py | core.candle, fvg_engine | core.candle.Candle, fvg_engine.FVGEngine |
| tests/test_gateio_futures.py | gateio_futures | gateio_futures.GateFuturesExchange |
| tests/test_gateio_public_stream.py | strategies.orderflow.gateio_public_stream | strategies.orderflow.gateio_public_stream.GatePublicStream |
| tests/test_historical_derivatives.py | historical_derivatives | historical_derivatives.load_historical_derivatives |
| tests/test_historical_funding_costs.py | core.candle, execution_costs | core.candle.Candle, execution_costs.adverse_funding_cost_r |
| tests/test_htf_poi_selection.py | htf_fvg_engine, htf_orderblock_engine | htf_fvg_engine.HTFFVGEngine, htf_orderblock_engine.HTFOrderBlockEngine |
| tests/test_incremental_cache_guards.py | engine | engine._has_dynamic_market_context |
| tests/test_institutional_engine.py | core.candle, institutional_engine | core.candle.Candle, institutional_engine.InstitutionalAnalysisEngine |
| tests/test_labels.py | core.swing_engine, utils.structure_labels | core.swing_engine.Swing, utils.structure_labels.label_swings |
| tests/test_learning_persistence.py | learning_engine | learning_engine.LearningEngine |
| tests/test_liquidity_engine_event_identity.py | core.candle, liquidity_engine | core.candle.Candle, liquidity_engine.LiquidityEngine |
| tests/test_liquidity_layers.py | core.candle, liquidity_engine | core.candle.Candle, liquidity_engine.LiquidityEngine |
| tests/test_liquidity_sweep_detection.py | core.candle, liquidity_sweep_engine | core.candle.Candle, liquidity_sweep_engine.LiquiditySweepEngine |
| tests/test_liquidity_sweep_reference_levels.py | core.candle, liquidity_engine, liquidity_sweep_engine | core.candle.Candle, liquidity_engine.LiquidityEngine, liquidity_sweep_engine.LiquiditySweepEngine |
| tests/test_live_learning_production.py | canonical_features, config, engine, learning_engine, manual_trade_quality, signal_engine, trade_journal | canonical_features.build_fingerprint, engine.AtlasEngine, learning_engine.LearningEngine, manual_trade_quality.ManualTradeQualityGate, signal_engine.SignalEngine, trade_journal.TradeJournal |
| tests/test_local_llama_server.py | ai.local_llama_server | ai.local_llama_server.LocalLlamaServerManager |
| tests/test_lookahead_timing.py | backtest_runner, core.candle, timing | backtest_runner.BacktestRunner, backtest_runner._window_up_to, core.candle.Candle, timing.closed_htf_candles |
| tests/test_main_entrypoint.py | atlas_app, main | — |
| tests/test_manual_trade_quality.py | config, manual_trade_quality, trade_journal | manual_trade_quality.ManualTradeQualityGate, trade_journal.TradeJournal |
| tests/test_manual_trade_service.py | manual_trade_service, trade_journal | manual_trade_service.ManualTradeService, trade_journal.TradeJournal |
| tests/test_market_data_freshness.py | atlas_runtime, core.candle | atlas_runtime._is_fresh_15m_data, core.candle.Candle |
| tests/test_market_data_usage.py | atlas_tui, shared.market_data_services, strategies.liquidation.strategy, strategy_lab, trace_context | atlas_tui._add_data_usage_section, shared.market_data_services._liquidation_evidence, shared.market_data_services.build_shared_market_evidence, strategies.liquidation.strategy.generate, strategy_lab.SevenStrategyLab, strategy_lab._setup_diagnostic, trace_context.new_trace_id |
| tests/test_market_data_validation.py | core.candle, engine | core.candle.Candle, engine.AtlasEngine.__new__, engine.AtlasEngine.__new__(AtlasEngine)._validate_market_data |
| tests/test_market_inventory.py | market_inventory | market_inventory.MarketInventory, market_inventory.reset_market_inventory |
| tests/test_market_phase.py | market_phase_engine | market_phase_engine.MarketPhaseEngine |
| tests/test_market_phase_identity.py | core.candle, market_phase_engine | core.candle.Candle, market_phase_engine.MarketPhaseEngine |
| tests/test_market_regime_engine.py | core.candle, decision_engine, market_regime_engine | core.candle.Candle, decision_engine.DecisionEngine, market_regime_engine.MarketRegimeEngine |
| tests/test_market_structure_confirmation.py | core.candle, core.market_structure_engine | core.candle.Candle, core.market_structure_engine.MarketStructureEngine |
| tests/test_microstructure_archive.py | microstructure_archive | microstructure_archive.record_snapshot, microstructure_archive.snapshot_at |
| tests/test_motor_ablation.py | motor_ablation | motor_ablation.DisabledMotor, motor_ablation._compare, motor_ablation._outcome_sensitivity, motor_ablation._sample_indices, motor_ablation._snapshot_for_index |
| tests/test_mtf_engine.py | mtf_engine, trend_engine | mtf_engine.MTFEngine, trend_engine.TrendEngine |
| tests/test_mtf_lookahead.py | config, core.candle, engine | core.candle.Candle, engine.AtlasEngine |
| tests/test_opportunity_pool_hardening.py | atlas_runtime, opportunity_pool | atlas_runtime.AtlasRuntime.__new__, opportunity_pool.OpportunityPool, opportunity_pool.SetupCandidate, opportunity_pool.SetupCandidate.from_dict |
| tests/test_orderbook_engine.py | orderbook_engine | orderbook_engine.OrderBookEngine |
| tests/test_orderflow_data_flow.py | shared.market_data_services, strategies.orderflow.analytics, strategies.orderflow.strategy, strategy_lab | shared.market_data_services.build_shared_market_evidence, strategies.orderflow.strategy.generate, strategy_lab.SevenStrategyLab, strategy_lab._setup_diagnostic |
| tests/test_orderflow_package.py | strategies.orderflow.analytics, strategies.orderflow.gateio_public_stream, strategies.orderflow.strategy, strategy_lab | strategies.orderflow.analytics.absorption_evidence, strategies.orderflow.analytics.build_cvd, strategies.orderflow.analytics.build_footprint, strategies.orderflow.analytics.footprint_directional_evidence, strategies.orderflow.analytics.liquidation_pressure, strategies.orderflow.analytics.liquidity_walls, strategies.orderflow.analytics.opposing_liquidity_wall, strategies.orderflow.gateio_public_stream.GatePublicStream, strategies.orderflow.strategy.generate |
| tests/test_ote_h4_range.py | engine, ote_engine | engine.AtlasEngine.__new__, engine.AtlasEngine.__new__(AtlasEngine)._h4_ote_range, ote_engine.OTEEngine |
| tests/test_pivot.py | core.pivot | core.pivot.Pivot |
| tests/test_pool_store.py | pool_store | pool_store.PoolStore |
| tests/test_premium_discount_engine.py | premium_discount_engine | premium_discount_engine.PremiumDiscountEngine |
| tests/test_price_precision.py | price_precision, risk_engine, strategy_lab | price_precision.snap_price_to_tick, risk_engine.RiskEngine, strategy_lab._risk_validate_candidate, strategy_lab._snap_candidate_to_exchange_tick |
| tests/test_profitability_quality_suite.py | backtest_engine, decision_engine, orderbook_engine, rr_engine | backtest_engine.BacktestEngine, backtest_engine.BacktestEngine.simulate_trade, decision_engine.DecisionEngine, orderbook_engine.OrderBookEngine, rr_engine.RREngine |
| tests/test_pytest_collection.py | — | — |
| tests/test_quality_filters_backtest.py | backtest_engine, core.candle, trade_quality_filters | backtest_engine.BacktestEngine, core.candle.Candle, trade_quality_filters.TradeQualityFilters |
| tests/test_risk_engine.py | config, dynamic_tp_engine, risk_engine, rr_engine | dynamic_tp_engine.DynamicTPEngine, risk_engine.RiskEngine, rr_engine.RREngine |
| tests/test_runtime_analysis_cache.py | atlas_runtime, config | atlas_runtime.AtlasRuntime.__new__ |
| tests/test_runtime_pool_integration.py | atlas_runtime, opportunity_pool | atlas_runtime.AtlasRuntime.__new__, opportunity_pool.OpportunityPool |
| tests/test_runtime_signal_id_resolution.py | atlas_runtime | atlas_runtime.AtlasRuntime.__new__ |
| tests/test_scan_queue.py | scan_queue | scan_queue.ScanQueue |
| tests/test_scan_queue_migration.py | scan_queue | scan_queue.ScanQueue |
| tests/test_scan_service_and_daily_refresh.py | daily_refresh, scan_service | daily_refresh.DailyPoolRefresh, daily_refresh.istanbul_day, daily_refresh.istanbul_hour, scan_service.ScanService |
| tests/test_scanner_entrypoint.py | atlas_app, scanner | — |
| tests/test_scanner_quality.py | scanner_engine | scanner_engine.ScannerEngine |
| tests/test_sector_universe.py | sector_universe | sector_universe.configured_sector_peers |
| tests/test_segmentation_report.py | backtest_runner, segmentation_report, trade_journal | backtest_runner.BacktestRunner, segmentation_report.build_report_payload, segmentation_report.classify_tp_behavior, segmentation_report.flatten_report_rows, segmentation_report.segment_breakdown, segmentation_report.trade_dimensions, segmentation_report.trade_metrics, segmentation_report.volatility_label, segmentation_report.write_csv_report, segmentation_report.write_json_report, trade_journal.TradeJournal |
| tests/test_selected_strategy_card.py | scanner_engine, utils.signal_card | scanner_engine.ScannerEngine, utils.signal_card.build_selected_strategy_card, utils.signal_card.format_card_text |
| tests/test_session_filter.py | config, session_filter | session_filter.SessionFilter |
| tests/test_setup_invalidation_reanalysis.py | atlas_runtime, opportunity_pool, state_engine | atlas_runtime.AtlasRuntime.__new__, opportunity_pool.OpportunityPool, opportunity_pool.SetupCandidate, state_engine.StateEngine |
| tests/test_setup_reasoning_engine.py | setup_reasoning_engine | setup_reasoning_engine.SetupReasoningEngine |
| tests/test_seven_strategies_independent.py | strategy_lab | strategy_lab.SevenStrategyLab |
| tests/test_seven_strategies_real_algorithms.py | strategies.breakout.strategy, strategies.liquidation.strategy, strategies.mean_reversion.strategy, strategies.orderflow.strategy, strategies.relative_strength.strategy, strategies.smc.strategy, strategies.trend.strategy, strategy_lab | strategies.breakout.strategy.generate, strategies.liquidation.strategy.generate, strategies.mean_reversion.strategy.generate, strategies.orderflow.strategy.generate, strategies.relative_strength.strategy.generate, strategies.smc.strategy.generate, strategies.trend.strategy.generate, strategy_lab._atr, strategy_lab._ema, strategy_lab._series |
| tests/test_shared_analysis_context.py | shared.analysis_context, shared.analysis_services | shared.analysis_context.AnalysisContext, shared.analysis_services._atr |
| tests/test_shared_analysis_services.py | shared.analysis_context, shared.market_structure_services, shared.microstructure_services, strategies.orderflow.analytics | shared.analysis_context.AnalysisContext, shared.market_structure_services.displacement, shared.market_structure_services.trend_structure, shared.market_structure_services.volatility_regime, shared.microstructure_services.beta_stability, shared.microstructure_services.relative_volume, strategies.orderflow.analytics.build_orderflow_evidence |
| tests/test_shared_market_data_services.py | shared.market_data_services | shared.market_data_services.build_shared_market_evidence |
| tests/test_signal_card.py | utils.signal_card | utils.signal_card.build_signal_card, utils.signal_card.format_card_text |
| tests/test_signal_card_direction.py | utils.signal_card | utils.signal_card.build_signal_card, utils.signal_card.format_card_text |
| tests/test_signal_engine_event_identity.py | signal_engine | signal_engine.SignalEngine |
| tests/test_signal_outcome_integration.py | canonical_features, config, core.candle, engine, learning_engine, setup_quality_engine, telegram_command_service, telegram_service, trade_journal | canonical_features.parse_fingerprint, core.candle.Candle, engine.AtlasEngine, learning_engine.LearningEngine, setup_quality_engine.SetupQualityEngine, telegram_command_service._format_telegram_card, telegram_command_service.format_daily_signal_report, telegram_service.TelegramTradeCommandHandler, trade_journal.TradeJournal |
| tests/test_signal_phase.py | signal_engine | signal_engine.SignalEngine |
| tests/test_signal_quality_gate.py | signal_engine | signal_engine.SignalEngine |
| tests/test_smc_mandatory_confluence.py | strategies.smc.strategy | strategies.smc.strategy._mandatory_confluence_reason |
| tests/test_smt_data_provider.py | data_engine | data_engine.get_smt_universe, data_engine.invalidate_all |
| tests/test_smt_engine.py | core.candle, smt_engine | core.candle.Candle, smt_engine.SMTDivergenceEngine |
| tests/test_specialist_evidence_routing.py | atlas_main_engine, shared.specialist_evidence, strategy_lab | atlas_main_engine.AtlasMainEngine, shared.specialist_evidence.attach_strategy_evidence, shared.specialist_evidence.evidence_for_strategy, strategy_lab._strategy_data_usage |
| tests/test_stale_entry_guards.py | engine, entry_engine, utils.signal_card | engine._tp1_already_reached, engine._tp1_touched_on_signal_candle, entry_engine.EntryEngine, utils.signal_card._num, utils.signal_card.build_signal_card, utils.signal_card.format_card_text |
| tests/test_state.py | core.market_state | core.market_state.MarketState |
| tests/test_state_learning_engines.py | core.candle, economic_news_engine, learning_engine, position_manager, state_engine, trade_cooldown_engine | core.candle.Candle, economic_news_engine.EconomicNewsFilter, learning_engine.LearningEngine, position_manager.PositionManager, state_engine.StateEngine, trade_cooldown_engine.TradeCooldownEngine |
| tests/test_state_optimization.py | core.candle, state_engine | core.candle.Candle, state_engine.StateEngine |
| tests/test_statistics_engine.py | statistics_engine | statistics_engine.StatisticsEngine |
| tests/test_strategy_advanced_models.py | strategy_lab | strategy_lab._absorption_proxy, strategy_lab._relative_strength |
| tests/test_strategy_backtest.py | backtest, backtest_runner, strategy_backtest | backtest._configured_partial_tp_weights, backtest_runner.BacktestRunner, strategy_backtest._accumulate_pipeline_metrics, strategy_backtest._empty_pipeline_metrics, strategy_backtest._snapshot_at, strategy_backtest._walk_forward_summary, strategy_backtest.simulate_candidate |
| tests/test_strategy_lab.py | decision_engine, strategies.breakout, strategies.liquidation.strategy, strategies.mean_reversion, strategies.orderflow.strategy, strategies.relative_strength.strategy, strategies.smc.strategy, strategies.trend, strategy_lab | decision_engine.DecisionEngine, strategies.breakout.generate, strategies.liquidation.strategy.generate, strategies.mean_reversion.generate, strategies.orderflow.strategy.generate, strategies.relative_strength.strategy.generate, strategies.smc.strategy.generate, strategies.trend.generate, strategy_lab.SevenStrategyLab, strategy_lab._adx, strategy_lab._atr, strategy_lab._candle_quality, strategy_lab._current_price, strategy_lab._directional_movement, strategy_lab._efficiency_ratio, strategy_lab._finalize_candidate_geometry, strategy_lab._liquidation_cascade, strategy_lab._mean_reversion, strategy_lab._orderflow_momentum, strategy_lab._raw_candidate, strategy_lab._regime, strategy_lab._relative_strength, strategy_lab._relative_volume, strategy_lab._rsi, strategy_lab._series, strategy_lab._smc_candidate, strategy_lab._structure_candle_sets, strategy_lab._trend_pullback, strategy_lab._valid_ohlc, strategy_lab._valid_plan, strategy_lab._volatility_breakout |
| tests/test_strategy_outcome_journal.py | strategy_outcome_journal | strategy_outcome_journal.StrategyOutcomeJournal |
| tests/test_strategy_performance.py | strategy_performance | strategy_performance.evaluate_strategy_edge, strategy_performance.rank_validated_candidate |
| tests/test_swing.py | core.candle, core.swing_engine | core.candle.Candle, core.swing_engine.detect |
| tests/test_telegram_auth_system.py | telegram_auth, telegram_auth_store, telegram_engine | telegram_auth.TelegramAuthService, telegram_auth_store.TelegramAuthStore, telegram_engine.TelegramBot |
| tests/test_telegram_botfather.py | telegram_botfather, telegram_commands | telegram_botfather.auto_register_on_startup, telegram_botfather.delete_bot_commands, telegram_botfather.get_botfather_commands, telegram_botfather.get_current_commands, telegram_botfather.register_bot_commands, telegram_botfather.verify_command_menu |
| tests/test_telegram_command_service.py | atlas_runtime, config, telegram_command_service, telegram_commands | telegram_command_service.TelegramCommandService, telegram_command_service._format_price, telegram_command_service._format_telegram_card, telegram_command_service.format_daily_signal_report, telegram_command_service.is_recognized_command, telegram_command_service.normalize_command, telegram_command_service.split_message, telegram_commands.get_command_by_name |
| tests/test_telegram_command_service_slash.py | atlas_runtime, telegram_command_service, telegram_commands | telegram_command_service.TelegramCommandService, telegram_command_service.TelegramCommandService._format_uptime, telegram_command_service._format_price, telegram_command_service._format_telegram_card, telegram_command_service.format_daily_signal_report, telegram_command_service.is_recognized_command, telegram_command_service.normalize_command, telegram_command_service.split_message |
| tests/test_telegram_commands.py | telegram_commands | telegram_commands.format_help_text, telegram_commands.get_all_categories, telegram_commands.get_botfather_commands, telegram_commands.get_command_by_name, telegram_commands.get_commands_by_category |
| tests/test_telegram_scan_and_pool_commands.py | opportunity_pool, telegram_command_service | opportunity_pool.OpportunityPool, opportunity_pool.SetupCandidate, telegram_command_service.TelegramCommandService, telegram_command_service.is_recognized_command |
| tests/test_telegram_service.py | telegram_service | telegram_service.TelegramService |
| tests/test_telegram_signal_consistency.py | core.candle, engine, telegram_engine | core.candle.Candle, engine.AtlasEngine, telegram_engine.TelegramBot.trade_feedback_keyboard, telegram_engine.TelegramEngine |
| tests/test_terminal_reports.py | atlas_tui | atlas_tui._is_supported_input, atlas_tui._parse_liquidity_command |
| tests/test_timing_boundaries.py | core.candle, timing | core.candle.Candle, timing.closed_htf_candles |
| tests/test_tp_rr_consistency_direction.py | trade_quality_filters | trade_quality_filters.TradeQualityFilters |
| tests/test_trace_context.py | trace_context | trace_context.ensure_trace, trace_context.new_trace_id, trace_context.record_stage, trace_context.trace_id |
| tests/test_trace_end_to_end.py | config, core.candle, engine, strategy_lab, trace_context | core.candle.Candle, engine.AtlasEngine, strategy_lab.SevenStrategyLab, trace_context.new_trace_id |
| tests/test_trade_cooldown_engine.py | trade_cooldown_engine | trade_cooldown_engine.TradeCooldownEngine |
| tests/test_trade_journal.py | trade_journal | trade_journal.TradeJournal |
| tests/test_trade_journal_engine_integration.py | core.candle, engine | core.candle.Candle, engine.AtlasEngine |
| tests/test_trade_journal_retention.py | config, trade_journal | trade_journal.TradeJournal |
| tests/test_trade_quality_engine.py | trade_quality_engine | trade_quality_engine.TradeQualityEngine |
| tests/test_trade_quality_filters.py | config, core.candle, trade_quality_filters | core.candle.Candle, trade_quality_filters.TradeQualityFilters |
| tests/test_trendline_engine.py | core.candle, trendline_engine | core.candle.Candle, trendline_engine.TrendlineEngine |
| tests/test_tui_imports.py | atlas_tui | — |
| tests/test_unicorn_engine.py | unicorn_engine | unicorn_engine.UnicornEngine |
| tests/test_unicorn_integration.py | confluence_engine, signal_engine, telegram_engine | confluence_engine.ConfluenceEngine, signal_engine.SignalEngine, telegram_engine.TelegramEngine |
| tests/test_universe_engine.py | universe_engine | universe_engine.select_symbols |
| tests/test_volume_profile_engine.py | core.candle, volume_profile_engine | core.candle.Candle, volume_profile_engine.VolumeProfileEngine |
| tests/test_volume_profile_integration.py | confluence_engine, decision_engine, risk_engine, signal_engine | confluence_engine.ConfluenceEngine, decision_engine.DecisionEngine, risk_engine.RiskEngine, signal_engine.SignalEngine |
| tests/test_websocket_first_snapshot.py | strategies.orderflow.gateio_public_stream | strategies.orderflow.gateio_public_stream.GatePublicStream |
| timing.py | — | — |
| trace_context.py | — | — |
| trade_cooldown_engine.py | config | — |
| trade_journal.py | canonical_features, config, execution_costs | canonical_features.build_fingerprint, canonical_features.normalize_features, canonical_features.parse_fingerprint, execution_costs.realized_trade_cost |
| trade_manager.py | — | — |
| trade_quality_engine.py | config, trade_quality_filters, utils.atr | trade_quality_filters.TradeQualityFilters, utils.atr.atr |
| trade_quality_filters.py | config, utils.atr | utils.atr.atr |
| trend_engine.py | — | — |
| trendline_engine.py | — | — |
| unicorn_engine.py | — | — |
| universe_engine.py | — | — |
| utils/__init__.py | — | — |
| utils/atr.py | — | — |
| utils/signal_card.py | — | — |
| utils/structure_labels.py | — | — |
| volume_profile_engine.py | core.analysis_utils | core.analysis_utils.clamp |
