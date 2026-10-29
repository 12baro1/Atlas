# Atlas

Atlas, kripto perpetual piyasalarını analiz eden SMC tabanlı sinyal motorudur. Varsayılan kullanım analiz + terminal sonucu + isteğe bağlı Telegram bildirimi şeklindedir. Borsa emir yürütmesi kod seviyesinde kapalıdır.

## 1. Android / UserLAnd kurulumu

Proje klasöründe:

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
cp .env.example .env
nano .env
```

`.env` içinde yalnızca kendi Telegram bot token'ını ve chat ID'ni yerel olarak doldur. Borsa API key/secret ekleme. Gerçek kimlik bilgilerini GitHub'a yükleme.

## 2. Çalıştırma

```bash
python3 atlas_app.py --install-cli
source ~/.bashrc
atlas
```

`atlas` varsayılan olarak BTC için analizi başlatır ve sonucu terminal arayüzünde gösterir. Başka bir sembol:

```bash
atlas ETH
atlas SOL/USDT:USDT
```

İlk analiz sembolünü değiştirmek için `.env` içinde:

```env
ATLAS_DEFAULT_SYMBOL=ETH
```

Tüm sembolleri sürekli tarama yalnızca açıkça istendiğinde:

```bash
atlas --full-scan
```

## 3. Arka planda çalışma

```bash
atlas --background
atlas --status
atlas --logs
atlas --restart
atlas --stop
```

Arka plan tarama aralığı ve sembol sınırı:

```bash
ATLAS_SCAN_INTERVAL_SECONDS=900 atlas --background
ATLAS_MAX_SYMBOLS=50 atlas --full-scan
```

## 4. Backtest ve rapor

```bash
python3 backtest.py --symbol BTC/USDT:USDT --days 90
python3 backtest.py --symbols BTC/USDT:USDT,ETH/USDT:USDT --days 90
python3 report.py
python3 report.py --detail
python3 -m pytest -q
```

Backtest sonuçları gelecekteki kârı garanti etmez. Komisyon, kayma, kapanmış mum kullanımı ve ayrı test dönemi doğrulanmadan gerçek sermayeyle işlem yapılmamalıdır.

## 5. Telegram manuel işlem günlüğü

```
/start
/trade help
/trade performance
```

Sinyal ve manuel işlem sonuçları farklı kaynaklar olarak tutulur. Yeterli örnek oluşana kadar öğrenme katmanının performansı kanıtladığı varsayılmaz.

## Güvenlik

- Atlas borsaya otomatik emir göndermez; bu güvenlik kilidi environment değişkenleriyle açılamaz.
- Daha önce repoda bulunan `.env` dosyasındaki gerçek bilgiler ifşa edilmiş kabul edilmeli; eski token/key'leri iptal edip yenilerini yerel ortamda kullan.
- `.env` dosyasını, veritabanlarını ve logları Git'e ekleme.
- `atlas --full-scan` çok sayıda sembol tarar; varsayılan `atlas` yalnızca seçili tek sembolle başlar.
