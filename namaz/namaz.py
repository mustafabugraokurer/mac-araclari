#!/usr/bin/env python3
"""
Namaz — Mac menü çubuğu için Türkçe namaz vakitleri ve namaz takibi.

- Menü çubuğunda sıradaki vakit ve kalan süre: "Akşam 2:22".
- Tıklayınca günün altı vakti; vakte tıklayınca "kıldım" olarak işaretlenir.
- Vakitten önce, vakit girince ve (kılınmadıysa) vakit çıkmadan bildirim.
- Haftalık takip penceresi: son 7 günde hangi namazlar kılındı.
- Dünya genelinde 60 ülke / 200+ şehir; ülkeye göre önerilen hesaplama yöntemi.
- Vakitler internetsiz hesaplanır.

Gerekenler: pip install -r requirements.txt
"""
import datetime as dt
import json
import plistlib
import subprocess
import uuid
from pathlib import Path

import rumps

import dil
from dil import t

from sehirler import SEHIR_EN, ULKE_EN, ULKELER, sehir_bilgi
from vakit import ADLAR, VAKITLER, YONTEMLER, vakitler

try:
    from AppKit import (NSApplication, NSAttributedString, NSBezierPath, NSButton, NSColor,
                        NSFont,
                        NSFontAttributeName, NSForegroundColorAttributeName, NSImage,
                        NSImageSymbolConfiguration, NSMakeRect, NSPanel, NSTextField,
                        NSView)
    from Foundation import NSBundle, NSMakePoint, NSObject, NSProcessInfo, NSString
    HAS_APPKIT = True
except Exception:  # pragma: no cover
    HAS_APPKIT = False

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

APP_ID = "com.bugra.namaz"
DATA_DIR = Path.home() / "Library" / "Application Support" / "Namaz"
SETTINGS_FILE = DATA_DIR / "ayarlar.json"
TAKIP_FILE = DATA_DIR / "takip.json"
LOG_FILE = Path.home() / "Library" / "Logs" / "Namaz.log"
AGENT_FILE = Path.home() / "Library" / "LaunchAgents" / f"{APP_ID}.plist"

DEFAULTS = {
    "ulke": "Türkiye",
    "sehir": "İstanbul",
    "yontem": "oto",        # "oto": ülkeye göre önerilen
    "hanefi": "oto",        # "oto" / True / False
    "once_dk": 15,          # vakitten kaç dk önce haber versin (0: kapalı)
    "vakitte_bildir": True,
    "takip_hatirlat": True,  # kılınmadıysa vakit çıkmadan hatırlat
    "takip_dk": 30,
    "ses": False,
    "sadece_ikon": False,
    "dil": "oto",            # "oto" (Mac'in diline göre) / "tr" / "en"
}
ONCE_SECENEKLERI = [0, 5, 10, 15, 30, 45]
TAKIP_SECENEKLERI = [15, 30, 45, 60]
NAMAZLAR = ["imsak", "ogle", "ikindi", "aksam", "yatsi"]   # takip edilen beş vakit
NAMAZ_ADI = {"imsak": "Sabah", "ogle": "Öğle", "ikindi": "İkindi", "aksam": "Akşam",
             "yatsi": "Yatsı"}
TICK = 2
ACCENT_LIGHT, ACCENT_DARK = (0x8A, 0x5A, 0x12), (0xE0, 0xB0, 0x60)
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos",
         "Eylül", "Ekim", "Kasım", "Aralık"]
GUNLER = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
GUN_KISA = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
AYLAR_EN = ["January", "February", "March", "April", "May", "June", "July", "August",
            "September", "October", "November", "December"]
GUNLER_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
GUN_KISA_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
VAKIT_EN = {"imsak": "Fajr", "gunes": "Sunrise", "ogle": "Dhuhr", "ikindi": "Asr",
            "aksam": "Maghrib", "yatsi": "Isha"}
YONTEM_EN = {
    "diyanet": "Diyanet (Turkey)", "mwl": "Muslim World League", "isna": "ISNA (North America)",
    "misir": "Egypt", "ummulkura": "Umm al-Qura (Saudi Arabia)", "karachi": "Karachi (South Asia)",
    "korfez": "Gulf (UAE)", "kuveyt": "Kuwait", "katar": "Qatar", "singapur": "Singapore",
    "malezya": "Malaysia (JAKIM)", "endonezya": "Indonesia (Kemenag)", "fas": "Morocco",
    "fransa": "France (UOIF, 12°)", "rusya": "Russia",
}


# İngilizce karşılıklar (anahtar: Türkçe metin)
CEVIRI = {
    "{dk} dk": "{dk} min",
    "{sa} sa {dk} dk": "{sa} h {dk} min",
    "{sa} sa": "{sa} h",
    "Konum · {sehir}, {ulke}": "Location · {sehir}, {ulke}",
    "Hesaplama yöntemi · {y}": "Calculation method · {y}",
    "İnternetsiz hesaplanır · Kesin vakit için yerel takvim esastır":
        "Calculated offline · Your local official timetable takes precedence",
    "Kıldığın vakte tıkla, işaretlensin": "Click a prayer to mark it as prayed",
    "Haftalık takip": "Weekly tracker",
    "Konum": "Location",
    "Hesaplama yöntemi": "Calculation method",
    "İkindi: Hanefi (2 misli gölge)": "Asr: Hanafi (shadow length 2×)",
    "Vakitten önce haber ver": "Remind before prayer time",
    "Vakit girince bildir": "Notify at prayer time",
    "Kılınmadıysa vakit çıkmadan hatırlat": "Remind before time runs out if not prayed",
    "Bildirim sesi": "Notification sound",
    "Sadece ikon göster": "Show icon only",
    "Oturum açınca başlat": "Open at login",
    "Bildirimler": "Notifications",
    "Güneşin doğmasına": "Until sunrise",
    "Ülkeye göre (önerilen)": "By country (recommended)",
    "Kapalı": "Off",
    "{dk} dk kala": "{dk} min before",
    "Namaz'dan çık": "Quit Namaz",
    "Ülkeye göre (önerilen: {y})": "By country (recommended: {y})",
    "kapalı": "off",
    "İmsak vaktine": "Until Fajr",
    "{ad} ezanına": "Until {ad}",
    " · şu an": " · now",
    "{a} / {b} vakit kılındı": "{a} / {b} prayers done",
    "Bu seçenek uygulama Namaz.app olarak kurulduğunda çalışır.":
        "This option works when the app is installed as Namaz.app.",
    "{dk} dk önce": "{dk} min before",
    "Bugün kılınan: {a}/{b}": "Prayed today: {a}/{b}",
    "Bugün henüz vakit girmedi": "No prayer time has started yet today",
    " · sabah namazı": "",
    "Güneş doğuşuna kadar · {s}": "Until sunrise · {s}",
    "{ad} vakti girdi": "It's time for {ad}",
    "Bugün": "Today",
    "Güneşin doğmasına {n} dakika": "{n} minutes until sunrise",
    "Sabah namazının vakti {s} itibarıyla çıkıyor · {sehir}": "Fajr time ends at {s} · {sehir}",
    "{ad} vaktine kadar · {s}": "Until {ad} · {s}",
    "İmsak vaktine kadar · {s}": "Until Fajr · {s}",
    " · Kılınca menüden işaretle": " · Mark it in the menu when done",
    "{ad} namazının vakti çıkıyor": "{ad} time is running out",
    "{kalan} kaldı ({s}) · Kıldıysan menüden işaretle":
        "{kalan} left (until {s}) · Mark it in the menu if you prayed",
    "İmsak vaktine {n} dakika": "{n} minutes until Fajr",
    "{ad} ezanına {n} dakika": "{n} minutes until {ad}",
    "Namaz takibi · {a} – {b}": "Prayer tracker · {a} – {b}",
    "Bu hafta": "This week",
    "Bu haftada vakti giren namazların {oran}'i · kılınmayan: {n}":
        "{oran} of the prayers due this week · missed: {n}",
    "Kıldığın ya da kaçırdığın vakti işaretlemek için daireye tıkla":
        "Click a circle to mark a prayer as prayed or not",
}


def en() -> bool:
    return dil.kod() == "en"


def vakit_adi(k):
    return VAKIT_EN[k] if en() else ADLAR[k]


def namaz_adi(k):
    return VAKIT_EN[k] if en() else NAMAZ_ADI[k]


def ulke_adi(u):
    return ULKE_EN.get(u, u) if en() else u


def sehir_adi(s):
    return SEHIR_EN.get(s, s) if en() else s


def yontem_adi(kod):
    return YONTEM_EN.get(kod, YONTEMLER[kod]["ad"]) if en() else YONTEMLER[kod]["ad"]


def tarih_metni(g):
    if en():
        return f"{GUNLER_EN[g.weekday()]}, {AYLAR_EN[g.month - 1]} {g.day}"
    return f"{g.day} {AYLAR[g.month - 1]} {GUNLER[g.weekday()]}"


def kisa_tarih(g, yil=False):
    if en():
        return f"{AYLAR_EN[g.month - 1][:3]} {g.day}" + (f", {g.year}" if yil else "")
    return f"{g.day} {AYLAR[g.month - 1]}" + (f" {g.year}" if yil else "")


def gun_kisa(g):
    return f"{(GUN_KISA_EN if en() else GUN_KISA)[g.weekday()]} {g.day}"


def log(msg):
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
    except Exception:
        pass


def _oku(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _yaz(path, data):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        log(f"kaydedilemedi ({path.name}): {e}")


def load_settings():
    s = dict(DEFAULTS)
    s.update(_oku(SETTINGS_FILE, {}))
    if s["ulke"] not in ULKELER:
        s["ulke"] = DEFAULTS["ulke"]
    if s["sehir"] not in ULKELER[s["ulke"]]["sehirler"]:
        s["sehir"] = next(iter(ULKELER[s["ulke"]]["sehirler"]))
    if s["yontem"] != "oto" and s["yontem"] not in YONTEMLER:
        s["yontem"] = "oto"
    return s


def save_settings(s):
    _yaz(SETTINGS_FILE, s)


def kalan_metin(sn: float, kisa=False) -> str:
    dk = max(0, int(sn // 60) + (1 if sn % 60 else 0))   # yukarı yuvarla
    sa, dk = divmod(dk, 60)
    if kisa:
        return f"{sa}:{dk:02d}"
    if sa and dk:
        return t("{sa} sa {dk} dk", sa=sa, dk=dk)
    if sa:
        return t("{sa} sa", sa=sa)
    return t("{dk} dk", dk=dk)


def bundle_executable():
    if not HAS_APPKIT:
        return None
    b = NSBundle.mainBundle()
    if b.bundleIdentifier() and str(b.bundlePath()).endswith(".app"):
        return str(b.executablePath())
    return None


_RENK = {}


def accent():
    if "a" in _RENK:
        return _RENK["a"]

    def rgb(c):
        return NSColor.colorWithSRGBRed_green_blue_alpha_(c[0] / 255, c[1] / 255, c[2] / 255, 1)
    try:
        l, d = rgb(ACCENT_LIGHT), rgb(ACCENT_DARK)

        def provider(appearance):
            name = appearance.bestMatchFromAppearancesWithNames_(
                ["NSAppearanceNameAqua", "NSAppearanceNameDarkAqua"])
            return d if name and "Dark" in str(name) else l
        _RENK["a"] = NSColor.colorWithName_dynamicProvider_("NamazAccent", provider)
    except Exception:
        _RENK["a"] = NSColor.systemOrangeColor()
    return _RENK["a"]


class Notifier:
    def __init__(self):
        self.center = None
        if not bundle_executable():
            return
        try:
            from UserNotifications import UNUserNotificationCenter
            self.center = UNUserNotificationCenter.currentNotificationCenter()
            self.center.requestAuthorizationWithOptions_completionHandler_(
                2 | 4, lambda granted, err: log(f"bildirim izni: {bool(granted)}"))
        except Exception as e:
            log(f"UserNotifications kullanılamadı: {e}")

    def send(self, title, body, sound):
        if self.center is not None:
            try:
                from UserNotifications import (UNMutableNotificationContent,
                                               UNNotificationRequest, UNNotificationSound)
                c = UNMutableNotificationContent.alloc().init()
                c.setTitle_(title)
                c.setBody_(body)
                if sound:
                    c.setSound_(UNNotificationSound.defaultSound())
                req = UNNotificationRequest.requestWithIdentifier_content_trigger_(
                    str(uuid.uuid4()), c, None)
                self.center.addNotificationRequest_withCompletionHandler_(
                    req, lambda err: err and log(f"bildirim hatası: {err}"))
                return
            except Exception as e:
                log(f"bildirim gönderilemedi: {e}")
        t, b = title.replace('"', "'"), body.replace('"', "'")
        script = f'display notification "{b}" with title "{t}"'
        if sound:
            script += ' sound name "Glass"'
        subprocess.Popen(["osascript", "-e", script])


def agent_installed():
    return AGENT_FILE.exists()


def set_agent(enabled):
    exe = bundle_executable()
    if enabled:
        if not exe:
            return False
        AGENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with AGENT_FILE.open("wb") as f:
            plistlib.dump({"Label": APP_ID, "ProgramArguments": [exe], "RunAtLoad": True,
                           "KeepAlive": {"SuccessfulExit": False},
                           "ProcessType": "Interactive",
                           "StandardErrorPath": str(LOG_FILE)}, f)
    elif AGENT_FILE.exists():
        AGENT_FILE.unlink()
    return True


# ---------------------------------------------------------------- takip
class Takip:
    """Gün gün kılınan namazlar: {"2026-11-15": ["imsak", "ogle"]}"""

    def __init__(self):
        self.veri = _oku(TAKIP_FILE, {})

    def kilindi_mi(self, gun: dt.date, k: str) -> bool:
        return k in self.veri.get(gun.isoformat(), [])

    def degistir(self, gun: dt.date, k: str) -> bool:
        liste = self.veri.setdefault(gun.isoformat(), [])
        if k in liste:
            liste.remove(k)
            durum = False
        else:
            liste.append(k)
            durum = True
        sinir = (dt.date.today() - dt.timedelta(days=800)).isoformat()
        for g in [g for g in self.veri if g < sinir]:
            del self.veri[g]
        _yaz(TAKIP_FILE, self.veri)
        return durum

    def sayi(self, gun: dt.date) -> int:
        return len([k for k in self.veri.get(gun.isoformat(), []) if k in NAMAZLAR])


if HAS_APPKIT:
    class Hedef(NSObject):
        """NSButton için hedef: tıklanınca Python fonksiyonunu çağırır."""

        def tikla_(self, sender):
            fn = getattr(self, "fn", None)
            if fn is not None:
                try:
                    fn()
                except Exception as e:
                    log(f"düğme hatası: {e}")

    class TakipView(NSView):
        """7 gün × 5 vakit: dolu daire kılındı, boş daire kılınmadı, nokta: henüz değil.
        Dairelere tıklayınca o günün o vakti işaretlenir / işaret kaldırılır."""

        SOL, UST, SATIR = 70.0, 26.0, 30.0

        def isFlipped(self):
            return True

        def acceptsFirstMouse_(self, event):
            return True

        def mouseDown_(self, event):
            gunler = list(getattr(self, "gunler", []))
            fn = getattr(self, "tikla", None)
            if not gunler or fn is None:
                return
            pt = self.convertPoint_fromView_(event.locationInWindow(), None)
            sutun = (self.bounds().size.width - self.SOL) / len(gunler)
            i = int((pt.x - self.SOL) // sutun)
            j = int((pt.y - self.UST) // self.SATIR)
            if 0 <= i < len(gunler) and 0 <= j < len(NAMAZLAR) and pt.x >= self.SOL:
                gun = gunler[i][2] if len(gunler[i]) > 2 else None
                if gun is not None and gunler[i][1][j] != "gelecek":
                    fn(gun, NAMAZLAR[j])

        def drawRect_(self, rect):
            gunler = list(getattr(self, "gunler", []))     # [(etiket, [durum x5])]
            renk = getattr(self, "renk", None) or NSColor.systemOrangeColor()
            if not gunler:
                return
            sol, ust, satir = self.SOL, self.UST, self.SATIR
            b = self.bounds()
            sutun = (b.size.width - sol) / len(gunler)
            kucuk = {NSFontAttributeName: NSFont.systemFontOfSize_(12),
                     NSForegroundColorAttributeName: NSColor.secondaryLabelColor()}
            normal = {NSFontAttributeName: NSFont.systemFontOfSize_(13),
                      NSForegroundColorAttributeName: NSColor.labelColor()}
            for j, k in enumerate(NAMAZLAR):
                NSString.stringWithString_(namaz_adi(k)).drawAtPoint_withAttributes_(
                    NSMakePoint(0, ust + j * satir + 6), normal)
            for i, gun_bilgi in enumerate(gunler):
                etiket, durumlar = gun_bilgi[0], gun_bilgi[1]
                x = sol + i * sutun + sutun / 2
                s = NSString.stringWithString_(etiket)
                sz = s.sizeWithAttributes_(kucuk)
                s.drawAtPoint_withAttributes_(NSMakePoint(x - sz.width / 2, 2), kucuk)
                for j, d in enumerate(durumlar):
                    y = ust + j * satir + 15
                    if d == "gelecek":
                        r = NSMakeRect(x - 2.5, y - 2.5, 5, 5)
                        NSColor.tertiaryLabelColor().setFill()
                        NSBezierPath.bezierPathWithOvalInRect_(r).fill()
                        continue
                    r = NSMakeRect(x - 9, y - 9, 18, 18)
                    p = NSBezierPath.bezierPathWithOvalInRect_(r)
                    if d == "kilindi":
                        renk.setFill()
                        p.fill()
                        tik = NSBezierPath.bezierPath()
                        tik.moveToPoint_(NSMakePoint(x - 4.5, y + 0.5))
                        tik.lineToPoint_(NSMakePoint(x - 1.2, y + 3.8))
                        tik.lineToPoint_(NSMakePoint(x + 4.8, y - 3.5))
                        tik.setLineWidth_(2.0)
                        NSColor.whiteColor().setStroke()
                        tik.stroke()
                    else:
                        p.setLineWidth_(1.5)
                        NSColor.tertiaryLabelColor().setStroke()
                        p.stroke()


def _etiket(metin, boyut=13, kalin=False, ikincil=False):
    t = NSTextField.labelWithString_(metin)
    t.setFont_(NSFont.systemFontOfSize_weight_(boyut, 0.3) if kalin
               else NSFont.systemFontOfSize_(boyut))
    if ikincil:
        t.setTextColor_(NSColor.secondaryLabelColor())
    return t


# ---------------------------------------------------------------- uygulama
class NamazApp(rumps.App):
    def __init__(self):
        super().__init__("Namaz", title="Namaz", quit_button=None)
        self.s = load_settings()
        dil.ayarla(self.s.get("dil", "oto"), CEVIRI)
        self.takip = Takip()
        self.notifier = None
        self._activity = None
        self._header = None
        self._son = None
        self._gun = None
        self._v = {}
        self._dun = {}
        self._yarin = {}
        self._panel = None
        self.gonderilen = set()

        self.m_ozet = rumps.MenuItem("Namaz")
        self.m_liste = {k: rumps.MenuItem(vakit_adi(k), callback=self.vakit_tikla)
                        for k in VAKITLER}
        self.m_liste["gunes"].set_callback(None)
        self.m_ipucu = rumps.MenuItem(t("Kıldığın vakte tıkla, işaretlensin"))
        self.m_haftalik = rumps.MenuItem(t("Haftalık takip"), callback=self._haftalik_menu,
                                         key="t")

        self.m_konum = rumps.MenuItem(t("Konum"))
        self._konum = []            # [(ülke, menü, {şehir: menü})]
        sira = sorted(ULKELER, key=lambda u: self._sirala(ulke_adi(u)))
        sira.remove("Türkiye")
        for i, ulke in enumerate(["Türkiye"] + sira):
            m_u = rumps.MenuItem(ulke_adi(ulke))
            sehirler = {}
            for sehir in sorted(ULKELER[ulke]["sehirler"], key=lambda x: self._sirala(sehir_adi(x))):
                m_s = rumps.MenuItem(sehir_adi(sehir), callback=self._sehir_cb(ulke, sehir))
                m_u.add(m_s)
                sehirler[sehir] = m_s
            self.m_konum.add(m_u)
            self._konum.append((ulke, m_u, sehirler))
            if i == 0:
                self.m_konum.add(None)

        self.m_yontem = rumps.MenuItem(t("Hesaplama yöntemi"))
        self._yontemler = {"oto": rumps.MenuItem(t("Ülkeye göre (önerilen)"),
                                                 callback=self._yontem_cb("oto"))}
        self.m_yontem.add(self._yontemler["oto"])
        self.m_yontem.add(None)
        for kod in YONTEMLER:
            self._yontemler[kod] = rumps.MenuItem(yontem_adi(kod), callback=self._yontem_cb(kod))
            self.m_yontem.add(self._yontemler[kod])
        self.m_hanefi = rumps.MenuItem(t("İkindi: Hanefi (2 misli gölge)"),
                                       callback=self.hanefi_degistir)

        self.m_once = rumps.MenuItem(t("Vakitten önce haber ver"))
        self._once = {}
        for dk in ONCE_SECENEKLERI:
            self._once[dk] = rumps.MenuItem(t("Kapalı") if dk == 0 else t("{dk} dk önce", dk=dk),
                                            callback=self._once_cb(dk))
            self.m_once.add(self._once[dk])
        self.m_vakitte = rumps.MenuItem(t("Vakit girince bildir"), callback=self.vakitte_degistir)
        self.m_takip_h = rumps.MenuItem(t("Kılınmadıysa vakit çıkmadan hatırlat"))
        self._takip_m = {0: rumps.MenuItem(t("Kapalı"), callback=self._takip_cb(0))}
        self.m_takip_h.add(self._takip_m[0])
        for dk in TAKIP_SECENEKLERI:
            self._takip_m[dk] = rumps.MenuItem(t("{dk} dk kala", dk=dk), callback=self._takip_cb(dk))
            self.m_takip_h.add(self._takip_m[dk])
        self.m_ses = rumps.MenuItem(t("Bildirim sesi"), callback=self.ses_degistir)
        self.m_ikon = rumps.MenuItem(t("Sadece ikon göster"), callback=self.ikon_degistir)
        self.m_giris = rumps.MenuItem(t("Oturum açınca başlat"), callback=self.giris_degistir)
        self.m_dil = rumps.MenuItem("Dil / Language")
        for ad in ("Sistem / System", "Türkçe", "English"):
            self.m_dil.add(rumps.MenuItem(ad, callback=self.dil_sec))
        self.m_bilgi = rumps.MenuItem("")

        self.m_ayarlar = rumps.MenuItem(t("Bildirimler"))
        for m in (self.m_once, self.m_vakitte, self.m_takip_h, self.m_ses):
            self.m_ayarlar.add(m)

        self.menu = [self.m_ozet, None, *[self.m_liste[k] for k in VAKITLER], self.m_ipucu,
                     self.m_haftalik, None,
                     self.m_konum, self.m_yontem, self.m_hanefi, self.m_ayarlar,
                     self.m_ikon, self.m_giris, self.m_dil, None, self.m_bilgi,
                     rumps.MenuItem(t("Namaz'dan çık"), callback=self.cik, key="q")]
        self._hesapla()
        self._isaretler()
        self.timer = rumps.Timer(self.tick, TICK)
        self.timer.start()

    @staticmethod
    def _sirala(x):
        tablo = str.maketrans({"Ç": "Cz", "ç": "cz", "Ğ": "Gz", "ğ": "gz", "İ": "Iz",
                               "ı": "hz", "Ö": "Oz", "ö": "oz", "Ş": "Sz", "ş": "sz",
                               "Ü": "Uz", "ü": "uz"})
        return x.translate(tablo).lower()

    # ---- hesap
    def yontem(self) -> str:
        y = self.s["yontem"]
        return ULKELER[self.s["ulke"]]["yontem"] if y == "oto" else y

    def hanefi(self) -> bool:
        h = self.s["hanefi"]
        return ULKELER[self.s["ulke"]]["hanefi"] if h == "oto" else bool(h)

    def tz(self):
        _, _, tz = sehir_bilgi(self.s["ulke"], self.s["sehir"])
        try:
            return ZoneInfo(tz) if ZoneInfo else None
        except Exception:
            return None

    def simdi(self) -> dt.datetime:
        """Seçili şehrin yerel saati (saat dilimi bilgisi olmadan)."""
        tz = self.tz()
        if tz is None:
            return dt.datetime.now()
        return dt.datetime.now(tz).replace(tzinfo=None)

    def _fark(self, gun: dt.date) -> float:
        tz = self.tz()
        if tz is None:
            off = dt.datetime.now().astimezone().utcoffset()
        else:
            off = dt.datetime.combine(gun, dt.time(12)).replace(tzinfo=tz).utcoffset()
        return off.total_seconds() / 3600 if off else 3.0

    def _gun_vakitleri(self, gun):
        enlem, boylam, _ = sehir_bilgi(self.s["ulke"], self.s["sehir"])
        return vakitler(gun, enlem, boylam, self._fark(gun),
                        yontem=self.yontem(), hanefi=self.hanefi())

    def _hesapla(self):
        bugun = self.simdi().date()
        self._v = self._gun_vakitleri(bugun)
        self._dun = self._gun_vakitleri(bugun - dt.timedelta(days=1))
        self._yarin = self._gun_vakitleri(bugun + dt.timedelta(days=1))
        self._gun = (bugun, self.s["ulke"], self.s["sehir"], self.yontem(), self.hanefi())
        log(f"{self.s['sehir']} ({self.s['ulke']}, {YONTEMLER[self.yontem()]['ad']}"
            f"{', Hanefi' if self.hanefi() else ''}) {bugun}: " +
            " ".join(f"{k}={self._v[k]:%H:%M}" for k in VAKITLER))

    def _simdiki_sonraki(self, now):
        simdiki = None
        for k in VAKITLER:
            if now >= self._v[k]:
                simdiki = k
        for k in VAKITLER:
            if self._v[k] > now:
                return simdiki, k, self._v[k]
        return simdiki, "imsak", self._yarin["imsak"]

    def _takip_gunu(self, now) -> dt.date:
        """İmsaktan önce yatsıyı işaretlemek dünün yatsısıdır."""
        if now < self._v["imsak"]:
            return now.date() - dt.timedelta(days=1)
        return now.date()

    # ---- yaşam döngüsü
    def _ilk(self):
        if self.notifier is not None:
            return
        self.notifier = Notifier()
        if HAS_APPKIT:
            try:
                self._activity = NSProcessInfo.processInfo() \
                    .beginActivityWithOptions_reason_(0x00EFFFFF, "Namaz vakitlerini izliyor")
            except Exception:
                pass
            self._header_kur()
        log("Namaz başladı")

    def _header_kur(self):
        try:
            W, H = 290, 92
            v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
            ust = _etiket("", boyut=12, ikincil=True)
            ust.setFrame_(NSMakeRect(14, 70, W - 28, 16))
            orta = _etiket("", boyut=12)
            orta.setFrame_(NSMakeRect(14, 52, W - 28, 16))
            buyuk = NSTextField.labelWithString_("")
            buyuk.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(24, 0.4))
            buyuk.setTextColor_(accent())
            buyuk.setFrame_(NSMakeRect(14, 22, W - 28, 30))
            alt = _etiket("", boyut=12, ikincil=True)
            alt.setFrame_(NSMakeRect(14, 4, W - 28, 16))
            for x in (ust, orta, buyuk, alt):
                v.addSubview_(x)
            self.m_ozet._menuitem.setView_(v)
            self._header = (ust, orta, buyuk, alt)
        except Exception as e:
            log(f"başlık kurulamadı: {e}")

    # ---- ekran
    def _isaretler(self):
        s = self.s
        for ulke, m_u, sehirler in self._konum:
            m_u.state = ulke == s["ulke"]
            for sehir, m_s in sehirler.items():
                m_s.state = ulke == s["ulke"] and sehir == s["sehir"]
        for dk, item in self._once.items():
            item.state = dk == s["once_dk"]
        for dk, item in self._takip_m.items():
            item.state = (not s["takip_hatirlat"]) if dk == 0 else \
                (s["takip_hatirlat"] and dk == s["takip_dk"])
        oneri = yontem_adi(ULKELER[s["ulke"]]["yontem"])
        for kod, item in self._yontemler.items():
            if kod == "oto":
                item.title = t("Ülkeye göre (önerilen: {y})", y=oneri)
                item.state = s["yontem"] == "oto"
            else:
                item.state = s["yontem"] == kod
        self.m_konum.title = t("Konum · {sehir}, {ulke}", sehir=sehir_adi(s["sehir"]),
                               ulke=ulke_adi(s["ulke"]))
        self.m_yontem.title = t("Hesaplama yöntemi · {y}", y=yontem_adi(self.yontem()))
        self.m_hanefi.state = self.hanefi()
        self.m_once.title = (t("Vakitten önce haber ver") + " · " +
                             (t("{dk} dk", dk=s["once_dk"]) if s["once_dk"] else t("kapalı")))
        self.m_takip_h.title = (t("Kılınmadıysa vakit çıkmadan hatırlat") + " · " +
                                (t("{dk} dk kala", dk=s["takip_dk"]) if s["takip_hatirlat"]
                                 else t("kapalı")))
        for item in self.m_dil.values():
            item.state = item.title == {"tr": "Türkçe", "en": "English"}.get(
                s.get("dil"), "Sistem / System")
        self.m_vakitte.state = bool(s["vakitte_bildir"])
        self.m_ses.state = bool(s["ses"])
        self.m_ikon.state = bool(s["sadece_ikon"])
        self.m_giris.state = agent_installed()
        self.m_bilgi.title = t("İnternetsiz hesaplanır · Kesin vakit için yerel takvim esastır")

    def _ekran(self, now):
        simdiki, sonraki, zaman = self._simdiki_sonraki(now)
        kalan = (zaman - now).total_seconds()
        ad = vakit_adi(sonraki)
        if sonraki == "gunes":
            hedef = t("Güneşin doğmasına")
        elif sonraki == "imsak":
            hedef = t("İmsak vaktine")
        else:
            hedef = t("{ad} ezanına", ad=ad)
        bugun = now.date()
        takip_gun = self._takip_gunu(now)
        kilinan = self.takip.sayi(bugun)
        girmis = sum(1 for k in NAMAZLAR if self._v[k] <= now)
        if self._header:
            ust, orta, buyuk, alt = self._header
            ust.setStringValue_(f"{sehir_adi(self.s['sehir'])} · {tarih_metni(bugun)}")
            orta.setStringValue_(hedef)
            buyuk.setStringValue_(kalan_metin(kalan))
            alt.setStringValue_(t("Bugün kılınan: {a}/{b}", a=kilinan, b=girmis) if girmis
                                else t("Bugün henüz vakit girmedi"))
        for k in VAKITLER:
            item = self.m_liste[k]
            etiket = vakit_adi(k) + (t(" · sabah namazı") if k == "imsak" else "")
            if k == simdiki:
                etiket += t(" · şu an")
            metin = f"{etiket}\t{self._v[k]:%H:%M}"
            self._liste_yaz(item, metin, k == simdiki,
                            k == sonraki and zaman.date() == bugun,
                            gecti=self._v[k] <= now and k != simdiki)
            if k in NAMAZLAR:
                gun = takip_gun if (k == "yatsi" and takip_gun != bugun) else bugun
                item.state = self.takip.kilindi_mi(gun, k)
        bar = "" if self.s["sadece_ikon"] else f"{ad} {kalan_metin(kalan, kisa=True)}"
        yakin = kalan <= max(self.s["once_dk"], 1) * 60
        self._menu_cubugu(bar, yakin)

    def _liste_yaz(self, item, metin, kalin, vurgulu, gecti):
        try:
            from AppKit import (NSMutableParagraphStyle, NSParagraphStyleAttributeName,
                                NSTextTab)
            p = NSMutableParagraphStyle.alloc().init()
            p.setTabStops_([NSTextTab.alloc().initWithTextAlignment_location_options_(
                2, 250, {})])
            renk = (accent() if vurgulu else NSColor.secondaryLabelColor() if gecti
                    else NSColor.labelColor())
            attrs = {NSFontAttributeName: NSFont.monospacedDigitSystemFontOfSize_weight_(
                13, 0.4 if (kalin or vurgulu) else 0.0),
                NSForegroundColorAttributeName: renk,
                NSParagraphStyleAttributeName: p}
            anahtar = (metin, kalin, vurgulu, gecti)
            if getattr(item, "_son_baslik", None) != anahtar:
                item._son_baslik = anahtar
                item._menuitem.setAttributedTitle_(
                    NSAttributedString.alloc().initWithString_attributes_(metin, attrs))
        except Exception:
            item.title = metin

    def _menu_cubugu(self, metin, yakin):
        anahtar = (metin, yakin)
        if anahtar == self._son:
            return
        self._son = anahtar
        try:
            b = self._nsapp.nsstatusitem.button()
            if getattr(self, "_son_ikon", None) != yakin:
                self._son_ikon = yakin
                img = NSImage.imageWithSystemSymbolName_accessibilityDescription_("moon",
                                                                                 "Namaz")
                if img is not None:
                    if yakin:
                        cfg = NSImageSymbolConfiguration.configurationWithHierarchicalColor_(
                            accent())
                        img = img.imageWithSymbolConfiguration_(cfg) or img
                        img.setTemplate_(False)
                    else:
                        img.setTemplate_(True)
                b.setImage_(img)
            b.setImagePosition_(2 if metin else 1)
            attrs = {NSFontAttributeName: NSFont.monospacedDigitSystemFontOfSize_weight_(
                13, 0.3 if yakin else 0.0)}
            if yakin:
                attrs[NSForegroundColorAttributeName] = accent()
            b.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(
                f" {metin}" if metin else "", attrs))
        except Exception:
            self.title = metin or "Namaz"

    # ---- zamanlayıcı
    def tick(self, _):
        self._ilk()
        now = self.simdi()
        if self._gun != (now.date(), self.s["ulke"], self.s["sehir"], self.yontem(),
                         self.hanefi()):
            self._hesapla()
            self.gonderilen = {x for x in self.gonderilen if x[0] >= now.date()}
        self._bildirimler(now)
        self._ekran(now)

    def _bildirimler(self, now):
        if self.notifier is None:
            return
        gun = now.date()
        sehir = sehir_adi(self.s["sehir"])
        for i, k in enumerate(VAKITLER):
            vt = self._v[k]
            ad = vakit_adi(k)
            once = self.s["once_dk"]
            if once and vt - dt.timedelta(minutes=once) <= now < vt and \
                    (gun, k, "once") not in self.gonderilen:
                self.gonderilen.add((gun, k, "once"))
                if (vt - now).total_seconds() > 60:
                    if k == "gunes":
                        baslik = t("Güneşin doğmasına {n} dakika", n=once)
                        govde = t("Sabah namazının vakti {s} itibarıyla çıkıyor · {sehir}",
                                  s=f"{vt:%H:%M}", sehir=sehir)
                    elif k == "imsak":
                        baslik = t("İmsak vaktine {n} dakika", n=once)
                        govde = f"{sehir} · {vt:%H:%M}"
                    else:
                        baslik = t("{ad} ezanına {n} dakika", ad=ad, n=once)
                        govde = f"{sehir} · {vt:%H:%M}"
                    self.notifier.send(baslik, govde, self.s["ses"])
                    log(f"bildirim: {baslik}")
            if self.s["vakitte_bildir"] and k != "gunes" and \
                    vt <= now < vt + dt.timedelta(minutes=2) and \
                    (gun, k, "vakit") not in self.gonderilen:
                self.gonderilen.add((gun, k, "vakit"))
                nk = VAKITLER[i + 1] if i + 1 < len(VAKITLER) else None
                if nk == "gunes":
                    govde = t("Güneş doğuşuna kadar · {s}", s=f"{self._v['gunes']:%H:%M}")
                elif nk:
                    govde = t("{ad} vaktine kadar · {s}", ad=vakit_adi(nk),
                              s=f"{self._v[nk]:%H:%M}")
                else:
                    govde = t("İmsak vaktine kadar · {s}", s=f"{self._yarin['imsak']:%H:%M}")
                self.notifier.send(t("{ad} vakti girdi", ad=ad),
                                   govde + t(" · Kılınca menüden işaretle"),
                                   self.s["ses"])
                log(f"bildirim: {ad} vakti girdi")
        # takip: kılınmadıysa vakit çıkmadan hatırlat (yatsı hariç: imsaka denk gelir)
        if self.s["takip_hatirlat"]:
            bitis = {"imsak": "gunes", "ogle": "ikindi", "ikindi": "aksam", "aksam": "yatsi"}
            for k, son in bitis.items():
                cikis = self._v[son]
                h = cikis - dt.timedelta(minutes=self.s["takip_dk"])
                if h <= now < cikis and self._v[k] <= now and \
                        not self.takip.kilindi_mi(gun, k) and \
                        (gun, k, "takip") not in self.gonderilen:
                    self.gonderilen.add((gun, k, "takip"))
                    kalan = kalan_metin((cikis - now).total_seconds())
                    self.notifier.send(t("{ad} namazının vakti çıkıyor", ad=namaz_adi(k)),
                                       t("{kalan} kaldı ({s}) · Kıldıysan menüden işaretle",
                                         kalan=kalan, s=f"{cikis:%H:%M}"),
                                       self.s["ses"])
                    log(f"bildirim: {NAMAZ_ADI[k]} vakti çıkıyor")

    # ---- takip eylemleri
    def vakit_tikla(self, sender):
        k = next((k for k, m in self.m_liste.items() if m is sender), None)
        if k not in NAMAZLAR:
            return
        now = self.simdi()
        gun = now.date()
        if k == "yatsi" and self._takip_gunu(now) != gun:
            gun = self._takip_gunu(now)       # gece yarısından sonra: dünün yatsısı
        elif self._v[k] > now:
            log(f"takip: {NAMAZ_ADI[k]} vakti henüz girmedi ({self._v[k]:%H:%M})")
            return
        durum = self.takip.degistir(gun, k)
        log(f"takip: {gun} {NAMAZ_ADI[k]} {'kılındı' if durum else 'geri alındı'}")
        self.tick(None)
        if self._panel is not None and self._panel.isVisible():
            self.haftalik_ac(None)

    def haftalik_ac(self, _):
        if not HAS_APPKIT:
            return
        try:
            now = self.simdi()
            bugun = now.date()
            ofset = getattr(self, "_hafta_ofset", 0)
            pazartesi = bugun - dt.timedelta(days=bugun.weekday()) + dt.timedelta(weeks=ofset)
            gunler = []
            kilinan = toplam = 0
            for i in range(7):
                g = pazartesi + dt.timedelta(days=i)
                durumlar = []
                for k in NAMAZLAR:
                    if g > bugun or (g == bugun and self._v[k] > now):
                        durumlar.append("gelecek")
                        continue
                    ok = self.takip.kilindi_mi(g, k)
                    durumlar.append("kilindi" if ok else "yok")
                    toplam += 1
                    kilinan += 1 if ok else 0
                etiket = t("Bugün") if g == bugun else gun_kisa(g)
                gunler.append((etiket, durumlar, g))

            W, H = 560, 320
            if self._panel is None:
                p = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                    NSMakeRect(0, 0, W, H), 1 | 2, 2, False)
                p.setReleasedWhenClosed_(False)
                p.setHidesOnDeactivate_(False)
                p.setLevel_(3)
                p.setCollectionBehavior_(1 | 256)
                self._panel = p
            p = self._panel
            pazar = pazartesi + dt.timedelta(days=6)
            p.setTitle_(t("Namaz takibi · {a} – {b}", a=kisa_tarih(pazartesi),
                          b=kisa_tarih(pazar, yil=True)))
            icerik = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))

            # hafta gezinme: ‹  Bu hafta  ›
            self._hedefler = []

            def dugme(baslik, x, w, fn, etkin=True):
                hd = Hedef.alloc().init()
                hd.fn = fn
                self._hedefler.append(hd)
                b = NSButton.alloc().initWithFrame_(NSMakeRect(x, H - 42, w, 26))
                b.setTitle_(baslik)
                b.setBezelStyle_(1)
                b.setTarget_(hd)
                b.setAction_("tikla:")
                b.setEnabled_(etkin)
                icerik.addSubview_(b)

            dugme("‹", W - 170, 36, lambda: self._hafta_git(-1))
            dugme(t("Bu hafta"), W - 132, 90, lambda: self._hafta_git(0, mutlak=True),
                  etkin=ofset != 0)
            dugme("›", W - 40, 36, lambda: self._hafta_git(+1), etkin=ofset < 0)

            yuzde = round(100 * kilinan / toplam) if toplam else None
            oran = (f"{yuzde}%" if en() else f"%{yuzde}") if toplam else "—"
            b1 = _etiket(t("{a} / {b} vakit kılındı", a=kilinan, b=toplam), boyut=20, kalin=True)
            b1.setTextColor_(accent())
            b1.setFrame_(NSMakeRect(20, H - 44, 330, 26))
            b2 = _etiket(t("Bu haftada vakti giren namazların {oran}'i · kılınmayan: {n}",
                           oran=oran, n=toplam - kilinan), boyut=12, ikincil=True)
            b2.setFrame_(NSMakeRect(20, H - 64, W - 40, 16))
            b3 = _etiket(t("Kıldığın ya da kaçırdığın vakti işaretlemek için daireye tıkla"),
                         boyut=11, ikincil=True)
            b3.setFrame_(NSMakeRect(20, 12, W - 40, 14))
            tv = TakipView.alloc().initWithFrame_(NSMakeRect(20, 34, W - 40, H - 108))
            tv.gunler, tv.renk = gunler, accent()
            tv.tikla = self._takip_tikla
            for x in (b1, b2, b3, tv):
                icerik.addSubview_(x)
            p.setContentView_(icerik)
            if not p.isVisible():
                p.center()
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            p.makeKeyAndOrderFront_(None)
        except Exception as e:
            log(f"haftalık takip açılamadı: {e}")

    def _hafta_git(self, adim, mutlak=False):
        self._hafta_ofset = adim if mutlak else min(0, getattr(self, "_hafta_ofset", 0) + adim)
        self.haftalik_ac(None)

    def _haftalik_menu(self, _):
        self._hafta_ofset = 0
        self.haftalik_ac(None)

    def _takip_tikla(self, gun, k):
        """Haftalık tablodan işaretleme (geçmiş günler dahil)."""
        durum = self.takip.degistir(gun, k)
        log(f"takip (tablo): {gun} {NAMAZ_ADI[k]} {'kılındı' if durum else 'geri alındı'}")
        self.tick(None)
        self.haftalik_ac(None)

    # ---- menü eylemleri
    def _degis(self, k, v):
        self.s[k] = v
        save_settings(self.s)
        self._son = None
        self._isaretler()
        self.tick(None)

    def _sehir_cb(self, ulke, sehir):
        def cb(_):
            self.s["ulke"] = ulke
            self._degis("sehir", sehir)
        return cb

    def _yontem_cb(self, kod):
        def cb(_):
            self._degis("yontem", kod)
        return cb

    def _once_cb(self, dk):
        def cb(_):
            self._degis("once_dk", dk)
        return cb

    def _takip_cb(self, dk):
        def cb(_):
            if dk == 0:
                self._degis("takip_hatirlat", False)
            else:
                self.s["takip_hatirlat"] = True
                self._degis("takip_dk", dk)
        return cb

    def hanefi_degistir(self, _):
        self._degis("hanefi", not self.hanefi())

    def vakitte_degistir(self, _):
        self._degis("vakitte_bildir", not self.s["vakitte_bildir"])

    def ses_degistir(self, _):
        self._degis("ses", not self.s["ses"])

    def ikon_degistir(self, _):
        self._degis("sadece_ikon", not self.s["sadece_ikon"])

    def giris_degistir(self, _):
        if not set_agent(not agent_installed()):
            rumps.alert("Namaz", t("Bu seçenek uygulama Namaz.app olarak kurulduğunda çalışır."))
        self._isaretler()

    def dil_sec(self, sender):
        yeni = {"Türkçe": "tr", "English": "en"}.get(sender.title, "oto")
        if yeni == self.s.get("dil", "oto"):
            return
        self.s["dil"] = yeni
        save_settings(self.s)
        log(f"dil değişti: {yeni}, yeniden başlatılıyor")
        dil.yeniden_baslat(agent_installed())

    def cik(self, _):
        log("Namaz kapatıldı")
        rumps.quit_application()


if __name__ == "__main__":
    NamazApp().run()
