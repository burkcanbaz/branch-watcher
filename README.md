# Branch Watcher

Bir git deposunun current branch'ini bir target branch (varsayılan `origin/develop`)
ile kıyaslar; ahead/behind sayılarını, local commit'leri ve incoming commit'leri
gösterir. Terminalden ya da LAN'dan erişilebilen bir web arayüzünden kullanılabilir.

## Proje yapısı

```
branch-watcher/
├── app/                     # uygulama kodu
│   ├── arp_scan.py
│   ├── branch_status.py
│   ├── firewall.py
│   ├── logging_setup.py     # ortak logger (konsol + dönen log dosyası)
│   └── templates/status.html
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── scripts/
│   └── setup-permissions.sh
├── .dockerignore
├── .env.example
├── requirements.txt
└── start.sh                 # Docker stack'ini build edip çalıştırır
```

## Docker ile çalıştırma (önerilen)

Her şey container'dan çalışacak şekilde paketlendi (git + arp-scan + ufw image
içinde gelir):

```bash
cp .env.example .env
# .env içinde izlemek istediğin repoyu host yolu olarak ver:
#   BW_REPO_HOST=/home/kullanici/projem
./start.sh            # build edip ön planda çalıştırır
./start.sh -d         # arka planda (detached)
./start.sh down       # durdur ve kaldır
./start.sh logs -f    # logları takip et
```

Container, root değil **non-root `app` user'ı** olarak çalışır. `arp-scan` ve
`ufw` root gerektirdiğinden, app user'a image içinde **sadece bu iki binary için**
şifresiz sudo verilir (tüm uygulamayı root çalıştırmak yerine). `network_mode:
host` ile çalışır; web arayüzü host'un kendi IP'sinde `BW_PORT` (varsayılan 9534)
üzerinden açılır. arp-scan/ufw için gereken `NET_ADMIN` ve `NET_RAW` yetenekleri
compose'da verilir.

İzlenen repo `/repo`'ya read-only mount edilir — `--fetch` kullanacaksan
compose'daki `:ro` ekini kaldır. Loglar `branch-watcher-logs` adlı bir named
volume'a yazılır (non-root user sahipliğini koruyabilsin diye); konsola da
basıldığı için `./start.sh logs -f` ile canlı izleyebilirsin.

> `start.sh`, `up` akışında önce `scripts/setup-permissions.sh`'i çalıştırmayı
> dener (host tarafı, opsiyonel firewall/cron kullanımı için). Docker akışı için
> gerekli değildir — başarısız olursa stack yine de ayağa kalkar.

## Kurulum (Docker'sız, doğrudan Python)

```bash
cd branch-watcher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Ayarları .env üzerinden yönet (başka PC'de sadece bu dosyayı değiştir):
cp .env.example .env

# Python modülleri app/ altında:
cd app
```

Tüm static değerler (`BW_REPO`, `BW_TARGET`, `BW_HOST`, `BW_PORT`, `BW_REFRESH`,
`BW_FETCH`, `ARP_SCAN_CMD`, `ARP_INTERFACE`, `TARGET_MAC`) `.env` dosyasından
okunur. Başka bir makineden çalıştırırken kodu değiştirmeden sadece `.env`
değerlerini düzenlemen yeterli. CLI argümanları env değerlerini ezer.

## Kullanım

Terminal raporu:

```bash
python branch_status.py "/path/to/repo"
python branch_status.py "/path/to/repo" --target origin/main
python branch_status.py "/path/to/repo" --fetch        # önce remote'u tazele
```

Web arayüzü (bu PC'yi LAN'dan dinlemek için):

```bash
python branch_status.py "/path/to/repo" --serve
# http://127.0.0.1:8787            (bu makinede)
# http://<bu-pc-nin-ip>:8787       (aynı ağdaki başka cihazdan)
# http://<bu-pc-nin-ip>:8787/api   (JSON)
```

Seçenekler: `--port`, `--host`, `--refresh` (oto-yenileme saniyesi), `--fetch`.

> Not: ahead/behind ve incoming commit'lerin güncel olması için remote ref'lerin
> güncel olması gerekir. Ağ erişimi varsa `--fetch` ekleyin; yoksa son `git fetch`
> anındaki duruma göre rapor verir.

## Ağ taraması (arp-scan) — ayrı, bağımsız modül

`arp_scan.py` tamamen kendi başına çalışır; `branch_status.py`'den bağımsızdır.
Başka bir projeye taşıyıp `arp_scan` / `find_ip_by_mac` fonksiyonlarını
import edebilirsin.

```bash
# Ağdaki tüm cihazları listele
python arp_scan.py

# Belirli bir MAC'in IP'sini bul (sadece IP basar)
python arp_scan.py --mac AA:BB:CC:DD:EE:FF

# Arayüzü zorla
python arp_scan.py --interface wlan0
```

Koddan kullanım:

```python
from arp_scan import arp_scan, find_ip_by_mac

hosts = arp_scan()                              # [{ip, mac, vendor}, ...]
ip = find_ip_by_mac("AA:BB:CC:DD:EE:FF")        # "192.168.1.42" ya da None
```

Ayarlar (env / `.env`): `ARP_SCAN_CMD`, `ARP_INTERFACE`, `TARGET_MAC`.

## Erişimi tek bir cihaza kilitleme (firewall)

Backend `0.0.0.0`'a bind olduğu için varsayılan olarak LAN'daki herkese açıktır.
Sadece **kendi PC'nin** erişmesini istiyorsan, IP yerine **MAC** ver: backend
açılışta o MAC'in güncel IP'sini `arp-scan` ile bulur ve `ufw` ile sadece o IP'ye
izin verir. Ayrıca arka planda **her 10 dakikada bir** (`BW_FIREWALL_REFRESH`, saniye)
MAC'i yeniden çözüp kuralı tazeler — yani backend çalışırken IP'n DHCP ile değişse
bile en geç bir sonraki tazelemede yeni IP'ne göre güncellenir.

```bash
# 1) arp-scan + ufw için şifresiz sudo'yu bir kez kur (backend'in olduğu makinede):
./scripts/setup-permissions.sh

# 2) .env'e kendi makinenin MAC'ini yaz:
#    BW_ALLOW_MAC=AA:BB:CC:DD:EE:FF

# 3) backend'i başlat — açılışta firewall kuralı otomatik uygulanır:
uv run branch_status.py
```

Kuralı elle de uygulayabilirsin:

```bash
python firewall.py --port 9534 --mac AA:BB:CC:DD:EE:FF
```

Backend'i hiç çalıştırmadan, gerçek bir cron job olarak da kurabilirsin
(10 dakikada bir):

```cron
*/10 * * * * cd /path/to/branch-watcher/app && /path/to/.venv/bin/python firewall.py --port 9534 --mac AA:BB:CC:DD:EE:FF
```

> `BW_ALLOW_MAC` boşsa firewall'a hiç dokunulmaz (LAN'a açık kalır). Şifresiz sudo
> kurulmamışsa firewall adımı atlanır ve backend yine de ayağa kalkar (uyarı basar).

> Not: `arp-scan` root ister (varsayılan komut `sudo arp-scan --localnet`).
> Terminalden şifreyi sorar; bir backend içinden çağıracaksan şifresiz sudo ver:
>
> ```bash
> echo "$USER ALL=(root) NOPASSWD: /usr/sbin/arp-scan" | sudo tee /etc/sudoers.d/arp-scan
> ```

## Loglama

Tüm modüller `app/logging_setup.py`'deki ortak logger'ı kullanır: her önemli
adım loglanır ve hatalar (ör. bir MAC'in LAN'da bulunamaması, arp-scan/ufw/git
komutlarının başarısız olması) `ERROR` seviyesinde yazılır. Loglar hem konsola
hem de dönen bir dosyaya (`branch_watcher.log`, ~1MB'da döner, 3 yedek) gider.

Ayarlar (env / `.env`):

- `BW_LOG_LEVEL` — `DEBUG` / `INFO` / `WARNING` / `ERROR` (varsayılan `INFO`)
- `BW_LOG_FILE` — log dosyası yolu (Docker'da `/app/logs/branch_watcher.log`'a mount edilir)
