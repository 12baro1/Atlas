# Atlas

Atlas, Bybit swap piyasasindan veri cekip coklu zaman dilimi analiz yapan bir SMC islem motorudur.

## Kurulum

1. `ccxt` paketini kur:

```bash
python3 -m pip install ccxt
```

2. Proje kokune `.env` dosyasi olustur (Bybit API key + Telegram ayarlari):

```env
ATLAS_BYBIT_API_KEY=BURAYA_KEY
ATLAS_BYBIT_API_SECRET=BURAYA_SECRET
ATLAS_BYBIT_TESTNET=1
ATLAS_BYBIT_DEMO_TRADING=1
ATLAS_TELEGRAM_BOT_TOKEN=BURAYA_TOKEN
ATLAS_TELEGRAM_CHAT_ID=BURAYA_CHAT_ID
```

## Calistirma

```bash
python3 main.py
```

Sembol sayisini sinirlamak icin:

```bash
ATLAS_MAX_SYMBOLS=50 python3 main.py
```

Statik katalo (web) icin:

```bash
ATLAS_SCAN_INTERVAL_SECONDS=900 python3 main.py   # her 15 dk da tekrar tara
```

## Surekli izleme

```bash
./run_bot.sh start      # arka planda calistir, crash'te otomatik restart
./run_bot.sh status     # calisiyor mu?
./run_bot.sh logs -f    # canli loglar
./run_bot.sh restart
./run_bot.sh stop
```

Ayarlar:
```bash
ATLAS_SCAN_INTERVAL_SECONDS=900 ./run_bot.sh start   # tarama arasi (sn)
ATLAS_MAX_SYMBOLS=50 ./run_bot.sh start              # sembol sayisi
RESTART_DELAY=10 ./run_bot.sh start                  # crash sonrasi bekleme (sn)
```

## Raporlar

```bash
python3 report.py            # winrate, beklenti, profit factor, TP/SL
python3 report.py --detail   # tek tek sinyal sonuclari
```

## Backtest

```bash
python3 backtest.py --symbol SOL/USDT:USDT --days 90
python3 backtest.py --symbols SOL/USDT:USDT,DYDX/USDT:USDT --days 60
python3 backtest.py --symbols ... --lenient   # karar kapisi olmadan
```

## Telegram komutlari

Bota bağlı Telegram tarafinda:

- `/start` — kimlik dogrulama (ilk kullanim)
- `/trade open <signal_id> [entry] [stop] [tp]` — islemi kaydet
- `/trade close <signal_id> [exit] [WIN|LOSS|BREAKEVEN]` — islemi kapat
- `/trade performance` — performans ozeti
- `/trade help` — kullanim rehberi

## Guvenlik

- API key/secret degerlerini kod icine yazma; sadece `.env` veya shell env kullan.
- Testnet key kullanicaksan `ATLAS_BYBIT_TESTNET=1`, demo icin `ATLAS_BYBIT_DEMO_TRADING=1` kullan.