# Atlas

**Atlas, kripto piyasalarını Smart Money Concepts (SMC) yaklaşımıyla analiz eden, Android UserLAnd/Ubuntu ve Linux terminalinde çalışan bir analiz aracıdır.** Tek ekranlı terminal arayüzünde coin analizi ve piyasa taraması yapar; uygun kurulumlarda LONG/SHORT yönü, MARKET/LIMIT giriş türü, giriş, stop-loss ve TP seviyelerini gösterir.

Atlas **otomatik al-sat botu değildir**: borsaya emir göndermez, pozisyon açmaz ve API işlem anahtarı istemez. Analiz ve backtest için herkese açık piyasa verilerini kullanır. İşlem kararını ve emir uygulamasını kullanıcı yapar.

## İçindekiler

- [Özellikler](#özellikler)
- [Gereksinimler](#gereksinimler)
- [Sıfırdan kurulum](#sıfırdan-kurulum)
- [Atlas'ı başlatma](#atlası-başlatma)
- [Kullanım komutları](#kullanım-komutları)
- [Backtest](#backtest)
- [Testleri çalıştırma](#testleri-çalıştırma)
- [Güncelleme](#güncelleme)
- [Sorun giderme](#sorun-giderme)
- [Güvenlik ve risk](#güvenlik-ve-risk)

## Özellikler

- Haftalık, günlük, 4 saatlik ve alt zaman dilimlerinde çoklu zaman dilimi analizi
- SMC piyasa yapısı: BOS/CHoCH, likidite, EQH/EQL, FVG, Order Block ve OTE
- Trend, piyasa rejimi ve farklı analiz motorlarından gelen kanıtların birlikte değerlendirilmesi
- Bybit herkese açık mum, emir defteri ve son gerçekleşen işlemler verisi
- LONG/SHORT yönü ile MARKET/LIMIT giriş planı
- Yapısal stop-loss, TP1/TP2/TP3 ve risk/ödül hesaplaması
- Yerel terminal arayüzü ve yerel işlem/sinyal kayıtları

Analiz puanı kazanma olasılığı değildir. Her analiz işlem sinyali üretmez; geçerli kurulum bulunamazsa Atlas bunu belirtir.

## Gereksinimler

- Android üzerinde UserLAnd ve Ubuntu **veya** Linux terminali
- Python 3 ve `venv` modülü
- Git
- Paket kurulumu ve piyasa verisi için internet bağlantısı

Kurulum örnekleri Ubuntu içindir.

## Sıfırdan kurulum

### 1. Ubuntu paketlerini yükle

UserLAnd içindeki Ubuntu terminalini aç ve çalıştır:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip build-essential
```

UserLAnd oturumunda `sudo` kullanılamıyorsa komutları `sudo` olmadan çalıştır.

### 2. Atlas deposunu indir

```bash
cd ~
git clone https://github.com/12baro1/Atlas.git
cd Atlas
```

Komut sonunda `~/Atlas` klasöründe olmalısın.

### 3. Python sanal ortamını oluştur

```bash
python3 -m venv venv
source venv/bin/activate
```

Sanal ortam açıldığında terminal satırının başında `(venv)` görünür. Her yeni terminal oturumunda Atlas'ı çalıştırmadan önce bu ortamı etkinleştirmen gerekir:

```bash
cd ~/Atlas
source venv/bin/activate
```

> Önemli: Projedeki `atlas` başlatıcısı varsayılan olarak `venv/bin/python` yolunu kullanır. Bu nedenle sanal ortamı README'deki gibi `venv` adıyla oluştur.

### 4. Python paketlerini yükle

Sanal ortam etkinken:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Kurulum tamamlanana kadar terminali kapatma.

### 5. Atlas komutunu kur

```bash
python3 atlas_app.py --install-cli
source ~/.bashrc
```

Kurulumu kontrol et:

```bash
which atlas
```

Komut bir `~/.local/bin/atlas` yolu göstermelidir.

## Atlas'ı başlatma

Her yeni terminal oturumunda:

```bash
cd ~/Atlas
source venv/bin/activate
atlas
```

Komut kurulumu yapılmadıysa veya `atlas: command not found` hatası alırsan proje klasöründen doğrudan çalıştır:

```bash
cd ~/Atlas
source venv/bin/activate
./atlas
```

Alternatif olarak:

```bash
python atlas_app.py
```

Bir coini açılışta doğrudan analiz etmek için:

```bash
atlas BTC
atlas ETH
```

## Kullanım komutları

Atlas açıldığında alttaki komut alanına yaz ve Enter'a bas.

| Komut | Açıklama |
|---|---|
| `BTC`, `ETH`, `SOL`, `BRC` | Girilen coinin USDT perpetual piyasasını analiz eder |
| `BTC/USDT:USDT` | Tam sembol ile analiz yapar |
| `işlem ver` | Hacme göre seçilen 30 piyasayı tarar, en iyi 1 kurulumu gösterir |
| `50 analiz et` | 50 piyasayı tarar, en iyi 5 kurulumu gösterir |
| `100 tara` | 100 piyasayı tarar, en iyi 5 kurulumu gösterir |
| `en iyi 5 işlem` | 100 piyasayı tarar, en iyi 5 kurulumu gösterir |
| `tüm piyasayı tara` | Uygun tüm USDT perpetual piyasalarını tarar; uzun sürebilir |
| `likidite BTC` | BTC için BSL/SSL, EQH/EQL ve likidite süpürmesi bilgisini gösterir |
| `performans` | Otomatik sinyal sonuçları ile manuel işlem kayıtlarını ayrı gösterir |
| `öğrenme` | Geçmiş işlem öğrenme verisini gösterir |
| `yardım` | Kullanılabilir komutları gösterir |
| `çıkış` | Atlas'ı kapatır |

Sayısal tarama komutları en fazla 500 piyasa ile sınırlandırılır. Tarama süresi internet bağlantısına ve borsa yanıtlarına göre değişir. Atlas geçerli kurulum bulamazsa zorla sinyal üretmez.

## Backtest

Backtest, Bybit'ten tarihsel OHLCV verisi alır ve sinyal/pozisyon sonuçlarını simüle eder. Sanal ortam etkinken proje klasöründe çalıştır.

Tek coin, 30 gün:

```bash
python3 backtest.py --symbol BTC/USDT:USDT --days 30
```

BTC ve ETH, 30 gün:

```bash
python3 backtest.py --symbols "BTC/USDT:USDT,ETH/USDT:USDT" --days 30
```

Tek coin, 7 gün:

```bash
python3 backtest.py --symbol BTC/USDT:USDT --days 7
```

Backtest giriş zaman dilimi şu anda 15 dakikadır. İsteğe bağlı parametreler:

- `--days`: Test edilecek gün sayısı.
- `--symbols`: Virgülle ayrılmış birden fazla perpetual sembol.
- `--symbol`: Tek perpetual sembol.
- `--limit-expiry-bars`: LIMIT emrinin bekleyeceği 15 dakikalık mum sayısı.
- `--lenient`: EXECUTE karar kapısını atlayarak ham sinyalleri teşhis amacıyla ölçer; normal işlem modu değildir.

Backtest geçmiş veriyi indirirken uzun sürebilir. Raporu değerlendirirken kapanan işlem sayısı, Net RR, işlem başına beklenti, Profit Factor, Max Drawdown ve LONG/SHORT sonuçlarını birlikte incele. Az sayıda işlemden kârlılık sonucu çıkarma. Geçmiş performans gelecekteki sonucu garanti etmez.

## Testleri çalıştırma

Test bağımlılığı kurulu değilse önce:

```bash
python -m pip install pytest
```

Ardından:

```bash
python -m pytest -q
```

## Güncelleme

Yeni sürümü indirmek için:

```bash
cd ~/Atlas
git pull --ff-only origin main
source venv/bin/activate
python -m pip install -r requirements.txt
```

Güncellemeden sonra başlat:

```bash
atlas
```

Yerel kodda kendi değişikliklerin varsa güncellemeden önce bunları commit et veya yedekle. Git, çakışan yerel değişiklikleri otomatik olarak güvenli biçimde birleştiremeyebilir.

## Sorun giderme

**`atlas: command not found`**

```bash
cd ~/Atlas
source venv/bin/activate
python3 atlas_app.py --install-cli
source ~/.bashrc
which atlas
```

**`No module named ...`**

Sanal ortamın açık olduğundan emin ol ve bağımlılıkları tekrar yükle:

```bash
cd ~/Atlas
source venv/bin/activate
python -m pip install -r requirements.txt
```

**`python3 -m venv` çalışmıyor**

```bash
sudo apt update
sudo apt install -y python3-venv
```

**Bybit veri bağlantısı başarısız**

İnternet bağlantısını kontrol et ve tekrar dene. Backtest, Bybit tarihsel veri isteği coğrafi erişim engeline takılırsa OHLCV geçmişi için Binance USD-M Futures yedeğini deneyebilir; raporda kullanılan veri sağlayıcısı yazdırılır. Canlı terminal analizinin veri kaynağı Bybit'tir.

## Güvenlik ve risk

- Atlas'ın analiz ve backtest akışı için Bybit API anahtarı veya işlem yetkisi gerekmez.
- Atlas borsaya emir göndermez; otomatik pozisyon açma kapalıdır.
- Gerçek API anahtarı, parola veya gizli bilgileri GitHub deposuna ekleme.
- Emir defteri ve son gerçekleşen işlem verileri anlık/sınırlı örneklerdir; tüm piyasa akışını temsil etmez.
- Sinyaller hatalı olabilir; komisyon, spread, kayma ve likidite gerçek sonucu etkiler.
- Önce demo ortamında doğrula. Kaldıraçlı işlemlerde sermayenin tamamı kaybedilebilir.

Atlas eğitim ve piyasa analizi amacıyla geliştirilmiştir; yatırım tavsiyesi değildir.
