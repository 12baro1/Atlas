# Atlas

**Atlas, kripto piyasalarını Smart Money Concepts (SMC) yaklaşımıyla analiz eden, Android üzerinde terminalden çalışan bir işlem analiz aracıdır.**

Atlas; piyasa yapısını, likiditeyi, FVG ve OTE bölgelerini, çoklu zaman dilimi uyumunu, risk/ödül oranını ve Bybit emir defteri verisini birlikte değerlendirerek işlem kurulumu arar. Uygun koşullar oluştuğunda LONG veya SHORT yönünde giriş planı üretir.

Atlas bir borsa işlem botu değildir. **Borsaya emir göndermez, Telegram kullanmaz ve sohbet amaçlı yapay zekâ çalıştırmaz.** Piyasa verilerini analiz eder; işlem kararını ve uygulamasını kullanıcıya bırakır.

## Özellikler

- Çoklu zaman dilimi piyasa ve trend analizi
- SMC tabanlı yapı, BOS/CHoCH, likidite süpürmesi, EQH/EQL, FVG ve OTE değerlendirmesi
- Bybit herkese açık emir defterinden anlık likidite kontrolü
- LONG/SHORT yönü, MARKET/LIMIT giriş türü, giriş, stop-loss ve kâr-al seviyeleri
- Risk/ödül ve işlem kalitesi kontrolleri
- Manuel işlem günlüğü ve geçmiş sonuç özeti
- Terminal üzerinden tek ekranlı kullanım

> Atlas'ın puanları kazanma olasılığı değildir. Hiçbir sinyal kâr garantisi vermez. Emir defteri anlık görüntüdür; gerçekleşmiş alım-satım akışını tek başına göstermez.

## Kurulum

Aşağıdaki adımlar Android üzerinde **UserLAnd + Ubuntu** içindir. Kurulum için internet bağlantısı ve terminal erişimi gerekir.

### 1. Gerekli paketleri yükle

UserLAnd içinde Ubuntu oturumunu aç ve çalıştır:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip build-essential
```

UserLAnd oturumunda `sudo` kullanılamıyorsa aynı komutları `sudo` olmadan çalıştır.

### 2. Depoyu indir

```bash
cd ~
git clone https://github.com/12baro1/Atlas.git
cd Atlas
```

Depo daha önce indirilmişse yeniden klonlamak yerine:

```bash
cd ~/Atlas
git pull origin main
```

### 3. Python sanal ortamını oluştur ve etkinleştir

```bash
python3 -m venv venv
source venv/bin/activate
```

Terminal satırının başında `(venv)` görünmesi sanal ortamın etkin olduğunu gösterir.

### 4. Python bağımlılıklarını yükle

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 5. Atlas komutunu kur

```bash
python3 atlas_app.py --install-cli
source ~/.bashrc
```

Kurulumu doğrula:

```bash
which atlas
```

### 6. Atlas'ı başlat

```bash
atlas
```

Komut bulunamazsa veya PATH henüz yenilenmediyse proje klasöründe şu komutla doğrudan başlatabilirsin:

```bash
cd ~/Atlas
source venv/bin/activate
python atlas_app.py
```

## Kullanım

Atlas açıldığında tek ekranlı terminal arayüzündeki komut alanına sembol veya komut yaz:

| Komut | İşlev |
|---|---|
| `BTC`, `ETH`, `SOL` | İlgili USDT perpetual piyasasını analiz eder |
| `BRC` | BRC/USDT perpetual piyasasını analiz eder |
| `işlem ver` | Hacmi yüksek ilk beş uygun USDT perpetual piyasada geçerli kurulum arar |
| `likidite BTC` | BTC için BSL/SSL, EQH/EQL ve son likidite süpürmesini gösterir |
| `performans` | Otomatik sinyal sonuçları ile manuel işlem kayıtlarını ayrı gösterir |
| `öğrenme` | Manuel işlem geçmişindeki setup eşleşmelerini özetler |
| `yardım` | Kullanılabilir komutları gösterir |
| `çıkış` | Atlas'ı kapatır |

Atlas'ı belirli bir coin ile doğrudan açmak da mümkündür:

```bash
atlas BTC
atlas ETH
```

`işlem ver` komutu tüm piyasayı taramaz; hacme göre seçilmiş ilk beş piyasayla sınırlıdır. Geçerli koşulları sağlayan kurulum bulunmazsa Atlas zorla işlem üretmez.

## Test ve backtest

Sanal ortam açıkken proje klasöründe:

```bash
python -m pytest -q
python backtest.py --symbol BTC/USDT:USDT --days 90
```

Backtest sonuçları kullanılan veri aralığına ve varsayımlara bağlıdır. Gerçek işlem öncesinde komisyon, kayma, örneklem büyüklüğü ve maksimum düşüş ayrıca değerlendirilmelidir.

## Veri ve güvenlik

- Piyasa verisi Bybit'in herkese açık piyasa verisi arayüzünden alınır.
- Mum ve emir defteri verisi için borsa API anahtarı gerekmez.
- Atlas borsaya emir göndermez; otomatik işlem yürütmez.
- Telegram bildirimi ve sohbet amaçlı yapay zekâ ürün akışının parçası değildir.
- Analiz için internet bağlantısı gerekir.
- İşlem kararı, pozisyon büyüklüğü ve emir uygulaması kullanıcı sorumluluğundadır.

## Sorumluluk reddi

Atlas eğitim ve piyasa analizi amacıyla geliştirilmiştir; yatırım tavsiyesi değildir. Sinyaller hatalı olabilir, stop-loss çalışması kayma yaşayabilir ve sermaye kaybı oluşabilir. Önce demo ortamında test et; geçmiş test sonuçlarını gelecekteki performans garantisi olarak değerlendirme.
