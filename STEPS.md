Teammate'in PC'sinde kurulum

# A) Docker ile (önerilen) — 3 adım

Sadece Docker gerekiyor; git ve python image'ın içinde geliyor.

**1) `.env`'i doldur**
```bash
cd branch-watcher
cp .env.example .env
```
`.env` içinde **sadece şu 5 alan zorunlu** — gerisi varsayılanıyla çalışır:

| alan | ne yazacaksın | örnek |
| --- | --- | --- |
| `BW_REPO` | izlenecek repo'nun host'taki yolu | `/home/kullanici/projem` |
| `BW_MAIL_TO` | raporun gideceği adres(ler), virgülle | `ben@firma.com, ekip@firma.com` |
| `BW_SMTP_HOST` | mail sunucusu | `smtp.gmail.com` |
| `BW_SMTP_USER` | gönderen hesabın adresi | `ben@gmail.com` |
| `BW_SMTP_PASS` | o hesabın uygulama şifresi | `abcd efgh ijkl mnop` |

Hazır gelen varsayılanlar: `BW_SMTP_PORT=587`, `BW_SMTP_SECURITY=starttls`
(Gmail için doğru), `BW_TARGET=origin/develop`, `BW_MAIL_TIME=09:15`,
`BW_MAIL_TZ=Europe/Istanbul`. `BW_MAIL_FROM` boşsa `BW_SMTP_USER` kullanılır.

> **Gmail'de normal hesap şifren çalışmaz**, 16 haneli bir uygulama şifresi
> gerekir: <https://myaccount.google.com/apppasswords> (2 Adımlı Doğrulama açık
> olmalı). Adım adım anlatım README'deki **"Gmail ile SMTP"** bölümünde.

> Bilgilerini `.env`'e yaz, `.env.example`'a **değil**. `.env` gitignore'da ve
> image'a kopyalanmaz — kimsenin şifresi repoya girmez; `.env.example` ise git'e
> giren şablon dosya.

**2) Ayarları doğrula (hemen bir mail atar)**
```bash
./start.sh test-mail        # ./start.sh preview-mail => göndermeden ekrana bas
```

**3) Başlat**
```bash
./start.sh -d               # arka planda
./start.sh logs -f mailer   # "Next mail at ... 09:15 +03" yazmalı
```
Bu kadar. Her sabah **09:15'te (UTC+3)** container branch'ini `origin/develop`
ile karşılaştırıp merge gerekip gerekmediğini `BW_MAIL_TO`'daki herkese mailler.
Cron veya git hook kurmana gerek yok. Makine yeniden başlarsa container
`restart: unless-stopped` ile kendiliğinden kalkar (Docker servisi açılışta
başlıyorsa).

Faydalı komutlar:
```bash
./start.sh logs -f          # tüm loglar
./start.sh down             # durdur
./start.sh -d               # .env'i değiştirdikten sonra tekrar çalıştır
                            # (restart .env'i YENİDEN OKUMAZ, up okur)
```

---

# B) Docker'sız (doğrudan Python)

**1) Bağımlılıklar**
```bash
sudo apt install git
cd branch-watcher
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

**2) `.env`**
```bash
cp .env.example .env
```
İçinde:
```
BW_REPO=/teammate/in/repo/yolu
BW_PORT=9534
BW_HOST=0.0.0.0
BW_SERVE=true
```

**3) Backend'i başlat**
```bash
cd app
python branch_status.py --serve          # ya da .env'de BW_SERVE=true ise: python branch_status.py
```

**4) Portu LAN'a açmak istersen (opsiyonel)**

Web arayüzüne aynı ağdaki başka bir cihazdan bakacaksan makinende firewall
açıksa porta izin ver:
```bash
sudo ufw allow 9534/tcp      # ya da daha dar: --from <subnet'in>
```
> Firewall kapalıysa (`sudo ufw status` → inactive) hiçbir şey yapmana gerek yok.

**5) Günlük mail (Docker'sız)**

`.env`'de SMTP ayarlarını doldurduktan sonra mailer'ı ayrı bir süreç olarak
çalıştır — o da 09:15'i kendi bekler:
```bash
cd app
python mailer.py --dry-run     # önce raporu gör
python mailer.py --once        # gerçekten bir mail at
python mailer.py               # günlük zamanlayıcı (arka planda çalışsın:
                               #   nohup python mailer.py >/dev/null 2>&1 &)
```
