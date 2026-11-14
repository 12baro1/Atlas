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

**Önemli doğrulama sınırı:** 6 yeni strateji deneysel aday üreticilerdir. Strateji bazlı kalıcı sonuç günlüğü ve tek kronolojik IS/OOS replay eklendi; ancak tam walk-forward test matrisi, gerçek fill verisi ve her stratejinin tüm gerekli tarihsel veri kaynakları henüz tamamlanmadı. Bu nedenle yalnızca replay'de gerçekten ölçülebilen motorlar, aynı kod revizyonu/sembol/rejim için yeterli IS/OOS örneklemi ve güven sınırı geçerse seçime terfi edebilir. `strategy_performance.py` eksik performans verisinde kapalı-kapı (fail-closed) davranır. Strateji bazında aynı-veri backtesti, komisyon/spread/slippage/funding modellemesi ve out-of-sample örneklem tamamlanmadan kârlılık veya geçmiş performans üstünlüğü iddia edilmez. Liquidation Cascade motoru gerçek likidasyon akışı yerine açık pozisyon (OI) daralmasını ve işlem akışını proxy olarak kullanır; gerçek likidasyon verisi olarak yorumlanmamalıdır. Atlas emir göndermez.

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
python3 strategy_backtest.py --symbol BTC/USDT:USDT --days 30
```

Bu replay yalnızca kapanmış mumlarla karar verir; MARKET girişini sonraki 15m mum açılışında, LIMIT girişini fiyat gerçekten limit seviyesine dokunursa doldurur. Aynı mumda SL ve TP birlikte görülürse SL önce kabul edilir. Komisyon, spread ve slippage varsayımları net R'den düşülür.

Maliyet modeli ve IS/OOS kayıtlarını yerel performans günlüğüne yazmak için açıkça `--persist` ekle:

```bash
python3 strategy_backtest.py --symbol BTC/USDT:USDT --days 30 --persist
```

Performans kayıtları sembol, rejim ve kod revizyonuna göre ayrılır. Kod revizyonu değiştiğinde eski sonuçlar yeni sürümün seçiminde kullanılmaz. Minimum örneklem ve güven sınırı geçilmeden deneysel strateji seçime terfi etmez.

**Tarihsel veri sınırı:** Bybit OHLCV arşivinde geçmiş order-book/taker-trade snapshot'ı bulunmadığı için Order Flow Momentum motoru bu replay'de ölçülmez. Aynı şekilde geçmiş OI/funding serileri bu replay'e henüz bağlanmadığından Liquidation Cascade motoru ölçülmez. Bu iki motor için "işlem yok" sonucu başarısız strateji anlamına gelmez; gerekli tarihsel veri mevcut değildir. Funding maliyeti de replay'de henüz modellenmez. Maliyet varsayımları gerçek dolum garantisi değildir.

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

## Güvenlik

- Analiz için borsa API anahtarı girme; Atlas'ın normal kullanımında gerekmez.
- Gerçek API anahtarı, parola veya kişisel erişim bilgilerini depoya yükleme.
- Sinyaller yatırım tavsiyesi değildir ve kâr garantisi vermez.
- Önce demo ortamında doğrula. Kaldıraçlı işlemlerde sermayenin tamamı kaybedilebilir.
