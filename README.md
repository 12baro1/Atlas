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

## Kullanım

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

## Performans ve öğrenme\n\nTerminalde `performans` komutu otomatik sinyal sonuçlarını (teorik) ve manuel işlem kayıtlarını (kullanıcının gerçek işlemleri) ayrı gösterir. `öğrenme` komutu geçmiş manuel işlem örnekleminin setup eşleşme özetini verir. 20 kapanan işlemden az örneklemde geçmiş performansın güvenilir olmadığı açıkça belirtilir. `likidite BTC` komutu seçilen sembolün BSL/SSL, EQH/EQL kümelerini ve son likidite süpürmesini gösterir.\n\n## Test ve backtest

```bash
python3 -m pytest -q
python3 backtest.py --symbol BTC/USDT:USDT --days 90
```

Testlerin geçmesi kârlılık kanıtı değildir. Gerçek sermayeden önce komisyon, kayma, drawdown ve ayrı test dönemlerini değerlendir.
