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
