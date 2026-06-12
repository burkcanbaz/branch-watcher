Teammate'in PC'sinde kurulum

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
```
> ufw zaten kapalıysa (inactive) hiç dokunmana gerek yok — port baştan açıktır. Kontrol: `sudo ufw status`.
