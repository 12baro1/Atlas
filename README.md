# Atlas

Atlas, Gate.io USDT perpetual piyasalarını terminal üzerinden analiz eder. Beş işlem stratejisi (Trend Pullback, Volatility Breakout, Mean Reversion, Order Flow Momentum, SMC) setup üretir. İki salt-okunur uzman (Relative Strength ve Liquidation Cascade) piyasa kanıtı sağlar, bağımsız işlem açmaz. Android UserLAnd/Ubuntu ve Linux üzerinde kullanılabilir.

**Bu sürüm analiz aracıdır; otomatik al-sat yapmaz.** Borsaya emir veya pozisyon göndermez. Analiz için herkese açık piyasa verilerini kullanır. Gate.io public futures API anahtarı gerekmez.

## Gereksinimler

- Ubuntu (UserLAnd) veya Linux
- Python 3, venv ve pip
- Git
- İnternet bağlantısı

## Kurulum

Ubuntu terminalinde aşağıdaki komutları sırayla çalıştır:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip build-essential
git clone https://github.com/12baro1/Atlas.git
cd Atlas
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

UserLAnd ortamında `sudo` kullanılamıyorsa apt komutlarını sudo olmadan çalıştır.

## Başlatma

Her yeni terminal oturumunda:

```bash
cd ~/Atlas
source venv/bin/activate
./atlas
```

İstersen komutu sisteme kurup her klasörden `atlas` olarak çalıştırabilirsin:

```bash
python atlas_app.py --install-cli
source ~/.bashrc
atlas
```

Komut bulunamazsa proje klasöründen `./atlas` ile başlat.

Belirli bir sembolle doğrudan açmak için:

```bash
./atlas BTC
./atlas ETH
```

## VPS üzerinde sürekli canlı analiz servisi

Sunucu servisi, terminal arayüzünü açmadan aynı `AtlasRuntime` ve `AtlasEngine` analiz hattını arka planda çalıştırır. Beş strateji, iki kanıt uzmanı, ortak analiz servisleri ve tek karar mekanizması korunur. Varsayılan tarama sınırı 50 coindir; sıralama Gate.io 24 saatlik USDT işlem hacmine göredir. `.env` içindeki `ATLAS_MAX_SYMBOLS` daha küçük bir sınır belirleyebilir, 50'yi aşamaz. Eski 300'lük tarama kuyruğu yeni 50'lik nesle taşınır; işlem takip kayıtlarına dokunulmaz.

### Otomatik kurulum (önerilen)

```bash
cd ~/Atlas
./deploy/setup_vps.sh
```

Bu script:
1. Python sanal ortamı ve bağımlılıkları kurar
2. `.env` dosyasını oluşturur (`.env.example` varsa)
3. Testleri çalıştırır
4. systemd kullanıcı servisini kurar ve SSH oturumu kapandıktan sonra da çalışabilmesi için linger ayarını doğrular
5. Servisi etkinleştirir ve güncel servis tanımıyla başlatır

### Manuel kurulum

```bash
cd ~/Atlas
cp .env.example .env
# İsteğe bağlı ayarları .env içinde düzenle.
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q tests/test_atlas_service.py tests/test_telegram_command_service.py
mkdir -p ~/.config/systemd/user
cp deploy/atlas.service ~/.config/systemd/user/atlas.service
systemctl --user daemon-reload
sudo loginctl enable-linger "$(whoami)"
systemctl --user enable atlas.service
systemctl --user restart atlas.service
```

Servis beklenmedik çıkıştan 30 saniye sonra tekrar başlatılır. Ana denetim döngüsünden üç dakika boyunca yaşam sinyali gelmezse systemd süreci yeniden başlatır. Kasıtlı `systemctl --user stop atlas.service` komutu servisi durdurur.

### Doğrulama komutları

```bash
systemctl --user status atlas.service
systemctl --user show atlas.service -p NRestarts -p Result -p WatchdogTimestamp
loginctl show-user "$(whoami)" -p Linger
journalctl --user -u atlas.service -n 100 --no-pager
systemctl --user restart atlas.service
```

Servis, beş stratejili işlem hattını ve iki kanıt uzmanını değiştirmez. VPS modunda eski otomatik Telegram sinyal bildirimi ve eski Telegram polling kapalı tutulur; yeni Telegram entegrasyonu yalnızca tanınan grup komutlarına cevap verir, kendi kendine sinyal göndermez. Otomatik emir gönderimi de kapalıdır.

BotFather komut menüsü servis başlangıcında `setMyCommands` API'si ile otomatik yüklenir. Elle doğrulamak için:
```bash
source .venv/bin/activate
python -m telegram_botfather verify
```

### Telegram grup komutları

Botu gruba ekledikten sonra BotFather üzerinden `/setprivacy` → botu seç → **Disable** yap. Bu ayar, botun gruptaki düz `BTC` mesajını görebilmesi için gereklidir.

VPS'deki `.env` dosyasına şu ayarları ekle:

```env
ATLAS_TELEGRAM_COMMANDS_ENABLED=1
ATLAS_TELEGRAM_BOT_TOKEN=
ATLAS_TELEGRAM_CHAT_ID=
```

Token'ı depoya veya sohbetlere yazma. `ATLAS_TELEGRAM_CHAT_ID` yalnızca izin verilen grubun ID'si olmalıdır. Bot diğer sohbetleri ve tanınmayan grup mesajlarını sessizce yok sayar.

Komutlar **sadece slash (`/`) formatında** çalışır:
- `/btc` `/eth` `/sol` — Hızlı coin analizi
- `/analiz BTC` — Belirtilen coin analizi
- `/20tara` `/30tara` `/50tara` `/100tara` — N piyasa tara
- `/tumtara` — Tüm desteklenen USDT perpetual piyasaları tara
- `/kaldir ARB`, `/kaldır ARB`, `/çıkart ARB` veya `/cikart ARB` — Bu sohbetin ARB takibini durdurur ve sembolü `/islemler` listesinden çıkarır.
- `/ekle ARB` — Yeni bir geçerli plan geldiğinde bu sohbette ARB takibini başlatır.
- `/eniyi5` — Arka plan havuzundan en iyi 5 setup (yeni tarama **başlatmaz**)
- `/mevcut` `/setuplar` `/takip` `/likidite BTC` — Setup ve takip
- `/performans` `/istatistik` `/ogrenme` — Performans ve öğrenme
- `/durum` `/sistem` `/yardim` — Sistem durumu ve yardım

Bot username eklenmiş biçim de çalışır: `/btc@BotAdi`, `/analiz BTC@BotAdi`. Komut isimleri büyük/küçük harf duyarsızdır.

**BotFather komut menüsü** (kod ile birebir eşleşir, `setMyCommands` ile otomatik yüklenir):
```
btc - BTC analizi yap
eth - ETH analizi yap
sol - SOL analizi yap
analiz - Belirtilen coin analizi (örn: /analiz BTC)
20tara - 20 piyasa tara
30tara - 30 piyasa tara
50tara - 50 piyasa tara
100tara - 100 piyasa tara
tumtara - Tüm desteklenen USDT perpetual piyasaları tara
eniyi5 - Arka plan havuzundan en iyi 5 setup'ı getir (yeni tarama başlatmaz)
mevcut - Bugünün setup ve işlem takibi
setuplar - Aktif setup havuzunu listele
takip - Açık sinyal takibi
likidite - Belirtilen coin için likidite haritası (örn: /likidite BTC)
performans - Tüm geçmiş performans istatistikleri
istatistik - Sinyal ve manuel işlem istatistikleri
ogrenme - Öğrenme motoru verisi
durum - Bot ve servis durumu (VPS, tarama, bağlantı)
sistem - Sistem kaynakları ve çalışma durumu
yardim - Komut listesi ve kullanım
```

Eski normal-metin komutlar (örn. `btc`, `en iyi 5 işlem`) geriye dönük uyumluluk için desteklenir ama slash komutları önerilir.

## Kullanım

Atlas açıldığında komut alanına sembol veya desteklenen komutlardan birini yaz:

| Komut | İşlev |
|---|---|
| `BTC`, `ETH`, `SOL` | İlgili piyasayı 5 strateji + 2 uzmanla analiz eder; tek plan seçer |
| `işlem ver` | Varsayılan taramayı çalıştırır ve uygun kurulum arar |
| `50 analiz et` | 50 piyasayı tarar |
| `100 analiz et` | 100 piyasayı tarar |
| `en iyi 5 işlem` | Tarama sonuçlarından en iyi 5 kurulumu listeler |
| `tüm piyasayı tara` | Desteklenen tüm USDT perpetual piyasalarını tarar |
| `likidite BTC` | BTC likidite seviyelerini gösterir |
| `performans` | Kayıtlı işlem performansını gösterir |
| `öğrenme` | Kayıtlı öğrenme verisini gösterir |
| `yardım` | Komutları listeler |
| `çıkış` | Programdan çıkar |

Tarama süresi piyasa sayısına ve internet bağlantısına göre değişir. Geçerli koşulları sağlayan kurulum yoksa Atlas sinyal üretmeyebilir.

## Order Flow veri akışı

`strategies/orderflow/` altında Order Flow'a özel veri bileşenleri bulunur:

- `gateio_public_stream.py`: Gate.io USDT Futures WebSocket üzerinden public trades, ticker ve `futures.public_liquidates` (`!all`) akışını toplar. `!all` liquidation aboneliği süreç içinde tek bağlantı olarak paylaşılır.
- Order book, OHLCV, ticker ve REST trade verileri Gate.io Futures REST API'den alınır. WebSocket order book sağlamaz; order book kaynağı REST'tir.
- `analytics.py`: gerçekleşen agresör notional'ından CVD ve footprint, REST L2 order book'tan görüntülenen liquidity wall, trade/candle verisinden açıkça proxy olarak etiketlenen absorption kanıtı üretir.
- Trade akışı ve liquidation olayları yalnızca Gate.io'dan gerçekten alındıkları zaman damgalarıyla raporlanır. Geçmiş L2/trade verisi geriye dönük oluşturulamaz.
- WebSocket verisi yoksa Gate.io REST verisi kullanılabilir. Gate.io erişilemezse başka borsaya geçilmez; ilgili feed `UNAVAILABLE` kalır.
- Absorption ve liquidity wall sonuçları kesin emir niyeti değildir: absorption bir çıkarım, wall ise iptal edilebilir görüntülenen derinliktir.

## 5 işlem stratejisi + 2 kanıt uzmanı

Tek coin analizinde ve en yüksek 24 saatlik USDT işlem hacmine sahip 50 Gate.io perpetual coin taramasında yalnızca beş işlem stratejisi kendi ham planını üretir. Relative Strength ve Liquidation Cascade analiz kanıtı sağlar. Ortak filtre giriş yönünü, yapısal stop ve hedefleri, işlem maliyetlerini ve maliyet sonrası net RR eşiğini (varsayılan 2,0) kontrol eder. Hedefler fiyat adımına yuvarlandıktan sonra farklı seviyelerde kalmalıdır. Merkezi karar motoru uygun adayları önce rejim uyumuyla ağırlıklandırılan setup gücüne, eşitlikte net RR'a göre sıralar. SMC diğer dört işlem stratejisiyle aynı seçim aşamasına girer. `/motorlar` üretim sayaçlarını, `/istatistik` sık görülen eleme nedenlerini gösterir.

**Önemli doğrulama sınırı:** SMC dışındaki dört işlem stratejisi deneysel aday üreticilerdir. Strateji replay'i kronolojik IS/OOS ayrımı ve 5 anchored walk-forward penceresi kullanır; maliyetler ve tarihsel funding verisi mevcut olduğunda aynı yürütme simülatöründen geçirilir. Bunlar gerçek borsa dolumu değildir. Eksik veya kısmi OI/funding verisi açıkça raporlanır; funding geçmişi tam kapsama sahip değilse --persist performans günlüğüne sonuç yazmaz. Order Flow Momentum yalnızca karar zamanından önce arşivlenmiş, taze order-book/trade örnekleri varsa tarihsel olarak ölçülebilir. Liquidation Cascade gerçek likidasyon akışı değil, OI/funding/işlem akışı proxy'sidir. Performans günlüğü aynı kod revizyonu, sembol ve rejim için IS/OOS sonuçlarını ayrı izler. Atlas emir göndermez.

## Backtest

Sanal ortam açıkken proje klasöründe:

```bash
python3 backtest.py --symbol BTC/USDT:USDT --days 7
```

Birden fazla sembol:

```bash
python3 backtest.py --symbols "BTC/USDT:USDT,ETH/USDT:USDT" --days 30
```

Daha büyük veri aralığını parçalara bölerek, eski dönem (IS) ile en yeni dönem (OOS) performansını ayrı ölç:

```bash
python3 backtest.py --symbols "BTC/USDT:USDT,ETH/USDT:USDT" --days 60 --chunk-days 10 --walk-forward
```

Walk-forward raporunda parametreler değiştirilmez. Eski parçalar eğitim/IS, en yeni parçalar dokunulmamış OOS kontrolüdür. Bu bir parametre optimizasyonu değildir. Küçük OOS örneklemi kârlılık kanıtı sayılmaz.

Backtest geçmiş veriyi simüle eder; gerçek piyasa dolumunu veya gelecekteki performansı garanti etmez.

## 5 strateji backtesti

Beş işlem üreticisini ayrı ayrı tarihsel replay ile ölçmek için:

```bash
python3 strategy_backtest.py --symbol BTC/USDT:USDT --days 30 --max-holding-bars 32 --limit-expiry-bars 8
```

Bu replay yalnızca kapanmış mumlarla karar verir; MARKET girişini sonraki 15m açılışında, LIMIT emrini en fazla 8 bar boyunca bekleterek doldurur. Gap-through LIMIT açılışta marketable limit olarak, sınırları içindeki yakın kaçırılmış LIMIT ise aynı kontrollü MARKET fallback kuralıyla ele alınır. Emir dolmadan hedef seviyesi aşılırsa kalan yapısal hedefler yeniden hesaplanır. Dolumdan sonra varsayılan maksimum tutma süresi 32 adet 15m bardır (8 saat); süre dolarsa pozisyon son kapanışta kapatılır. Kısmi TP ağırlıkları yapılandırılabilir; aynı mumda SL ve TP birlikte görülürse SL önce kabul edilir. Komisyon, spread, slippage ve mevcut tarihsel funding maliyeti net R'den düşülür.

Maliyet modeli ve IS/OOS kayıtlarını yerel performans günlüğüne yazmak için açıkça `--persist` ekle:

```bash
python3 strategy_backtest.py --symbol BTC/USDT:USDT --days 30 --persist
```

Performans kayıtları sembol, rejim ve kod revizyonuna göre ayrılır. Kod revizyonu değiştiğinde eski sonuçlar yeni sürümün seçiminde kullanılmaz. Canlı aday seçimini ortak risk filtresi ve merkezi sıralama belirler.

**Tarihsel veri sınırı:** OI ve funding geçmişi Gate.io'in tarihsel uç noktalarından zaman damgasıyla alınır. Veri kapsaması HISTORICAL, PARTIAL veya UNAVAILABLE olarak raporlanır. Funding ödemeleri pozisyon yönüne göre modellenir; olumsuz debiler maliyete yazılır, olumlu krediler muhafazakâr biçimde kazanç sayılmaz. Kısmi funding geçmişiyle sonuç üretilebilir ancak bu sonuç strateji terfisi için kalıcı performans günlüğüne yazılmaz. Geçmiş order-book/taker-trade snapshot'ları geriye dönük üretilemez; Order Flow Momentum yalnızca yerel arşivde karar anından önce mevcut olan taze örneklerle ölçülür.


## Motor katkısı (ablation)

Uzman motorların kararı ve örneklenmiş tek işlem sonucunu nasıl etkilediğini ölçmek için:

```bash
python3 motor_ablation.py --symbol BTC/USDT:USDT --days 14 --samples 3
```

Rapor her motoru aynı karar anlarında tek tek devre dışı bırakır; karar/plan değişimini ve ortak SMC yürütme simülatörüyle hesaplanan örnek net-R farkını gösterir. Bu, tam portföy backtesti veya nedensel kârlılık kanıtı değildir. Varsayılan örnekler yüklenen tarih aralığına eşit yayılır. Sabit aralık istersen --step 96 kullan.

## Güncelleme

```bash
cd ~/Atlas
git pull --ff-only origin main
source venv/bin/activate
python -m pip install -r requirements.txt
```

## Sorun giderme

**`atlas: command not found`**

```bash
cd ~/Atlas
source venv/bin/activate
./atlas
```

**`No module named ...`**

```bash
cd ~/Atlas
source venv/bin/activate
python -m pip install -r requirements.txt
```


## Demo forward doğrulaması

Backtest ve motor ablation raporları gerçek zamanlı forward test yerine geçmez. Atlas otomatik emir göndermez; bu nedenle canlı/demoda gerçekleşen dolum, spread, kayma ve funding sonuçları henüz otomatik olarak doğrulanmış sayılmaz. Mikro yapı arşivi yalnızca Atlas çalışırken yeni snapshot biriktirir; geçmiş L2 verisini geriye dönük oluşturmaz. Strateji terfisi veya gerçek sermaye kullanımı öncesinde demo ortamında yeterli sayıda kapanmış sinyalin gerçek zamanlı takibi ve sonuçlarının maliyet sonrası karşılaştırılması gerekir.

## Güvenlik

- Analiz için borsa API anahtarı girme; Atlas'ın normal kullanımında gerekmez.
- Gerçek API anahtarı, parola veya kişisel erişim bilgilerini depoya yükleme.
- Sinyaller yatırım tavsiyesi değildir ve kâr garantisi vermez.
- Önce demo ortamında doğrula. Kaldıraçlı işlemlerde sermayenin tamamı kaybedilebilir.

## Tarihsel doğrulama, funding ve mikro yapı arşivi

Beş işlem stratejisinin tarihsel karşılaştırması:

```bash
python3 strategy_backtest.py --symbol BTC/USDT:USDT --days 30
```

- Rapor, 5 ardışık test pencereli anchored walk-forward sonuçlarını IS/OOS sonuçlarından ayrı gösterir.
- Gate.io'in tarihsel OI ve funding uç noktaları destekleniyorsa zaman damgalı seriler yüklenir. Funding ödemesi pozisyon yönüne göre net R'ye yansıtılır.
- Funding geçmişi alınamazsa `--persist` sonuçları performans günlüğüne yazmaz. Eksik maliyetli örnekler strateji seçiminde kullanılamaz.
- Canlı order-book ve recent-trade örnekleri yerel olarak `data/microstructure/` altında JSONL arşivine kaydedilir.
- Salt-okunur Relative Strength uzmanı, BTC/ETH beta-adjusted residual alpha kullanır. İsteğe bağlı sektör/peer grubu `ATLAS_SECTOR_PEERS_JSON` ile tanımlanır; örnek: `{"SOL":["AVAX/USDT:USDT","ADA/USDT:USDT"]}`. Bilinmeyen coinlere otomatik sektör etiketi uydurulmaz.
- Order Flow Momentum, agresif alış/satış akışı fiyatı ilerletemediğinde ve karşı tarafta derinlik varsa absorption proxy üretir. Bu, gerçek kuyruk yenilenmesi veya gizli emir kanıtı değildir. Kapatmak için `ATLAS_MICROSTRUCTURE_ARCHIVE_ENABLED=0` ayarlayın.
- Geçmiş order-book verisi geriye dönük üretilemez. Order-flow replay yalnızca karar zamanından önce arşivlenmiş ve tazeliği doğrulanmış örnekleri kullanır. Arşiv oluşana kadar bu motorun tarihsel performansı ölçülmüş sayılmaz.
- Arşiv her sembol için varsayılan 5 MiB ve 7 gün ile sınırlandırılır. İhtiyaca göre ATLAS_MICROSTRUCTURE_ARCHIVE_MAX_BYTES ve ATLAS_MICROSTRUCTURE_ARCHIVE_RETENTION_DAYS ayarlanabilir.
- Salt-okunur Liquidation Cascade uzmanı, gerçek liquidation-event akışı değildir; tarihsel OI/funding ve varsa arşivlenmiş trade-flow ile sınırlı bir proxy'dir.

Komisyon, spread ve slippage hâlâ parametreli yürütme varsayımlarıdır; gerçek emir gerçekleşme fiyatı değildir. Walk-forward çıktısı kârlılık garantisi veya parametre optimizasyonu anlamına gelmez.


### Ortak analiz servisleri

- `shared/analysis_services.py`: OHLCV doğrulama, seri çıkarımı, EMA, Wilder ATR/ADX, RSI, VWAP, Bollinger, yönsel hareket ve mum anatomisi gibi strateji-nötr hesaplamaların tek kaynağıdır.
- `shared/analysis_context.py`: her `SevenStrategyLab.analyze()` çağrısında izole bir memoization bağlamı açar. Aynı kapanmış mum nesneleri ve parametrelerle istenen hesaplamalar stratejiler arasında yeniden kullanılabilir; yeni sembol/snapshot analizinde cache temiz başlar.
- `strategy_lab.py` bu servisleri eski yardımcı adlarıyla dışa aktarmaya devam eder; böylece strateji adaptörlerinin uyumluluğu korunurken hesaplama sahipliği `shared/` katmanına taşınır.

- `shared/market_structure_services.py`: trend structure, displacement, volatility regime, breakout acceptance, statistical deviation and RSI divergence evidence. The SMC package continues to own its SMC-specific submotors; generic structure/displacement evidence is shared.
- `shared/microstructure_services.py`: timestamped CVD, liquidation-event validation, beta stability and relative-volume calculations. The legacy top-level modules remain compatibility re-exports, while strategy generators import the shared implementations through the lab.
