# ATLAS — GÜNCEL MÜHENDİSLİK DURUMU

Tarih: 30.10.2026
Durum: **Mühendislik denetimi devam ediyor; gerçek sermaye için onaylı değil.**

> 08.08.2026 tarihli eski rapordaki %54,29 win rate, +0,244R expectancy ve PF 1,32 değerleri yeni fill modeliyle yeniden üretilmedi. PR #32 öncesinde backtest, LIMIT emirlerini seviyeye dokunmadan dolmuş sayabiliyordu ve MARKET girişlerini sinyal fiyatından varsayıyordu. Bu nedenle eski metrikler güncel performans kanıtı değildir.

## 1. Ürün kapsamı

Atlas, Android/UserLAnd üzerinde çalışan terminal tabanlı SMC analiz aracıdır.

- Veri: Bybit public OHLCV; alım-satım API anahtarı gerektirmez.
- Zaman dilimleri: 15m / 1h / 4h / 1d / 1w.
- Analiz: piyasa yapısı, BOS/CHoCH, likidite, FVG, order block, OTE, MTF, SMT, CISD ve hacim profili.
- Karar: sinyal + setup kalitesi + risk + RR filtreleri.
- Çıktı: tek terminal ekranında LONG/SHORT/işleme girme kararı, giriş türü, SL ve TP seviyeleri.
- Yürütme: terminal ürünü borsaya emir göndermez.
- AI/LLM: ürün akışında model kullanılmaz. Depo sözleşmesi sohbet modeli, model indirme/başlatma, Telegram ve bulut servisi eklenmesini yasaklar. Mevcut deterministik analiz ve öğrenme motorları kullanılmaya devam eder.

## 2. Son doğrulanmış mühendislik düzeltmeleri

| PR | Düzeltme | Durum |
|---|---|---|
| #28, #31 | Yapısal stop seçimi, ATR tabanlı minimum mesafe, stop sonrası RR/TP yeniden hesaplama | Birleştirildi |
| #32 | MARKET girişini sonraki mum açılışından simüle etme; LIMIT için fiyat dokunuşu/fill şartı; aynı mum koruma-stop belirsizliğinde muhafazakâr çıkış | Birleştirildi |
| #33 | OHLCV verisinde eksik, bozuk, NaN/Infinity, geçersiz fiyat ve sırasız mum kontrolleri | Birleştirildi |
| #34 | Risk ve karar katmanlarında NaN/Infinity değerlerini reddetme | Birleştirildi |
| #35 | Gerçekleşmemiş sinyalleri kapanmış işlem istatistiklerinden ayırma | Birleştirildi |
| #36 | Son kapanmış 15m mum 30 dakikadan eskiyse canlı analizden işlem sinyali üretmeme | Birleştirildi |

Tüm değişiklikler ayrı PR ve CI kontrolleriyle birleştirildi. Son birleştirme sonrası ana dalın kontrolü ayrıca takip edilmelidir.

## 3. Performans kanıtı

Şu anda bu belgede güncel ve geçerli bir kârlılık iddiası yoktur.

Gerçek sermayeden önce aşağıdakiler yeniden üretilmelidir:

1. Yeni MARKET/LIMIT fill mantığıyla tarihsel backtest.
2. Komisyon, spread ve kaymanın tek ve doğru biçimde hesaba katılması.
3. Parametreleri sabit tutarak ayrı out-of-sample dönem testi.
4. Sembol, yön, setup fingerprint ve piyasa rejimi kırılımı.
5. Expectancy (R), profit factor, max drawdown, örneklem sayısı ve açık işlem sayısı.
6. İleriye dönük demo sinyallerinde yeterli sayıda kapanmış işlem.

Sinyal puanı veya confidence yüzdesi kazanma olasılığı değildir. Testlerin geçmesi kârlılığı garanti etmez.

## 4. Açık denetim başlıkları

- Ücret/kayma varsayımlarının backtest ve sinyal sonucu takibinde tam olarak bir kez uygulanmasını kanıtlamak.
- Look-ahead kontrolünü cache restore ve tüm yardımcı SMC modüllerinde genişletmek.
- Eski Bybit execution modüllerinin terminal akışından erişilemediğini ve güvenlik kilidinin tüm çağrı yollarında korunduğunu doğrulamak.
- Out-of-sample ve walk-forward test komutlarını tekrarlanabilir hale getirmek.
- Sembol bazlı performans ve minimum örneklem kurallarını raporlamak.
- Sinyal geçerlilik süresi ve manuel işlem günlüğü/otomatik sinyal sonuçlarının ayrımını uçtan uca doğrulamak.

## 5. Kurulum ve kullanım

```bash
python3 -m pip install -r requirements.txt
python3 atlas_app.py --install-cli
source ~/.bashrc
atlas
```

Komutlar:
- BTC, ETH, BRC — ilgili USDT perpetual piyasasını analiz et.
- işlem ver — hacme göre seçilen sınırlı piyasa listesindeki geçerli kurulumu bul.
- yardım — komutları göster.
- çıkış — uygulamayı kapat.

Atlas uygun koşul bulamazsa işlem uydurmaz. Gerçek emirleri kullanıcı kendi borsasında manuel olarak girer.
