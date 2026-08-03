# Branch Watcher

Bir git deposunun current branch'ini bir target branch (varsayılan `origin/develop`)
ile kıyaslar; ahead/behind sayılarını, local commit'leri ve incoming commit'leri
gösterir. Terminalden ya da LAN'dan erişilebilen bir web arayüzünden kullanılabilir.

## Proje yapısı

```
branch-watcher/
├── app/                     # uygulama kodu
│   ├── branch_status.py
│   ├── mailer.py            # her sabah 09:15'te rapor maili atan servis
│   ├── logging_setup.py     # ortak logger (konsol + dönen log dosyası)
│   └── templates/
│       ├── status.html      # web arayüzü
│       └── email.html       # mail şablonu
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── .dockerignore
├── .env.example
├── requirements.txt
└── start.sh                 # Docker stack'ini build edip çalıştırır
```

## Docker ile çalıştırma (önerilen)

Her şey container'dan çalışacak şekilde paketlendi (git image içinde gelir;
host'ta Docker'dan başka bir şey kurman gerekmez):

```bash
cp .env.example .env
# .env'de aşağıdaki 5 alanı doldur, sonra:
./start.sh              # build edip ön planda çalıştırır
./start.sh -d           # arka planda (detached)
./start.sh down         # durdur ve kaldır
./start.sh logs -f      # logları takip et
./start.sh test-mail    # ayarları doğrula: hemen bir rapor maili at
./start.sh preview-mail # maili göndermeden terminale bas
```

### Doldurman gereken 5 alan

`.env` içinde sadece bunlar zorunlu; geri kalan her şey varsayılanıyla çalışır.

| alan | ne yazacaksın | örnek |
| --- | --- | --- |
| `BW_REPO` | izlenecek repo'nun **host'taki** yolu | `/home/kullanici/projem` |
| `BW_MAIL_TO` | raporun gideceği adres(ler), virgülle | `ben@firma.com, ekip@firma.com` |
| `BW_SMTP_HOST` | mail sunucusu | `smtp.gmail.com` |
| `BW_SMTP_USER` | gönderen hesabın adresi | `ben@gmail.com` |
| `BW_SMTP_PASS` | o hesabın **uygulama şifresi**, boşluksuz (normal şifre değil) | `abcdefghijklmnop` |

Varsayılanları: port `587` + `starttls` (Gmail için doğru), gönderim saati
`09:15` `Europe/Istanbul`, hedef branch `origin/develop`. `BW_MAIL_FROM` boş
bırakılırsa `BW_SMTP_USER` kullanılır. Uygulama şifresini nereden alacağın
aşağıdaki **"Gmail ile SMTP"** bölümünde adım adım anlatılıyor.

> `.env`'i **her değiştirdiğinde `./start.sh -d` çalıştır.** `./start.sh restart`
> container'ı yeniden yaratmadığı için `.env`'i yeniden okumaz, eski değerlerle
> devam eder.

> Kendi bilgilerini `.env`'e yaz, `.env.example`'a **değil** — `.env` gitignore'da
> ama `.env.example` git'e giriyor.

Stack iki servis ayağa kaldırır:

| servis | ne yapar |
| --- | --- |
| `branch-watcher` | web arayüzü — `http://localhost:BW_PORT` (varsayılan 9534) |
| `mailer` | her sabah `BW_MAIL_TIME`'da (varsayılan 09:15 Europe/Istanbul) rapor maili atar |

Sadece maili istiyorsan web'i hiç açmadan çalıştırabilirsin:

```bash
docker compose --project-directory . -f docker/docker-compose.yml up -d mailer
```

Her iki container da root değil **non-root `app` user'ı** olarak çalışır ve
hiçbir ekstra yetki (capability) istemez. Ağ tarafı sade bridge networking:
web arayüzü `BW_PORT` (varsayılan 9534) host'a publish edilir, yani
`http://localhost:9534` — Linux, macOS ve Windows'ta aynı şekilde çalışır.
Aynı ağdaki başka bir cihazdan bakmak istersen host'un LAN IP'sini kullan.

İzlenen repo `/repo`'ya mount edilir. Varsayılan olarak **read-write**, çünkü
`git fetch` `.git` içine yazmak zorunda (mail raporunun "behind" sayısı bugünkü
develop'a göre çıksın diye). Repo'ya hiç yazılmasın istiyorsan `.env`'de
`BW_REPO_MOUNT=ro` yap ve `BW_FETCH`/`BW_MAIL_FETCH`'i kapat. Loglar `branch-watcher-logs` adlı bir named
volume'a yazılır (non-root user sahipliğini koruyabilsin diye); konsola da
basıldığı için `./start.sh logs -f` ile canlı izleyebilirsin.

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
`BW_FETCH`, `BW_SERVE` ve `BW_MAIL_*` / `BW_SMTP_*`) `.env` dosyasından
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
   Google boşluklarla gösterir ama şifre aslında 16 karakter: `.env`'e yazarken
   **boşlukları sil**.

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
BW_SMTP_PASS=abcdefghijklmnop          # 2. adımdaki 16 haneli şifre, boşluksuz
BW_MAIL_FROM=kendi.adresin@gmail.com   # Gmail'de gönderen = hesabın kendisi
BW_MAIL_TO=ekip1@firma.com, ekip2@firma.com
```

> Boşlukları silersen hiçbir tırnağa gerek kalmaz — en temiz yol bu. Boşluklu
> bırakmak istersen tırnak içine al (`"abcd efgh ijkl mnop"`); tırnaklar
> okunurken kaldırılır. Genel kural: bir değerde **boşluktan sonra `#`** varsa
> (`pass #x`) mutlaka tırnak kullan, yoksa o kısım yorum sayılıp kırpılır.

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
| `BW_SMTP_HOST is empty` gibi bir liste | `.env` doldurulmamış, ya da doldurulup `./start.sh -d` ile yeniden başlatılmamış (`restart` .env'i yeniden okumaz). |
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

> `git fetch` başarısız olursa (ağ yok, anahtar yok) mail yine gider: son
> `fetch` anındaki ref'lere göre rapor çıkarılır ve mailin başına "bu sayılar
> bayat olabilir" uyarısı, sebebiyle birlikte eklenir. Yani hiçbir zaman sessizce
> yanlış bilgi almazsın.

### SSH ile fetch (`git@github.com:...` remote'ları)

Repo'yu SSH ile klonladıysan — ekipte olağan durum — container'ın her sabah
`git fetch` yapabilmesi için anahtarına ihtiyacı var. Bu **hazır ayarlı gelir**:
compose, `~/.ssh` dizinini mailer container'ına **read-only** mount eder ve
`GIT_SSH_COMMAND`'i ayarlar. Container bu dizine yazmaz, sadece okur.

Ek bir şey yapman gerekmiyor; şu durumlarda dokunman gerekir:

- **HTTPS remote kullanıyorsan** bu mount'a gerek yok, compose'daki satırı
  silebilirsin (public repo'da HTTPS fetch anahtarsız çalışır).
- **Anahtarın başka bir yerdeyse:** `.env`'de `BW_SSH_DIR=/başka/yol` ver.
- **Linux'ta kullanıcı uid'in 1000 değilse:** container `app` user'ı (uid 1000)
  anahtarını okuyamaz. Anahtarı ayrı bir klasöre kopyalayıp
  `sudo chown -R 1000:1000 <klasör>` yap ve `BW_SSH_DIR` ile onu göster.
  (macOS/Windows'ta Docker Desktop sahipliği kendisi eşlediği için sorun çıkmaz.)
- **Anahtarında passphrase varsa:** container şifreyi soramaz, fetch hemen hata
  verir (mail yine gider, bayat uyarısıyla). Passphrase'siz bir read-only deploy
  key kullan ya da `BW_MAIL_FETCH=false` yap.

## Loglama

Tüm modüller `app/logging_setup.py`'deki ortak logger'ı kullanır: her önemli
adım loglanır ve hatalar (ör. `git fetch`'in ya da mail gönderiminin
başarısız olması) `ERROR` seviyesinde yazılır. Loglar hem konsola
hem de dönen bir dosyaya (`branch_watcher.log`, ~1MB'da döner, 3 yedek) gider.

Ayarlar (env / `.env`):

- `BW_LOG_LEVEL` — `DEBUG` / `INFO` / `WARNING` / `ERROR` (varsayılan `INFO`)
- `BW_LOG_FILE` — log dosyası yolu (Docker'da `/app/logs/branch_watcher.log`'a mount edilir)
