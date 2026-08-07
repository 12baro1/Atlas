# Atlas

Atlas, Bybit swap piyasasindan veri cekip coklu zaman dilimi analiz yapan bir SMC islem motorudur.

## Bybit Demo Auto Trading

Otomatik emir acma/kapama ozelligi env degiskenleri ile calisir.

1. `ccxt` paketini kur:

```bash
python3 -m pip install ccxt
```

1. Proje kokune `.env` dosyasi olustur:

```env
ATLAS_CCXT_MODE=real
ATLAS_BYBIT_TESTNET=0
ATLAS_BYBIT_DEMO_TRADING=1
ATLAS_AUTO_TRADING_ENABLED=1
ATLAS_AUTO_TRADING_AUTO_ENABLE_WITH_KEYS=1
ATLAS_AUTO_TRADING_MIN_CONFIDENCE=85
ATLAS_AUTO_TRADING_ALLOW_EXECUTE_WITH_CAUTION=0
ATLAS_AUTO_TRADING_MIN_LEVERAGE=1
ATLAS_AUTO_TRADING_MAX_LEVERAGE=20
ATLAS_BYBIT_API_KEY=BURAYA_KEY
ATLAS_BYBIT_API_SECRET=BURAYA_SECRET
ATLAS_BYBIT_POSITION_MODE=one_way
ATLAS_BYBIT_LOG_HTTP=0
ATLAS_REJECT_TIGHT_STOPS=1
```

1. Tarayiciyi calistir:

```bash
python3 main.py
```

## Guvenlik

- API key/secret degerlerini kod icine yazma; sadece `.env` veya shell env kullan.
- Bybit Demo Trading hesabi kullanirken `ATLAS_BYBIT_DEMO_TRADING=1` yap; demo hesap testnet/sandbox degildir.
- Testnet API key kullanacaksan `ATLAS_BYBIT_DEMO_TRADING=0` ve `ATLAS_BYBIT_TESTNET=1` kullan.
- Gercek hesapta calismak icin `ATLAS_BYBIT_DEMO_TRADING=0` ve `ATLAS_BYBIT_TESTNET=0` yapmadan once kucuk miktarla test et.

## Telegram Kalite Filtresi

Gercek para ile Telegram sinyalini gorup manuel isleme gireceksen, Atlas artik Telegram'a dusen sinyalleri ayrica kalite kapisindan gecirir. Bu filtre kar garantisi vermez; amaci dusuk grade, dusuk RR veya karar motoru onayi olmayan setup'lari Telegram'a hic gondermeyerek daha secici davranmaktir.

Varsayilan korumalar:

```env
ATLAS_TELEGRAM_MIN_CONFIDENCE=85
ATLAS_TELEGRAM_REQUIRE_DECISION_ACTION=1
ATLAS_TELEGRAM_QUALITY_FILTERS_ENABLED=1
ATLAS_TELEGRAM_MIN_GRADE=A
ATLAS_TELEGRAM_MIN_RR=3.0
ATLAS_TELEGRAM_ALLOW_CAUTION_SIGNALS=0
ATLAS_TELEGRAM_MIN_CONFLUENCE_SCORE=70
ATLAS_TELEGRAM_REQUIRE_MTF_ALIGNMENT=1
ATLAS_TELEGRAM_ALLOWED_MARKET_PHASES=Expansion,Trending,Reversal
```

- `ATLAS_TELEGRAM_MIN_CONFIDENCE`: Telegram'a dusmesi icin minimum guven puani.
- `ATLAS_TELEGRAM_MIN_GRADE`: Minimum sinyal kalitesi; gercek kullanim icin `A` veya `A+` onerilir.
- `ATLAS_TELEGRAM_MIN_RR`: Minimum risk/odul. Varsayilan 3R altini gondermez.
- `ATLAS_TELEGRAM_MIN_CONFLUENCE_SCORE`: SMC stack puani dusukse Telegram'a bildirim gitmez.
- `ATLAS_TELEGRAM_REQUIRE_DECISION_ACTION`: Karar motoru isleme izin vermediyse Telegram bildirimi gitmez.
- `ATLAS_TELEGRAM_ALLOW_CAUTION_SIGNALS`: `0` iken sadece net `EXECUTE` sinyalleri gider; `EXECUTE_WITH_CAUTION` filtrelenir.
- `ATLAS_TELEGRAM_REQUIRE_MTF_ALIGNMENT`: Ust zaman dilimi ve giris yonu uyumsuzsa sinyali engeller.
- `ATLAS_TELEGRAM_ALLOWED_MARKET_PHASES`: Sadece listelenen piyasa fazlarinda Telegram sinyali uretir.

Onemli: Sinyal gelse bile islem oncesi haber, ani volatilite, likidite ve pozisyon buyuklugunu kontrol et. Hicbir filtre kar garantisi vermez; gercek hesapta once kucuk miktar veya demo ile dogrula.

## Manual Trade Score ve Geri Bildirim

Telegram filtresi artik sinyal kalitesini tek bir `Manual Score` ile ozetler. Bu skor confidence, confluence, RR, decision, risk, market phase ve varsa gecmis performans bilgisini birlestirir.

Ek ayarlar:

```env
ATLAS_TELEGRAM_MIN_MANUAL_SCORE=75
ATLAS_TELEGRAM_HISTORICAL_MIN_TRADES=20
ATLAS_TELEGRAM_HISTORICAL_MIN_EXPECTANCY=0.30
ATLAS_TELEGRAM_HISTORICAL_MIN_PROFIT_FACTOR=1.30
ATLAS_TELEGRAM_HISTORICAL_STRICT=0
```

- `ATLAS_TELEGRAM_MIN_MANUAL_SCORE`: Telegram'a dusmesi icin minimum manuel islem skoru.
- `ATLAS_TELEGRAM_HISTORICAL_MIN_TRADES`: Gecmis performans filtresinin guvenilir saymasi icin minimum kapali islem sayisi.
- `ATLAS_TELEGRAM_HISTORICAL_MIN_EXPECTANCY`: Benzer setup'larda istenen minimum ortalama R.
- `ATLAS_TELEGRAM_HISTORICAL_MIN_PROFIT_FACTOR`: Benzer setup'larda istenen minimum profit factor.
- `ATLAS_TELEGRAM_HISTORICAL_STRICT`: `1` yapilirsa yeterli gecmis veri yokken sinyal engellenir; `0` iken sadece uyari olarak gosterilir.

Telegram mesajlarina manuel takip butonlari da eklenir: `Girdim`, `Girmedim`, `TP`, `SL`, `Erken ciktim`. Bu callback'leri gercek trade sonucuna baglamak sonraki gelistirme adiminda Atlas'in senin manuel performansindan daha hizli ogrenmesini saglar.

---

## Canli Izleme (Sinyal Sonuc Takibi + Süpervizör)

Sistem her EXECUTE sinyalini kalici `atlas_journal.db`'ye kaydeder, mumlar ilerledikçe SL/TP vuruşuyla WIN/LOSS çözer ve `report.py` ile ölçer.

### Tek seferlik tarama
```bash
ATLAS_MAX_SYMBOLS=50 python3 main.py
```

### Sürekli izleme (crash'e karsi otomatik restart)
```bash
./run_bot.sh start                     # arka planda, 900s arayla, max 100 sembol
./run_bot.sh status                    # calisiyor mu?
./run_bot.sh logs -f                   # canli loglar
./run_bot.sh restart
./run_bot.sh stop
```

Ayarlar:
```bash
ATLAS_SCAN_INTERVAL_SECONDS=900 ./run_bot.sh start   # tarama arasi (sn)
ATLAS_MAX_SYMBOLS=50 ./run_bot.sh start              # sembol sayisi
RESTART_DELAY=10 ./run_bot.sh start                  # crash sonrasi bekleme (sn)
```

### Canli performans raporu
```bash
python3 report.py            # winrate, beklenti, profit factor, TP/SL
python3 report.py --detail   # tek tek sinyal sonuclari
```

### Backtest (edge dogrulama)
```bash
python3 backtest.py --symbol SOL/USDT:USDT --days 90
python3 backtest.py --symbols SOL/USDT:USDT,DYDX/USDT:USDT --days 60
python3 backtest.py --symbols ... --lenient   # karar kapisi olmadan
```
