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
│   ├── mailer.py            # her sabah 09:15'te rapor maili atan servis
│   ├── logging_setup.py     # ortak logger (konsol + dönen log dosyası)
│   └── templates/
│       ├── status.html      # web arayüzü
│       └── email.html       # mail şablonu
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
#   BW_REPO=/home/kullanici/projem
# ve mail ayarlarını doldur (aşağıdaki "Günlük mail raporu" bölümü).
./start.sh              # build edip ön planda çalıştırır
./start.sh -d           # arka planda (detached)
./start.sh down         # durdur ve kaldır
./start.sh logs -f      # logları takip et
./start.sh test-mail    # ayarları doğrula: hemen bir rapor maili at
./start.sh preview-mail # maili göndermeden terminale bas
```

Stack iki servis ayağa kaldırır:

| servis | ne yapar |
| --- | --- |
| `branch-watcher` | web arayüzü (`BW_PORT`, varsayılan 9534), opsiyonel firewall/arp-scan |
| `mailer` | her sabah `BW_MAIL_TIME`'da (varsayılan 09:15 Europe/Istanbul) rapor maili atar |

Sadece maili istiyorsan web'i hiç açmadan çalıştırabilirsin:

```bash
docker compose --project-directory . -f docker/docker-compose.yml up -d mailer
```

Container, root değil **non-root `app` user'ı** olarak çalışır. `arp-scan` ve
`ufw` root gerektirdiğinden, app user'a image içinde **sadece bu iki binary için**
şifresiz sudo verilir (tüm uygulamayı root çalıştırmak yerine). `network_mode:
host` ile çalışır; web arayüzü host'un kendi IP'sinde `BW_PORT` (varsayılan 9534)
üzerinden açılır. arp-scan/ufw için gereken `NET_ADMIN` ve `NET_RAW` yetenekleri
compose'da verilir.

İzlenen repo `/repo`'ya mount edilir. Varsayılan olarak **read-write**, çünkü
`git fetch` `.git` içine yazmak zorunda (mail raporunun "behind" sayısı bugünkü
develop'a göre çıksın diye). Repo'ya hiç yazılmasın istiyorsan `.env`'de
`BW_REPO_MOUNT=ro` yap ve `BW_FETCH`/`BW_MAIL_FETCH`'i kapat. Loglar `branch-watcher-logs` adlı bir named
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

## Günlük mail raporu (`mailer.py`)

Her sabah **09:15'te (Europe/Istanbul = UTC+3)** container kendi kendine uyanır,
`BW_REPO`'daki branch'i `BW_TARGET` (varsayılan `origin/develop`) ile
karşılaştırır ve `BW_MAIL_TO`'daki herkese şu maili atar:

- ahead / behind sayıları,
- develop'tan gelen commit'ler ve local'deki commit'ler,
- net cevap: **"merge gerekli"** mi, **"güncel"** mi.

Cron'a ya da git hook'una gerek yok — zamanlamayı container'ın kendisi tutar;
tek şart ayakta kalması (compose'da `restart: unless-stopped`).

### Kurulum

`.env` içinde **kendi** SMTP bilgilerini doldur. Bu dosya `.gitignore`'da,
image'a da kopyalanmaz (`.dockerignore`) — şifren sadece senin makinende kalır,
repoda kimsenin bilgisi yoktur:

```bash
BW_MAIL_TO=ekip1@firma.com, ekip2@firma.com   # kime gidecek (virgülle)
BW_SMTP_HOST=smtp.gmail.com
BW_SMTP_PORT=587
BW_SMTP_USER=benim.adresim@gmail.com
BW_SMTP_PASS=xxxxxxxxxxxxxxxx                 # Gmail'de "uygulama şifresi"
BW_SMTP_SECURITY=starttls                     # starttls (587) / ssl (465) / none
BW_MAIL_FROM=benim.adresim@gmail.com          # boşsa BW_SMTP_USER kullanılır
```

### Gmail ile SMTP — herkes kendi hesabıyla (adım adım)

Ayrı bir mail sunucusu kurmana gerek yok: Gmail'in SMTP sunucusu
(`smtp.gmail.com`) herkesin kendi hesabıyla ücretsiz kullanabileceği bir
gönderim yolu. Tek şart, normal hesap şifreni **değil**, Google'ın ürettiği
16 haneli bir **uygulama şifresi** (app password) kullanmak — Google 2022'den
beri normal şifreyle SMTP girişini kapattı.

> **Önce doğru hesapta olduğundan emin ol.** Tarayıcında birden fazla Google
> hesabı açıksa aşağıdaki linkler **varsayılan** hesabı açar — şirket mailinle
> uğraşırken kişisel hesabının ayarlarına girmiş olabilirsin. Sayfanın sağ
> üstündeki avatardan hesabı kontrol et; en garantisi gizli sekme açıp sadece o
> hesapla giriş yapmak.

#### 1) 2 Adımlı Doğrulama'yı aç

Uygulama şifresi ancak 2 Adımlı Doğrulama açıkken üretilebilir; kapalıysa
uygulama şifresi sayfası hiç açılmaz.

1. <https://myaccount.google.com/security> (sol menüde **Güvenlik**).
2. **"Google'da oturum açma şekliniz"** başlığı altında → **2 Adımlı Doğrulama**.
   Doğrudan link: <https://myaccount.google.com/signinoptions/twosv>
3. Telefon/Authenticator ile kurulumu tamamla. Zaten "Açık" yazıyorsa atla.

#### 2) Uygulama şifresi üret

Google bu sayfayı menüden kaldırdı — Güvenlik sayfasında gezinerek bulamazsın.
Üç yoldan biriyle aç:

- **En kısası, doğrudan adres:** <https://myaccount.google.com/apppasswords>
- **Arama ile:** Google Hesabı sayfasının en üstündeki *"Google Hesabınızda arama
  yapın"* kutusuna `uygulama şifreleri` (İngilizce arayüzde `app passwords`) yaz
  → çıkan sonuca tıkla.
- **2FA sayfasından:** Güvenlik → 2 Adımlı Doğrulama → sayfanın **en altına in**
  → **Uygulama şifreleri**.

Sayfa açıldığında:

1. Tek bir alan vardır: **Uygulama adı** → `branch-watcher` yaz.
   (Eski arayüzde iki açılır liste görürsün: *Uygulama seç* → **Diğer (Özel ad)**
   → adı yaz.)
2. **Oluştur**'a bas.
3. Sarı bir kutuda `abcd efgh ijkl mnop` gibi 4'erli 4 grup — toplam 16 harf —
   çıkar. **Bu kutu bir daha açılmaz**, hemen kopyala; sonra **Bitti**.

Bu şifre sadece bu uygulamaya özeldir; aynı sayfadan istediğin an iptal
edebilirsin, hesabının asıl şifresi hiçbir yere yazılmaz.

> **Sayfa açılmıyor ya da "bu ayar hesabınızda kullanılamıyor" diyorsa:** ya 2
> Adımlı Doğrulama kapalıdır (1. adıma dön), ya da **şirket hesabında (Google
> Workspace) yönetici uygulama şifrelerini kapatmıştır**. İkincisinde senin
> tarafında yapılacak bir ayar yok: IT'den Admin Console'dan açmasını iste, ya da
> kişisel bir Gmail hesabı veya şirketin kendi SMTP relay'i ile devam et
> (aşağıdaki "Diğer sağlayıcılar" tablosu).

#### 3) `.env`'e yaz

```bash
BW_SMTP_HOST=smtp.gmail.com
BW_SMTP_PORT=587
BW_SMTP_SECURITY=starttls
BW_SMTP_USER=kendi.adresin@gmail.com
BW_SMTP_PASS="abcd efgh ijkl mnop"     # 2. adımdaki 16 haneli şifre
BW_MAIL_FROM=kendi.adresin@gmail.com   # Gmail'de gönderen = hesabın kendisi
BW_MAIL_TO=ekip1@firma.com, ekip2@firma.com
```

> Tırnaklar okunurken kaldırılır, yani `"abcd efgh ijkl mnop"` da
> `abcdefghijklmnop` da çalışır. Ama şifrede **boşluktan sonra `#`** geçiyorsa
> (`pass #x`) tırnaksız yazma — o kısım yorum sayılıp kırpılır. Şüphedeysen
> tırnak içine al; zararı yok.

#### 4) Test et

```bash
./start.sh test-mail
```

`Mail sent to ...` satırını görüyorsan bitti; gelen kutunu (ve Spam klasörünü)
kontrol et.

#### Bilinmesi gerekenler

- Gönderen adresi her zaman `BW_SMTP_USER`'daki Gmail hesabıdır. `BW_MAIL_FROM`'a
  başka bir adres yazarsan Gmail onu kendi adresinle değiştirir.
- Ücretsiz Gmail hesabında günlük ~500 alıcı sınırı var; günde bir rapor için
  fazlasıyla yeterli.
- Kendine mail atıyorsan (`BW_MAIL_TO` = kendi adresin) Gmail maili "Gönderilenler"
  ile aynı konuşmada gösterebilir; gelen kutusunda görünmüyorsa oraya bak.
- Şirket hesabında uygulama şifresi üretemiyorsan yöneticin kapatmış olabilir —
  2. adımın sonundaki nota bak.

#### Sık karşılaşılan hatalar

| Hata | Sebebi / çözümü |
| --- | --- |
| `535 5.7.8 Username and Password not accepted` | Normal hesap şifresi girilmiş. Uygulama şifresi üret (2. adım). |
| `534 5.7.9 Application-specific password required` | Aynı sebep: 2 Adımlı Doğrulama açık ama uygulama şifresi kullanılmamış. |
| Bağlantı 587'de zaman aşımına uğruyor | Ağın/ISS'in 587'yi kapatmış olabilir. `BW_SMTP_PORT=465` + `BW_SMTP_SECURITY=ssl` dene. |
| `BW_SMTP_HOST is empty` gibi bir liste | `.env` doldurulmamış ya da `./start.sh restart` yapılmamış. |
| Mail gitti ama gelmedi | Spam klasörüne bak; `BW_MAIL_TO`'daki adresi kontrol et. |

### Diğer sağlayıcılar

| sağlayıcı | `BW_SMTP_HOST` | port | `BW_SMTP_SECURITY` |
| --- | --- | --- | --- |
| Gmail | `smtp.gmail.com` | 587 | `starttls` |
| Gmail (alternatif) | `smtp.gmail.com` | 465 | `ssl` |
| Outlook / Microsoft 365 | `smtp.office365.com` | 587 | `starttls` |
| Yandex | `smtp.yandex.com` | 465 | `ssl` |
| Şirket içi relay (auth'suz) | kendi sunucun | 25 | `none` (USER/PASS boş) |

### Doğrula ve başlat

Ayarları doğrula (beklemeden hemen bir mail atar):

```bash
./start.sh test-mail       # gerçekten gönderir
./start.sh preview-mail    # göndermez, raporu terminale basar
```

Sonra stack'i başlat; mailer arka planda 09:15'i bekler:

```bash
./start.sh -d
./start.sh logs -f mailer
```

### Ayarlar

| değişken | varsayılan | açıklama |
| --- | --- | --- |
| `BW_MAIL_TIME` | `09:15` | günlük gönderim saati (HH:MM) |
| `BW_MAIL_TZ` | `Europe/Istanbul` | saatin hangi zaman diliminde olduğu (UTC+3) |
| `BW_MAIL_TO` | — | alıcılar, virgülle ayrılmış |
| `BW_MAIL_FROM` / `BW_MAIL_FROM_NAME` | `BW_SMTP_USER` / `Branch Watcher` | gönderen |
| `BW_MAIL_SUBJECT_PREFIX` | `[branch-watcher]` | konu başlığı öneki |
| `BW_MAIL_FETCH` | `true` | karşılaştırmadan önce `git fetch` |
| `BW_MAIL_ON_START` | `false` | container açılır açılmaz da bir mail at (test için) |
| `BW_MAIL_ONLY_WHEN_BEHIND` | `false` | `true` ise sadece merge gerektiğinde mail at |
| `BW_MAIL_RETRIES` / `BW_MAIL_RETRY_DELAY` | `3` / `30` | gönderim hatasında tekrar denemesi |

Container'ı hiç kullanmadan elle de çalıştırabilirsin:

```bash
cd app
python mailer.py --once               # şimdi bir mail at
python mailer.py --dry-run            # sadece raporu bas
python mailer.py --time 08:00 --tz Europe/Berlin
```

> `git fetch` başarısız olursa (ağ yok, private repo'ya erişim yok) mail yine
> gider: son `fetch` anındaki ref'lere göre rapor çıkarılır ve mailin başına
> "bu sayılar bayat olabilir" uyarısı eklenir. Private bir remote'u SSH ile
> fetch'lemen gerekiyorsa `docker/docker-compose.yml` içindeki `~/.ssh` mount'unu
> ve `GIT_SSH_COMMAND` satırını yorumdan çıkar.

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
