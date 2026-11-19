# Atlas tarama ve Telegram sanal işlem denetimi

## Çalışma akışı

1. Runtime açılışında kalıcı kuyruktaki yarım işler sürer. Yeni generation için envanterden pozitif ve sonlu 24 saatlik hacmi ölçülen 300 farklı Gate.io USDT perpetual sözleşmesi gerekir. Yeterli sıralama yoksa worker yeniden dener. Manuel komut generation boyunu değiştiremez.
2. Her başarılı analiz, karar mumunun zamanı, analiz zamanı, seçilmiş aday ve yapısı bozulan strateji kimlikleriyle birlikte kuyruk veritabanına yazılır. Sonuç yazımı ve işin tamamlanması aynı transaction içindedir. Worker yalnızca kendi generation ve lease denemesini tamamlayabilir. Hata kontrollü yeniden denenir ve sınır dolduğunda başarısız sayılır.
3. Kuyruk boşalınca yayıncı geçerli sonuçları, arşivi, takip revizyonlarını, bildirimleri ve son uygulanan generation numarasını havuz veritabanında birlikte kaydeder. Bu commit sonrasında geçici sonuçlar silinir ve yeni döngü açılır. İki veritabanı arasındaki kesintide generation işareti çift yayını önler. Hatalı analiz o sembol için yapısal iptal üretmez.
4. Ayrı bakım görevi ilk çalışmada kalıcı bir başlangıç zamanı kaydeder. Ardından son temizlikten 24 saat geçince havuzdaki adayları ve doğrulanmış kayıtları arşive taşır. Üyelikler ve pozisyonlar korunur. Bir sonraki tamamlanmış döngü yeni yayını yapar.
5. Her sohbetin üyeliği ve sanal pozisyon revizyonları aynı SQLite veritabanında tutulur. Üretimde manuel analiz ve en iyi listelerinin takibi başarılı Telegram yanıtından sonra kaydedilir. /havuz ve /setup sadece okur. Bekleyen geometri değiştiğinde önceki revizyon kapanır. Açılmış ve sonucu belirsiz pozisyonlar kendi kimliklerini korur.
6. Sanal takip kararı izleyen tamamen kapanmış 15 dakikalık mumlarla çalışır. LIMIT için fiyat aralığı, MARKET için sonraki uygun mum açılışı kullanılır. Aktif sembollerin mumları tarama dışında da bakım göreviyle yenilenir. Eksik mum veya çözülmeyen mum içi sıra sonucu belirsiz bırakır. Kısmi hedefler, kalan pozisyon ve kapanış maliyeti mevcut sinyal günlüğünün hesaplayıcısını kullanır. Para birimi cinsinden bakiye veya borsa emri oluşturulmaz.
7. /islemler sonuçlanmış kayıtları çözülme gününün sonuna kadar gösterir. Gün sınırı Europe/Istanbul ile hesaplanır. Bu görünüm restart sırasında da doğrudur. /gecmis ayrı ve kalıcıdır.

## BotFather ve komut envanteri

| Komut | Girdi, işlem ve çıktı |
|---|---|
| /btc, /eth, /sol, /avax, /analiz SEMBOL | Güncel analiz. Seçilen stratejinin risk ve geometri kontrolü geçerse yön ve seviyeler gösterilir. Normal bir grup sohbetindeki yalın sembol analiz başlatmaz. Diğer semboller örneğin /doge ile çağrılabilir. |
| /tara N, /20tara, /30tara, /50tara, /100tara, /200tara, /500tara, /1000tara, /tumtara | Sürekli taramayı sürdürür ve ilk N sıradaki bekleyen işleri önceliklendirir. Üst sınır döngünün 300 sembolüdür. Metin olarak 20 tara ve 30 tara da aynı servise gider. |
| /taramadurum, /taramadurdur, /taramadevam | Kalıcı kuyruk sayıları, kontrollü worker durdurma ve yeniden başlatma. |
| /yenile, /veri | Gate.io envanter yenilemesi ve veri durumu. |
| /havuz, /havuzdurum, /setup SEMBOL | Yayımlanmış fırsatlar, havuz sayıları veya bir sembolün doğrulanmış seviyeleri. |
| /eniyi5, /eniyi10 | Yayımlanmış havuzdan sıralı seçim. Gösterilen semboller sohbete bağlanır. |
| /islemler, /gecmis | Sohbetin sanal portföyü ve kapanma/iptal geçmişi. /mevcut, /setuplar ve /takip eski çağrıları /islemler handler’ına gider. |
| /likidite SEMBOL | Sembolün likidite analizi. |
| /performans | Sistem sinyal günlüğü ile manuel kayıtlar için ayrı performans özeti. Sohbete özel sanal sonuçlar /islemler içindedir. |
| /istatistik, /motorlar, /ogrenme | Strateji üretimi, ret gerekçeleri, motor ve öğrenme durumu. |
| /start, /yardim, /durum, /sistem | Kullanım, komut listesi, servis ve yerel kaynak durumu. |

Grup komutundaki bot adı artık parametreyi yutmaz. Başka bota hitap eden komut bilinen bot kullanıcı adıyla karşılaştırılır. Geçersiz tarama parametresi sınırsız iş başlatamaz. Komut servis hatasında dahili istisna metnini kullanıcıya aktarmaz.

## Mesaj biçimleri

Aşağıdaki değişkenler uygulamada gerçek havuz ve sinyal alanlarından doldurulur.

```text
EN İYİ 5 SETUP
1. {sembol} | {yön} | {strateji} | {net_R}

İŞLEMLERİM — {sayı}
1. {sembol} | {yön} | Giriş bekliyor
2. {sembol} | {yön} | TP1 alındı

{sembol} — SETUP GÜNCELLENDİ
Eski: {yön} | {strateji}
Yeni: {yön} | {strateji}
Giriş: {giriş} | Stop: {stop} | TP1: {tp1} | TP2: {tp2}
```

## Doğrulama ve işletim sınırları

Çevrimdışı regresyonlar gerçek SQLite veritabanlarını, worker döngüsünü, runtime analiz girişini ve Telegram handler’larını çalıştırır. Piyasa cevabı ve Telegram taşıması testte kontrol edilir. Testler 299 işten sonra yeniden başlatmayı, hacim sıralı 300’ün yayınlanmasını, otomatik yeni generation’ı, aktif pozisyonun korunmasını, tekrar bildirimini, temizlikleri ve sohbet ayrımını kapsar. Menüdeki 35 komut ayrıca grup hitabı, handler seçimi, hatalı parametre ve servis istisnasıyla sınanır.

Gate.io canlı piyasa erişimi, BotFather’ın uzaktaki menüsü ve gerçek Telegram teslimatı bu değişikliğin testine dahil değildir. Başarılı Telegram teslimatı ile yerel SQLite onayı ayrı sistemlerdedir. Aradaki çökmede tekrar bildirim veya henüz kaydedilmemiş bir takip üyeliği mümkündür. Sanal MARKET fiyatı sonraki uygun mum açılışıdır. R cinsinden açık değer son kapanmış muma dayanır. Mum geçmişindeki boşluk veya belirsiz fiyat sırası otomatik sonuçlandırılmaz. İşletim bir runtime yazıcısı ve yapılandırılmış bir yetkili sohbet kullanır.


Tam yerel kontrol: `ATLAS_RUN_RUNTIME_HEAVY_TESTS=1 python3 -m pytest -q -rs` ile 1455 test geçti. Üretim entegrasyon testi gerçek `atlas_journal.db` bulunmadığı için atlandı. `python3 -m compileall -q .` ve `git diff --check` başarılıydı.
