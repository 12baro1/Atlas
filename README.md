# Atlas

Atlas, Bybit USDT perpetual piyasalarını terminal üzerinden analiz eder. Tek coin analizinde 7 ayrı stratejiyi çalıştırır: Trend Following + Pullback, Volatility Breakout, Mean Reversion, Liquidation Cascade (açık pozisyon daralması proxy'si), Order Flow Momentum, Relative Strength ve mevcut SMC motoru. Android UserLAnd/Ubuntu ve Linux üzerinde kullanılabilir.

**Bu sürüm analiz aracıdır; otomatik al-sat yapmaz.** Borsaya emir veya pozisyon göndermez. Analiz için herkese açık piyasa verilerini kullanır. Bybit API anahtarı gerekmez.

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

## Kullanım

Atlas açıldığında komut alanına sembol veya desteklenen komutlardan birini yaz:

| Komut | İşlev |
|---|---|
| `BTC`, `ETH`, `SOL` | İlgili piyasayı 7 stratejiyle analiz eder; adayları karşılaştırıp tek plan seçer |
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

## 7 strateji analizi

Tek coin komutunda Atlas aynı kapanmış piyasa verisi üzerinde 6 yeni stratejiyi ve mevcut SMC kararını bağımsız değerlendirir. Her stratejinin giriş/stop/hedef geometrisi ayrı tutulur. Yeni motorların adayları yalnızca setup gücü puanıyla seçilmez: stratejiye özel, maliyet sonrası IS/OOS performansı, minimum örneklem ve expectancy güven sınırı doğrulanmadan SMC'nin önüne geçemez. Doğrulanmış deneysel edge yoksa SMC adayı varsa o gösterilir; SMC de yoksa seçilmiş plan üretilmez. Yeni motorların hedefleri yeterli swing likiditesi varsa yapısal seviyelerden, yoksa açıkça etiketlenmiş R-katı fallback ile hesaplanır.

**Önemli doğrulama sınırı:** 6 yeni strateji deneysel aday üreticilerdir. Strateji replay'i kronolojik IS/OOS ayrımı ve 5 anchored walk-forward penceresi kullanır; maliyetler ve tarihsel funding verisi mevcut olduğunda aynı yürütme simülatöründen geçirilir. Bunlar gerçek borsa dolumu değildir. Eksik veya kısmi OI/funding verisi açıkça raporlanır; funding geçmişi tam kapsama sahip değilse --persist performans günlüğüne sonuç yazmaz. Order Flow Momentum yalnızca karar zamanından önce arşivlenmiş, taze order-book/trade örnekleri varsa tarihsel olarak ölçülebilir. Liquidation Cascade gerçek likidasyon akışı değil, OI/funding/işlem akışı proxy'sidir. Hiçbir motorun kârlılığı kanıtlanmış değildir; terfi için aynı kod revizyonu/sembol/rejim altında minimum IS/OOS örneklemi, PF ve expectancy eşikleri geçilmelidir. Atlas emir göndermez.

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

## 7 strateji backtesti

Yedi motoru ayrı ayrı tarihsel replay ile ölçmek için:

```bash
python3 strategy_backtest.py --symbol BTC/USDT:USDT --days 30 --max-holding-bars 32 --limit-expiry-bars 8
```

Bu replay yalnızca kapanmış mumlarla karar verir; MARKET girişini sonraki 15m açılışında, LIMIT emrini en fazla 8 bar boyunca bekleterek doldurur. Gap-through LIMIT açılışta marketable limit olarak, sınırları içindeki yakın kaçırılmış LIMIT ise aynı kontrollü MARKET fallback kuralıyla ele alınır. Emir dolmadan hedef seviyesi aşılırsa kalan yapısal hedefler yeniden hesaplanır. Dolumdan sonra varsayılan maksimum tutma süresi 32 adet 15m bardır (8 saat); süre dolarsa pozisyon son kapanışta kapatılır. Kısmi TP ağırlıkları yapılandırılabilir; aynı mumda SL ve TP birlikte görülürse SL önce kabul edilir. Komisyon, spread, slippage ve mevcut tarihsel funding maliyeti net R'den düşülür.

Maliyet modeli ve IS/OOS kayıtlarını yerel performans günlüğüne yazmak için açıkça `--persist` ekle:

```bash
python3 strategy_backtest.py --symbol BTC/USDT:USDT --days 30 --persist
```

Performans kayıtları sembol, rejim ve kod revizyonuna göre ayrılır. Kod revizyonu değiştiğinde eski sonuçlar yeni sürümün seçiminde kullanılmaz. Minimum örneklem ve güven sınırı geçilmeden deneysel strateji seçime terfi etmez.

**Tarihsel veri sınırı:** OI ve funding geçmişi Bybit'in tarihsel uç noktalarından zaman damgasıyla alınır. Veri kapsaması HISTORICAL, PARTIAL veya UNAVAILABLE olarak raporlanır. Funding ödemeleri pozisyon yönüne göre modellenir; olumsuz debiler maliyete yazılır, olumlu krediler muhafazakâr biçimde kazanç sayılmaz. Kısmi funding geçmişiyle sonuç üretilebilir ancak bu sonuç strateji terfisi için kalıcı performans günlüğüne yazılmaz. Geçmiş order-book/taker-trade snapshot'ları geriye dönük üretilemez; Order Flow Momentum yalnızca yerel arşivde karar anından önce mevcut olan taze örneklerle ölçülür.


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

Yedi stratejinin tarihsel karşılaştırması:

```bash
python3 strategy_backtest.py --symbol BTC/USDT:USDT --days 30
```

- Rapor, 5 ardışık test pencereli anchored walk-forward sonuçlarını IS/OOS sonuçlarından ayrı gösterir.
- Bybit'in tarihsel OI ve funding uç noktaları destekleniyorsa zaman damgalı seriler yüklenir. Funding ödemesi pozisyon yönüne göre net R'ye yansıtılır.
- Funding geçmişi alınamazsa `--persist` sonuçları performans günlüğüne yazmaz. Eksik maliyetli örnekler strateji seçiminde kullanılamaz.
- Canlı order-book ve recent-trade örnekleri yerel olarak `data/microstructure/` altında JSONL arşivine kaydedilir.
- Relative Strength, BTC/ETH beta-adjusted residual alpha kullanır. İsteğe bağlı sektör/peer grubu `ATLAS_SECTOR_PEERS_JSON` ile tanımlanır; örnek: `{"SOL":["AVAX/USDT:USDT","ADA/USDT:USDT"]}`. Bilinmeyen coinlere otomatik sektör etiketi uydurulmaz.
- Order Flow Momentum, agresif alış/satış akışı fiyatı ilerletemediğinde ve karşı tarafta derinlik varsa absorption proxy üretir. Bu, gerçek kuyruk yenilenmesi veya gizli emir kanıtı değildir. Kapatmak için `ATLAS_MICROSTRUCTURE_ARCHIVE_ENABLED=0` ayarlayın.
- Geçmiş order-book verisi geriye dönük üretilemez. Order-flow replay yalnızca karar zamanından önce arşivlenmiş ve tazeliği doğrulanmış örnekleri kullanır. Arşiv oluşana kadar bu motorun tarihsel performansı ölçülmüş sayılmaz.
- Arşiv her sembol için varsayılan 5 MiB ve 7 gün ile sınırlandırılır. İhtiyaca göre ATLAS_MICROSTRUCTURE_ARCHIVE_MAX_BYTES ve ATLAS_MICROSTRUCTURE_ARCHIVE_RETENTION_DAYS ayarlanabilir.
- Liquidation Cascade, gerçek liquidation-event akışı değildir; tarihsel OI/funding ve varsa arşivlenmiş trade-flow ile sınırlı bir proxy'dir.

Komisyon, spread ve slippage hâlâ parametreli yürütme varsayımlarıdır; gerçek emir gerçekleşme fiyatı değildir. Walk-forward çıktısı kârlılık garantisi veya parametre optimizasyonu anlamına gelmez.
