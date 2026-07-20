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
ATLAS_BYBIT_TESTNET=1
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
- Demo disinda calismak icin `ATLAS_BYBIT_TESTNET=0` yapmadan once kucuk miktarla test et.
