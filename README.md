# Atlas

Atlas, kripto piyasalarını SMC (Smart Money Concepts) yaklaşımıyla analiz eden, terminal üzerinden çalışan bir analiz aracıdır. Android UserLAnd/Ubuntu ve Linux üzerinde kullanılabilir.

**Bu sürüm analiz aracıdır; otomatik al-sat yapmaz.** Borsaya emir veya pozisyon göndermez. Analiz için herkese açık piyasa verilerini kullanır. Bybit API anahtarı gerekmez.

## Gereksinimler

- Ubuntu (UserLAnd) veya Linux
- Python 3, venv ve pip
- Git
- İnternet bağlantısı

## Kurulum

Ubuntu terminalinde aşağıdaki komutları sırayla çalıştır:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip build-essential
git clone https://github.com/12baro1/Atlas.git
cd Atlas
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

UserLAnd ortamında `sudo` kullanılamıyorsa apt komutlarını sudo olmadan çalıştır.

## Başlatma

Her yeni terminal oturumunda:

```bash
cd ~/Atlas
source venv/bin/activate
./atlas
```

İstersen komutu sisteme kurup her klasörden `atlas` olarak çalıştırabilirsin:

```bash
python atlas_app.py --install-cli
source ~/.bashrc
atlas
```

Komut bulunamazsa proje klasöründen `./atlas` ile başlat.

Belirli bir sembolle doğrudan açmak için:

```bash
./atlas BTC
./atlas ETH
```

## Kullanım

Atlas açıldığında komut alanına sembol veya desteklenen komutlardan birini yaz:

| Komut | İşlev |
|---|---|
| `BTC`, `ETH`, `SOL` | İlgili USDT perpetual piyasasını analiz eder |
| `işlem ver` | Varsayılan taramayı çalıştırır ve uygun kurulum arar |
| `50 analiz et` | 50 piyasayı tarar |
| `100 analiz et` | 100 piyasayı tarar |
| `en iyi 5 işlem` | Tarama sonuçlarından en iyi 5 kurulumu listeler |
| `tüm piyasayı tara` | Desteklenen tüm USDT perpetual piyasalarını tarar |
| `likidite BTC` | BTC likidite seviyelerini gösterir |
| `performans` | Kayıtlı işlem performansını gösterir |
| `öğrenme` | Kayıtlı öğrenme verisini gösterir |
| `yardım` | Komutları listeler |
| `çıkış` | Programdan çıkar |

Tarama süresi piyasa sayısına ve internet bağlantısına göre değişir. Geçerli koşulları sağlayan kurulum yoksa Atlas sinyal üretmeyebilir.

## Backtest

Sanal ortam açıkken proje klasöründe:

```bash
python3 backtest.py --symbol BTC/USDT:USDT --days 7
```

Birden fazla sembol:

```bash
python3 backtest.py --symbols "BTC/USDT:USDT,ETH/USDT:USDT" --days 30
```

Backtest geçmiş veriyi simüle eder; gerçek piyasa dolumunu veya gelecekteki performansı garanti etmez.

## Güncelleme

```bash
cd ~/Atlas
git pull --ff-only origin main
source venv/bin/activate
python -m pip install -r requirements.txt
```

## Sorun giderme

**`atlas: command not found`**

```bash
cd ~/Atlas
source venv/bin/activate
./atlas
```

**`No module named ...`**

```bash
cd ~/Atlas
source venv/bin/activate
python -m pip install -r requirements.txt
```

## Güvenlik

- Analiz için borsa API anahtarı girme; Atlas'ın normal kullanımında gerekmez.
- Gerçek API anahtarı, parola veya kişisel erişim bilgilerini depoya yükleme.
- Sinyaller yatırım tavsiyesi değildir ve kâr garantisi vermez.
- Önce demo ortamında doğrula. Kaldıraçlı işlemlerde sermayenin tamamı kaybedilebilir.
