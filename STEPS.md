Teammate'in PC'sinde kurulum

# A) Docker ile (önerilen) — 3 adım

Sadece Docker gerekiyor; git/python/arp-scan image'ın içinde.

**1) `.env`'i doldur**
```bash
cd branch-watcher
cp .env.example .env
```
İçinde en az şunlar:
```
BW_REPO=/kendi/repo/yolun          # host'taki repo yolu
BW_TARGET=origin/develop
BW_MAIL_TO=ekip1@firma.com, ekip2@firma.com
BW_SMTP_HOST=smtp.gmail.com
BW_SMTP_PORT=587
BW_SMTP_USER=kendi.adresin@gmail.com
BW_SMTP_PASS=uygulama-sifresi      # Gmail: normal şifre DEĞİL, "uygulama şifresi"
BW_SMTP_SECURITY=starttls
```

> Gmail uygulama şifresini <https://myaccount.google.com/apppasswords> adresinden
> alırsın (2 Adımlı Doğrulama açık olmalı). Adım adım anlatım için README'deki
> **"Gmail ile SMTP"** bölümüne bak.
> Herkes kendi SMTP bilgisini kendi `.env`'ine yazar. `.env` gitignore'da ve
> image'a kopyalanmaz — kimsenin şifresi repoya girmez.

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
./start.sh restart          # .env değişikliğinden sonra
```

---

# B) Docker'sız (doğrudan Python)

**1) Bağımlılıklar**
```bash
sudo apt install git arp-scan        # arp-scan sadece BW_ALLOW_MAC kullanacaksa şart
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

**4) Firewall — iki seçenek**

**Seçenek A — basit (portu LAN'a aç):**
```bash
sudo ufw allow 9534/tcp
# ya da daha dar, sadece kendi subnet'in:
sudo ufw allow from 192.168.12.0/24 to any port 9534 proto tcp
sudo ufw enable
sudo ufw status
```
> ufw zaten kapalıysa (inactive) hiç dokunmana gerek yok — port baştan açıktır. Kontrol: `sudo ufw status`.

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
