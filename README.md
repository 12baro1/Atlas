# Atlas

Atlas, SMC tabanlı kripto piyasası analiz aracıdır. Kullanımı tek bir terminal ekranına indirgenmiştir. **Yapay zekâ sohbeti yok, Telegram bildirimi yok, borsaya emir gönderme yok.**

## Android / UserLAnd kurulumu

Proje klasöründe:

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 atlas_app.py --install-cli
source ~/.bashrc
```

## Telefon ekranından uygulama gibi kullanma

Atlas'ın Python analiz motoru UserLAnd içinde çalışır; mobil arayüz Android tarayıcısında açılır. Proje klasöründe:

```bash
python3 atlas_mobile.py
```

Aynı telefonda Chrome'u açıp `http://127.0.0.1:8765` adresine gir. Chrome menüsünden **Ana ekrana ekle** seçeneğini kullanarak Atlas'ı uygulama simgesi gibi açabilirsin. Analiz motorunun çalışması için UserLAnd'deki terminal süreci açık kalmalıdır. Durdurmak için terminalde `Ctrl+C`.

Bu yerel arayüz yalnızca `127.0.0.1` adresine bağlanır; başka cihazlardan erişime açılmaz. Bu yöntem APK değildir, ancak ana ekrandan açılan mobil uygulama deneyimi sağlar.

## Terminal kullanımı

```bash
atlas
```

Tek bir terminal ekranı açılır. Alt kısımdaki komut alanına coin veya komut yazıp Enter'a bas.

- `BRC` — BRC/USDT perpetual piyasasını analiz eder.
- `BTC`, `ETH`, `SOL` — seçilen coin'i analiz eder.
- `işlem ver` — hacmi yüksek ilk beş USDT perpetual piyasasını analiz eder ve Atlas'ın geçerli işlem koşullarını geçen en güçlü kurulumu ekranda gösterir.
- `yardım` — komutları gösterir.
- `çıkış` — uygulamayı kapatır.

İstersen doğrudan sembolle de açabilirsin:

```bash
atlas BRC
atlas ETH
```

## İşlem seçimi nasıl çalışır?

`işlem ver` komutu hacme göre ilk beş uygun piyasayı tarar. Yalnızca karar motorunun `EXECUTE` olarak onayladığı, LONG/SHORT yönü ve geçerli giriş/stop/RR bilgileri bulunan kurulumlar aday kabul edilir. Aday yoksa Atlas işlem uydurmak yerine beklemeyi söyler.

Bu tarama tüm coinleri kapsamlı biçimde taramaz; ilk beş yüksek hacimli piyasayla sınırlıdır. Sıralama puanı kazanma olasılığı değildir ve kâr garantisi vermez.

## Güvenlik ve veri

- Atlas borsaya emir göndermez; yalnızca analiz yapar.
- Telegram bildirimleri ve Telegram servis başlangıcı kapalıdır.
- Sohbet modeli/AI başlatılmaz veya analiz için kullanılmaz.
- Piyasa mumları herkese açık borsa piyasa verisinden alınır; borsa alım-satım API anahtarı gerekmez.
- Canlı piyasa verisi için internet bağlantısı gerekir.
- Analiz koşulları oluşmazsa sonuç BEKLE/ATLA olabilir. Zorla sinyal üretmez.

## Test ve backtest

```bash
python3 -m pytest -q
python3 backtest.py --symbol BTC/USDT:USDT --days 90
```

Testlerin geçmesi kârlılık kanıtı değildir. Gerçek sermayeden önce komisyon, kayma, drawdown ve ayrı test dönemlerini değerlendir.
