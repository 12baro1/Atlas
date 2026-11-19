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
Giriş: {giriş} | Stop: {stop}
TP1: {tp1} | TP2: {tp2} | TP3: {tp3}

İŞLEMLERİM — {sayı}
1. {sembol} | {yön} | Giriş bekliyor
Giriş: {giriş} | Stop: {stop}
TP1: {tp1} | TP2: {tp2} | TP3: {tp3}
2. {sembol} | {yön} | TP1 alındı
Giriş: {giriş} | Stop: {stop}
TP1: {tp1} | TP2: {tp2} | TP3: {tp3}
Güncel stop: {güncel_stop}

{sembol} — SETUP GÜNCELLENDİ
Eski: {yön} | {strateji}
Yeni: {yön} | {strateji}
Giriş: {giriş} | Stop: {stop}
TP1: {tp1} | TP2: {tp2} | TP3: {tp3}
```

## Doğrulama ve işletim sınırları

Çevrimdışı regresyonlar gerçek SQLite veritabanlarını, worker döngüsünü, runtime analiz girişini ve Telegram handler’larını çalıştırır. Piyasa cevabı ve Telegram taşıması testte kontrol edilir. Testler 299 işten sonra yeniden başlatmayı, hacim sıralı 300’ün yayınlanmasını, otomatik yeni generation’ı, aktif pozisyonun korunmasını, tekrar bildirimini, temizlikleri ve sohbet ayrımını kapsar. Menüdeki 35 komut ayrıca grup hitabı, handler seçimi, hatalı parametre ve servis istisnasıyla sınanır.

## PR #220 takip denetimi

- PR #219 sürümünden kalan bir işin `done` satırı olup geçici analiz sonucu bulunmayabiliyordu. Yayıncı eksik sonuçlu başarılı işleri aynı generation içinde yeniden tarar. Yayını daha önce tamamlanmış generation yeniden açılmaz.
- Her bildirim için kalıcı olay kimliği ve benzersiz sohbet/sembol/revizyon/olay anahtarı vardır. Olay sanal işlem geçişiyle birlikte kaydedilir. Gönderici, HTTP çağrısından önce SQLite transaction içinde denemeyi sahiplenir. Başarı için doğru sohbet kimliği ve pozitif Telegram mesaj kimliği gerekir.
- Kesin bağlantı zaman aşımı ve Telegram’ın geçici retleri artan gecikmeyle tekrar denenir. 429 yanıtının bekleme süresine uyulur. Sekiz başarısız denemeden sonra kayıt inceleme için saklanır. Cevabı kaybolan istek veya gönderim sırasında çöken süreç için durum belirsiz kalır. Yeniden başlatma bu kayıtları otomatik göndermez. /durum doğrulanamayan bildirimlerin sayısını gösterir.
- Bir en iyi listesi iletilirken havuz değişirse sohbet üyeliği gösterilen gözlemden oluşturulur. Daha yeni seçim veya aynı stratejiye ait yapısal iptal daha sonra aynı transaction içinde uygulanır.
- Eksik 4H girdisi ve geçersiz ATR artık stratejinin yapısal koşulunun bozulduğu şeklinde kaydedilmez. Net RR için ortak risk planının maliyet sonrası değeri kullanılır. Eksik net RR yerine brüt RR yazılması engellendi. Sanal pozisyon planın kısmi çıkış oranlarını ve işlem maliyeti girdilerini saklar. Gecikmiş bir fiyat serisi açık PnL değerlemesini geriye alamaz.
- Gece yarısı görünümü için kapanış zamanı, sonucun görüldüğü mumun kapanışıdır. Gecikmeli işlemenin saati bir önceki günün sonucunu bugüne taşımaz.

**Canlı kontrol.** Gate.io API üzerinde hacim sıralaması 300 farklı USDT perpetual sözleşmesi verdi. Seçilen 300 sembolün her birinden tazelik sınırı içinde en az bir kapanmış 15 dakikalık mum alındı. Ayrı bir BTC çalıştırmasında gerçek runtime yedi stratejiyi değerlendirdi. Relative strength adayı ortak filtrede elendi ve nihai setup çıkmadı. 300 tam strateji analiziyle generation devrinin testi çevrimdışı yürütüldü.

**Sınırlar.** Gerçek Telegram teslimatı ve BotFather’ın uzaktaki menüsü doğrulanmadı. Gönderimden sonra yanıt kaybolursa mesajın ulaşıp ulaşmadığını Atlas kesin olarak bilemez. Kullanıcı komutunun yanıtı ile yerel takip kaydı arasındaki süreç çökmesi de üyelik kaydını engelleyebilir. Bu işlemler iki ayrı sistemdedir. Sanal fiyatlar kapanmış mumlara dayanır. Açık PnL son işlenmiş kapanışı gösterir. Fiyat sırasının veya mum geçmişinin belirsiz kaldığı durumlarda kapanış getirisi hesaplanmaz.

**Test sonucu.** Derleme ve diff kontrolleri geçti. Ağır runtime testleri açıkken 1465 test geçti. Üretim günlüğüne ihtiyaç duyan bir entegrasyon testi gerçek `atlas_journal.db` bulunmadığı için atlandı.
