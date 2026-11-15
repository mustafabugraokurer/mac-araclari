#!/usr/bin/env python3
"""
Denge — Mac menü çubuğu için Türkçe "kalk ve su iç" hatırlatıcısı.

Hareket ve Su tek uygulamada:
- Menü çubuğunda sandalye ikonu + kalkmaya kalan süre, damla + içilen bardak.
- 30 dakika oturunca ekranda uyarı: Kalktım (mola başlar) / 5 dk / 15 dk ertele.
- Belirli aralıklarla su hatırlatması: İçtim / 15 dk ertele / Bu sefer atla.
- İki hatırlatma birkaç dakika arayla denk gelirse tek uyarıda birleşir.
- Mikrofon kullanılırken (toplantı) uyarılar bir süre bekletilir.
- Haftalık istatistik penceresi (⌘I).
- Boşta kalma süresi Quartz ile ölçülür; ayrı program çalıştırılmaz.

Gerekenler: pip install -r requirements.txt
"""
import ctypes
import datetime as dt
import json
import plistlib
import struct
import subprocess
import time
import uuid
from pathlib import Path

import rumps

try:  # macOS yerel arayüz parçaları (yoksa sade metin moduna düşer)
    from AppKit import (NSApplication, NSAttributedString, NSBezierPath,
                        NSBox, NSButton, NSColor, NSFont, NSFontAttributeName,
                        NSForegroundColorAttributeName, NSImage,
                        NSImageSymbolConfiguration, NSMakeRect,
                        NSMutableAttributedString, NSPanel,
                        NSProgressIndicator, NSTextAttachment, NSTextField,
                        NSView)
    from Foundation import NSBundle, NSMakePoint, NSObject, NSProcessInfo, NSString
    HAS_APPKIT = True
except Exception:  # pragma: no cover
    HAS_APPKIT = False

# ---------------------------------------------------------------- sabitler
APP_ID = "com.bugra.denge"
DATA_DIR = Path.home() / "Library" / "Application Support" / "Denge"
SETTINGS_FILE = DATA_DIR / "ayarlar.json"
DAYS_FILE = DATA_DIR / "gunluk.json"
OLD_SETTINGS = Path.home() / "Library" / "Application Support" / "Hareket" / "ayarlar.json"
LOG_FILE = Path.home() / "Library" / "Logs" / "Denge.log"
AGENT_FILE = Path.home() / "Library" / "LaunchAgents" / f"{APP_ID}.plist"

DEFAULTS = {
    # hareket
    "sure_dk": 30,          # kaç dakika oturunca uyarsın
    "mola_dk": 3,           # kaç dakika boşta kalınca doğal mola sayılsın
    "kalkma_dk": 5,         # "Kalktım" sonrası mola süresi
    # su
    "su_acik": True,
    "su_hedef_ml": 2000,
    "bardak_ml": 250,
    "su_aralik_dk": 45,
    # genel
    "toplanti_sessiz": True,  # mikrofon açıkken uyarıları beklet
    "ses": True,
    "sadece_ikon": False,
}
SURE_SECENEKLERI = [20, 30, 45, 60]
MOLA_SECENEKLERI = [2, 3, 5]
KALKMA_SECENEKLERI = [2, 5, 10]
HEDEF_SECENEKLERI = [1500, 2000, 2500, 3000]
BARDAK_SECENEKLERI = [200, 250, 300, 500]
ARALIK_SECENEKLERI = [30, 45, 60, 90]

HAREKET_LIGHT, HAREKET_DARK = (0x2F, 0x7D, 0x6D), (0x6C, 0xC4, 0xB0)
SU_LIGHT, SU_DARK = (0x2F, 0x6F, 0xB8), (0x6A, 0xA6, 0xE8)

TICK = 1             # ekran güncelleme (sn)
IDLE_EVERY = 5       # boşta kalma kontrolü (sn)
SLEEP_GAP = 300      # bu kadar sn tick gelmezse Mac uyumuş say
YAKIN = 5 * 60       # iki hatırlatma bu kadar yakınsa birleştir
TOPLANTI_BEKLE = 60  # mikrofon açıkken kaç sn sonra tekrar bak
TOPLANTI_EN_FAZLA = 60 * 60  # en fazla bu kadar beklet, sonra yine de uyar
GUNLER = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]


# ---------------------------------------------------------------- yardımcılar
def log(msg: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
    except Exception:
        pass


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        log(f"kaydedilemedi ({path.name}): {e}")


def load_settings() -> dict:
    s = dict(DEFAULTS)
    if SETTINGS_FILE.exists():
        s.update(_read_json(SETTINGS_FILE, {}))
    else:  # Hareket'ten geçiş: eski ayarları al
        eski = _read_json(OLD_SETTINGS, {})
        for k in ("sure_dk", "mola_dk", "kalkma_dk", "ses", "sadece_ikon"):
            if k in eski:
                s[k] = eski[k]
        if eski.get("gun") == dt.date.today().isoformat() and eski.get("bugun_kalkis"):
            gunler = _read_json(DAYS_FILE, {})
            gunler.setdefault(eski["gun"], {})["kalkis"] = int(eski["bugun_kalkis"])
            _write_json(DAYS_FILE, gunler)
        if eski:
            log("Hareket ayarları Denge'ye aktarıldı")
        _write_json(SETTINGS_FILE, s)
    return s


def idle_seconds() -> float:
    """Son klavye/fare hareketinden bu yana geçen süre (sn)."""
    try:
        from Quartz import CGEventSourceSecondsSinceLastEventType
        try:
            from Quartz import kCGAnyInputEventType as ANY
        except Exception:
            ANY = 0xFFFFFFFF
        return float(CGEventSourceSecondsSinceLastEventType(1, ANY))  # 1: HID durumu
    except Exception:
        pass
    try:  # yedek yol (daha ağır)
        import re
        out = subprocess.run(["ioreg", "-c", "IOHIDSystem"],
                             capture_output=True, text=True, timeout=3).stdout
        m = re.search(r'"HIDIdleTime" = (\d+)', out)
        return int(m.group(1)) / 1e9 if m else 0.0
    except Exception:
        return 0.0


# ---- mikrofon kullanımda mı (CoreAudio, ctypes ile)
class _PropAddr(ctypes.Structure):
    _fields_ = [("mSelector", ctypes.c_uint32), ("mScope", ctypes.c_uint32),
                ("mElement", ctypes.c_uint32)]


def _fourcc(s: str) -> int:
    return struct.unpack(">I", s.encode("ascii"))[0]


_CA = {}


def mikrofon_acik() -> bool:
    """Varsayılan giriş aygıtı herhangi bir uygulama tarafından kullanılıyor mu."""
    try:
        ca = _CA.get("lib")
        if ca is None:
            ca = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
            ca.AudioObjectGetPropertyData.restype = ctypes.c_int32
            _CA["lib"] = ca
        dev = ctypes.c_uint32(0)
        size = ctypes.c_uint32(4)
        addr = _PropAddr(_fourcc("dIn "), _fourcc("glob"), 0)
        if ca.AudioObjectGetPropertyData(1, ctypes.byref(addr), 0, None,
                                         ctypes.byref(size), ctypes.byref(dev)) != 0:
            return False
        if not dev.value:
            return False
        calisiyor = ctypes.c_uint32(0)
        size = ctypes.c_uint32(4)
        addr = _PropAddr(_fourcc("gone"), _fourcc("glob"), 0)
        if ca.AudioObjectGetPropertyData(dev.value, ctypes.byref(addr), 0, None,
                                         ctypes.byref(size), ctypes.byref(calisiyor)) != 0:
            return False
        return bool(calisiyor.value)
    except Exception:
        return False


def mmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def litre(ml: int) -> str:
    v = ml / 1000
    txt = f"{v:.2f}".rstrip("0").rstrip(".")
    return txt.replace(".", ",")


def bundle_executable():
    """Uygulama .app olarak çalışıyorsa çalıştırılabilir dosyanın yolu."""
    if not HAS_APPKIT:
        return None
    b = NSBundle.mainBundle()
    if b.bundleIdentifier() and str(b.bundlePath()).endswith(".app"):
        return str(b.executablePath())
    return None


def _dinamik_renk(ad, light, dark, yedek):
    def rgb(c):
        return NSColor.colorWithSRGBRed_green_blue_alpha_(
            c[0] / 255, c[1] / 255, c[2] / 255, 1.0)
    try:
        l, d = rgb(light), rgb(dark)

        def provider(appearance):
            name = appearance.bestMatchFromAppearancesWithNames_(
                ["NSAppearanceNameAqua", "NSAppearanceNameDarkAqua"])
            return d if name and "Dark" in str(name) else l
        return NSColor.colorWithName_dynamicProvider_(ad, provider)
    except Exception:
        return yedek


_RENK = {}


def hareket_renk():
    if not HAS_APPKIT:
        return None
    if "h" in _RENK:
        return _RENK["h"]
    _RENK["h"] = _dinamik_renk("DengeHareket", HAREKET_LIGHT, HAREKET_DARK,
                         NSColor.systemTealColor())
    return _RENK["h"]


def su_renk():
    if not HAS_APPKIT:
        return None
    if "s" not in _RENK:
        _RENK["s"] = _dinamik_renk("DengeSu", SU_LIGHT, SU_DARK, NSColor.systemBlueColor())
    return _RENK["s"]


_SEMBOL = {}
_EKLER = {}


def sistem_renk(ad):
    """labelColor / secondaryLabelColor: tek nesne olarak sakla."""
    if ad not in _RENK:
        _RENK[ad] = getattr(NSColor, ad)()
    return _RENK[ad]


def sembol(ad, boyut=None, renk=None):
    """SF Symbol görseli; aynı istek için hep aynı nesne (her saniye yeniden çizilmesin)."""
    anahtar = (ad, boyut, id(renk) if renk is not None else None)
    if anahtar in _SEMBOL:
        return _SEMBOL[anahtar]
    img = _sembol_yap(ad, boyut, renk)
    _SEMBOL[anahtar] = img
    return img


def _sembol_yap(ad, boyut=None, renk=None):
    img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(ad, "Denge")
    if img is None:
        return None
    if boyut:
        cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(boyut, 0.0)
        img = img.imageWithSymbolConfiguration_(cfg) or img
    if renk is not None:
        cfg = NSImageSymbolConfiguration.configurationWithHierarchicalColor_(renk)
        img = img.imageWithSymbolConfiguration_(cfg) or img
        img.setTemplate_(False)
    else:
        img.setTemplate_(True)
    return img


# ---------------------------------------------------------------- günlük kayıt
class Gunluk:
    """Gün gün kalkış sayısı ve içilen su (ml)."""

    def __init__(self):
        self.veri = _read_json(DAYS_FILE, {})

    @staticmethod
    def bugun() -> str:
        return dt.date.today().isoformat()

    def gun(self, tarih=None) -> dict:
        return self.veri.get(tarih or self.bugun(), {})

    def ekle(self, alan: str, miktar: int) -> None:
        g = self.veri.setdefault(self.bugun(), {})
        g[alan] = max(0, int(g.get(alan, 0)) + miktar)
        self._temizle()
        _write_json(DAYS_FILE, self.veri)

    def kalkis(self) -> int:
        return int(self.gun().get("kalkis", 0))

    def su(self) -> int:
        return int(self.gun().get("su_ml", 0))

    def son_7_gun(self):
        bugun = dt.date.today()
        out = []
        for i in range(6, -1, -1):
            t = bugun - dt.timedelta(days=i)
            g = self.veri.get(t.isoformat(), {})
            out.append((t, int(g.get("kalkis", 0)), int(g.get("su_ml", 0))))
        return out

    def _temizle(self):  # 400 günden eskisini at
        sinir = (dt.date.today() - dt.timedelta(days=400)).isoformat()
        for k in [k for k in self.veri if k < sinir]:
            del self.veri[k]


# ---------------------------------------------------------------- bildirim
class Notifier:
    """Uygulama paketiyse gerçek macOS bildirimi, değilse osascript."""

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
            self.center = None

    def send(self, title: str, body: str, sound: bool) -> None:
        if self.center is not None:
            try:
                from UserNotifications import (UNMutableNotificationContent,
                                               UNNotificationRequest,
                                               UNNotificationSound)
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
                log(f"bildirim gönderilemedi, osascript'e geçiliyor: {e}")
        t, b = title.replace('"', "'"), body.replace('"', "'")
        script = f'display notification "{b}" with title "{t}"'
        if sound:
            script += ' sound name "Glass"'
        subprocess.Popen(["osascript", "-e", script])


# ---------------------------------------------------------------- giriş öğesi
def agent_installed() -> bool:
    return AGENT_FILE.exists()


def set_agent(enabled: bool) -> bool:
    """Oturum açınca başlat + çökerse yeniden aç (LaunchAgent)."""
    exe = bundle_executable()
    if enabled:
        if not exe:
            return False
        AGENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with AGENT_FILE.open("wb") as f:
            plistlib.dump({
                "Label": APP_ID,
                "ProgramArguments": [exe],
                "RunAtLoad": True,
                "KeepAlive": {"SuccessfulExit": False},
                "ProcessType": "Interactive",
                "StandardErrorPath": str(LOG_FILE),
            }, f)
    elif AGENT_FILE.exists():
        AGENT_FILE.unlink()
    return True


# ---------------------------------------------------------------- yerel görünümler
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

    class BardakView(NSView):
        """Bardak sırası: dolu bardaklar renkli, kalanlar çerçeve."""

        def drawRect_(self, rect):
            toplam = max(1, int(getattr(self, "toplam", 8)))
            dolu = int(getattr(self, "dolu", 0))
            b = self.bounds()
            bosluk = 5.0
            w = (b.size.width - bosluk * (toplam - 1)) / toplam
            h = b.size.height
            renk = getattr(self, "renk", None) or NSColor.systemBlueColor()
            for i in range(toplam):
                r = NSMakeRect(i * (w + bosluk), 0, w, h)
                p = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(r, 4, 4)
                if i < dolu:
                    renk.setFill()
                    p.fill()
                else:
                    NSColor.tertiaryLabelColor().setStroke()
                    p.setLineWidth_(1.5)
                    inset = NSMakeRect(r.origin.x + 0.75, 0.75, w - 1.5, h - 1.5)
                    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                        inset, 4, 4).stroke()

    class GrafikView(NSView):
        """Basit çubuk grafik: 7 gün, isteğe bağlı hedef çizgisi."""

        def drawRect_(self, rect):
            degerler = list(getattr(self, "degerler", []))
            etiketler = list(getattr(self, "etiketler", []))
            yazilar = list(getattr(self, "yazilar", []))
            hedef = getattr(self, "hedef", None)
            renk = getattr(self, "renk", None) or NSColor.systemBlueColor()
            if not degerler:
                return
            b = self.bounds()
            alt, ust = 18.0, 16.0
            yuk = b.size.height - alt - ust
            n = len(degerler)
            bosluk = 14.0
            w = (b.size.width - bosluk * (n - 1)) / n
            tepe = max(max(degerler), hedef or 0, 1)
            kucuk = {NSFontAttributeName: NSFont.systemFontOfSize_(11),
                     NSForegroundColorAttributeName: NSColor.secondaryLabelColor()}
            kalin = {NSFontAttributeName: NSFont.boldSystemFontOfSize_(11),
                     NSForegroundColorAttributeName: NSColor.labelColor()}
            # taban çizgisi
            NSColor.separatorColor().setFill()
            NSBezierPath.fillRect_(NSMakeRect(0, alt, b.size.width, 1))
            for i, v in enumerate(degerler):
                x = i * (w + bosluk)
                h = yuk * v / tepe
                bugun = i == n - 1
                if v > 0:
                    r = NSMakeRect(x, alt + 1, w, h)
                    p = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(r, 3, 3)
                    if bugun:
                        renk.colorWithAlphaComponent_(0.55).setFill()
                    else:
                        renk.setFill()
                    p.fill()
                attrs = kalin if bugun else kucuk
                if i < len(yazilar):
                    s = NSString.stringWithString_(yazilar[i])
                    sz = s.sizeWithAttributes_(attrs)
                    s.drawAtPoint_withAttributes_(
                        NSMakePoint(x + (w - sz.width) / 2, alt + h + 3), attrs)
                if i < len(etiketler):
                    s = NSString.stringWithString_(etiketler[i])
                    sz = s.sizeWithAttributes_(attrs)
                    s.drawAtPoint_withAttributes_(
                        NSMakePoint(x + (w - sz.width) / 2, 1), attrs)
            if hedef:
                y = alt + yuk * hedef / tepe
                p = NSBezierPath.bezierPath()
                p.moveToPoint_(NSMakePoint(0, y))
                p.lineToPoint_(NSMakePoint(b.size.width, y))
                p.setLineWidth_(1.2)
                p.setLineDash_count_phase_([4.0, 3.0], 2, 0.0)
                NSColor.secondaryLabelColor().setStroke()
                p.stroke()


def _etiket(metin, boyut=13, kalin=False, ikincil=False, sag=False, mono=False):
    t = NSTextField.labelWithString_(metin)
    if mono:
        t.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(boyut, 0.3 if kalin else 0.0))
    elif kalin:
        t.setFont_(NSFont.systemFontOfSize_weight_(boyut, 0.3))
    else:
        t.setFont_(NSFont.systemFontOfSize_(boyut))
    if ikincil:
        t.setTextColor_(NSColor.secondaryLabelColor())
    if sag:
        t.setAlignment_(1)
    return t


# ---------------------------------------------------------------- uygulama
class DengeApp(rumps.App):
    def __init__(self):
        super().__init__("Denge", title="Denge", quit_button=None)
        self.s = load_settings()
        self.g = Gunluk()
        self.notifier = None
        self._activity = None
        self._header = None
        self._son_durum = None
        self._hedef = None
        self._istatistik = None

        # hareket durumu
        self.oturma = 0.0
        self.sonraki_uyari = self.limit
        self.uyarildi = False
        self.duraklatildi = False
        self.mola_bitis = None      # mola sürüyorsa bitiş zamanı (monotonic)
        # su durumu
        self.su_gecen = 0.0
        self.su_sonraki = self.su_limit
        self.su_bardaklar = []      # bugün eklenen bardaklar (geri almak için)
        # genel
        self.son_tick = time.monotonic()
        self.son_idle_kontrol = 0.0
        self.bosta = False
        self.toplanti_bas = None    # toplantı yüzünden beklemeye ne zaman başladık

        # ---- menü
        self.m_ozet = rumps.MenuItem("Denge")
        self.m_detay = rumps.MenuItem("")
        self.m_bardak = rumps.MenuItem("Bir bardak içtim", callback=self.bardak_menu, key="d")
        self.m_istatistik = rumps.MenuItem("Haftalık istatistik", callback=self.istatistik_ac,
                                           key="i")
        self.m_duraklat = rumps.MenuItem("Hepsini duraklat", callback=self.duraklat, key="p")
        self.m_sifirla = rumps.MenuItem("Kalktım, sıfırla", callback=self.sifirla, key="r")

        self.m_hareket = rumps.MenuItem("Hareket ayarları")
        self.m_sure = rumps.MenuItem("Hatırlatma süresi")
        for dk in SURE_SECENEKLERI:
            self.m_sure.add(rumps.MenuItem(f"{dk} dk", callback=self.sure_sec))
        self.m_kalkma = rumps.MenuItem("Mola süresi")
        for dk in KALKMA_SECENEKLERI:
            self.m_kalkma.add(rumps.MenuItem(f"{dk} dk mola", callback=self.kalkma_sec))
        self.m_mola = rumps.MenuItem("Doğal mola sayılsın")
        for dk in MOLA_SECENEKLERI:
            self.m_mola.add(rumps.MenuItem(f"{dk} dk boşta", callback=self.mola_sec))
        self.m_hareket.add(self.m_sure)
        self.m_hareket.add(self.m_kalkma)
        self.m_hareket.add(self.m_mola)

        self.m_su = rumps.MenuItem("Su ayarları")
        self.m_su_acik = rumps.MenuItem("Su hatırlatıcısı", callback=self.su_ac_kapa)
        self.m_hedef = rumps.MenuItem("Günlük hedef")
        for ml in HEDEF_SECENEKLERI:
            self.m_hedef.add(rumps.MenuItem(f"{litre(ml)} L", callback=self.hedef_sec))
        self.m_bardak_boy = rumps.MenuItem("Bardak")
        for ml in BARDAK_SECENEKLERI:
            self.m_bardak_boy.add(rumps.MenuItem(f"{ml} ml", callback=self.bardak_sec))
        self.m_aralik = rumps.MenuItem("Hatırlatma aralığı")
        for dk in ARALIK_SECENEKLERI:
            self.m_aralik.add(rumps.MenuItem(f"Her {dk} dk", callback=self.aralik_sec))
        self.m_geri = rumps.MenuItem("Son bardağı geri al", callback=self.bardak_geri)
        self.m_su.add(self.m_su_acik)
        self.m_su.add(self.m_hedef)
        self.m_su.add(self.m_bardak_boy)
        self.m_su.add(self.m_aralik)
        self.m_su.add(None)
        self.m_su.add(self.m_geri)

        self.m_toplanti = rumps.MenuItem("Mikrofon açıkken sessiz (toplantı)",
                                         callback=self.toplanti_degistir)
        self.m_ses = rumps.MenuItem("Bildirim sesi", callback=self.ses_degistir)
        self.m_ikon = rumps.MenuItem("Sadece ikon göster", callback=self.ikon_degistir)
        self.m_giris = rumps.MenuItem("Oturum açınca başlat", callback=self.giris_degistir)

        self.menu = [
            self.m_ozet, self.m_detay, self.m_bardak, None,
            self.m_istatistik, self.m_duraklat, self.m_sifirla, None,
            self.m_hareket, self.m_su, self.m_toplanti, self.m_ses, self.m_ikon, None,
            self.m_giris, None,
            rumps.MenuItem("Denge'den çık", callback=self.cik, key="q"),
        ]
        self._isaretleri_guncelle()

        self.timer = rumps.Timer(self.tick, TICK)
        self.timer.start()

    # ------------------------------------------------ yaşam döngüsü
    def _ilk_kurulum(self):
        if self.notifier is not None:
            return
        self.notifier = Notifier()
        if HAS_APPKIT:
            try:  # App Nap'i engelle (uykuya izin ver)
                self._activity = NSProcessInfo.processInfo() \
                    .beginActivityWithOptions_reason_(0x00EFFFFF,
                                                      "Oturma ve su süresini sayıyor")
            except Exception as e:
                log(f"App Nap engellenemedi: {e}")
            self._header_kur()
        log("Denge başladı")

    def _header_kur(self):
        """Menünün en üstüne Hareket ve Su kartları."""
        try:
            W, H = 300, 156
            view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
            x, iw = 14, W - 28
            h_ad = _etiket("Hareket", kalin=True)
            h_ad.setFrame_(NSMakeRect(x, 134, 160, 17))
            h_deger = _etiket("30:00", kalin=True, sag=True, mono=True)
            h_deger.setFrame_(NSMakeRect(x + iw - 120, 134, 120, 17))
            h_bar = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(x, 120, iw, 10))
            h_bar.setStyle_(0)
            h_bar.setIndeterminate_(False)
            h_bar.setControlSize_(2)
            h_bar.setMinValue_(0.0)
            h_bar.setMaxValue_(1.0)
            h_alt = _etiket("", boyut=12, ikincil=True)
            h_alt.setFrame_(NSMakeRect(x, 100, iw, 16))

            ayrac = NSBox.alloc().initWithFrame_(NSMakeRect(x, 90, iw, 1))
            ayrac.setBoxType_(2)  # ayırıcı çizgi

            s_ad = _etiket("Su", kalin=True)
            s_ad.setFrame_(NSMakeRect(x, 64, 160, 17))
            s_deger = _etiket("0 / 2 L", kalin=True, sag=True, mono=True)
            s_deger.setFrame_(NSMakeRect(x + iw - 140, 64, 140, 17))
            s_bardak = BardakView.alloc().initWithFrame_(NSMakeRect(x, 38, iw, 20))
            s_bardak.renk = su_renk()
            s_alt = _etiket("", boyut=12, ikincil=True)
            s_alt.setFrame_(NSMakeRect(x, 10, iw - 96, 16))
            s_btn = NSButton.alloc().initWithFrame_(NSMakeRect(x + iw - 90, 5, 90, 26))
            s_btn.setTitle_("+ 1 bardak")
            s_btn.setBezelStyle_(1)  # yuvarlak köşeli düğme
            s_btn.setControlSize_(1)
            try:
                s_btn.setBezelColor_(su_renk())
            except Exception:
                pass
            self._hedef = Hedef.alloc().init()
            self._hedef.fn = lambda: self.bardak_ekle(kaynak="menü")
            s_btn.setTarget_(self._hedef)
            s_btn.setAction_("tikla:")

            try:  # ikonlar
                hi = sembol("figure.walk", 13, hareket_renk())
                si = sembol("drop.fill", 12, su_renk())
                if hi is not None:
                    h_ad.setStringValue_("      Hareket")
                    s_ad.setStringValue_("      Su")
                    from AppKit import NSImageView
                    for img, y in ((hi, 133), (si, 63)):
                        v = NSImageView.alloc().initWithFrame_(NSMakeRect(x, y, 18, 18))
                        v.setImage_(img)
                        view.addSubview_(v)
            except Exception:
                pass

            for v in (h_ad, h_deger, h_bar, h_alt, ayrac, s_ad, s_deger, s_bardak,
                      s_alt, s_btn):
                view.addSubview_(v)
            self.m_ozet._menuitem.setView_(view)
            self.m_detay._menuitem.setHidden_(True)
            self._header = {"h_deger": h_deger, "h_bar": h_bar, "h_alt": h_alt,
                            "h_ad": h_ad, "s_deger": s_deger, "s_bardak": s_bardak,
                            "s_alt": s_alt, "s_btn": s_btn, "s_ad": s_ad}
        except Exception as e:
            log(f"menü başlığı kurulamadı, metin moduna geçiliyor: {e}")
            self._header = None

    # ------------------------------------------------ ortak mantık
    @property
    def limit(self) -> int:
        return int(self.s["sure_dk"]) * 60

    @property
    def su_limit(self) -> int:
        return int(self.s["su_aralik_dk"]) * 60

    def _kaydet(self):
        _write_json(SETTINGS_FILE, self.s)

    def _kalkti(self, sayilsin: bool = True, zorla: bool = False):
        if sayilsin and (zorla or self.oturma >= 60):
            self.g.ekle("kalkis", 1)
        self.oturma = 0.0
        self.sonraki_uyari = self.limit
        self.uyarildi = False

    def su_aktif(self) -> bool:
        return bool(self.s["su_acik"]) and self.g.su() < int(self.s["su_hedef_ml"])

    def durum(self) -> str:
        if self.duraklatildi:
            return "durdu"
        if self.mola_bitis is not None:
            return "mola"
        return "kalk" if self.uyarildi else "sayiyor"

    def bardak_toplam(self) -> int:
        return max(1, round(int(self.s["su_hedef_ml"]) / int(self.s["bardak_ml"])))

    def bardak_dolu(self) -> int:
        return int(self.g.su() // int(self.s["bardak_ml"]))

    # ------------------------------------------------ çizim
    def _isaretleri_guncelle(self):
        s = self.s
        for item in self.m_sure.values():
            item.state = item.title == f"{s['sure_dk']} dk"
        for item in self.m_mola.values():
            item.state = item.title == f"{s['mola_dk']} dk boşta"
        for item in self.m_kalkma.values():
            item.state = item.title == f"{s['kalkma_dk']} dk mola"
        for item in self.m_hedef.values():
            item.state = item.title == f"{litre(s['su_hedef_ml'])} L"
        for item in self.m_bardak_boy.values():
            item.state = item.title == f"{s['bardak_ml']} ml"
        for item in self.m_aralik.values():
            item.state = item.title == f"Her {s['su_aralik_dk']} dk"
        self.m_sure.title = f"Hatırlatma süresi · {s['sure_dk']} dk"
        self.m_mola.title = f"Doğal mola sayılsın · {s['mola_dk']} dk boşta"
        self.m_kalkma.title = f"Mola süresi · {s['kalkma_dk']} dk"
        self.m_hedef.title = f"Günlük hedef · {litre(s['su_hedef_ml'])} L"
        self.m_bardak_boy.title = f"Bardak · {s['bardak_ml']} ml"
        self.m_aralik.title = f"Hatırlatma aralığı · {s['su_aralik_dk']} dk"
        self.m_hareket.title = f"Hareket ayarları · {s['sure_dk']} dk"
        self.m_su.title = (f"Su ayarları · {litre(s['su_hedef_ml'])} L · {s['su_aralik_dk']} dk"
                           if s["su_acik"] else "Su ayarları · kapalı")
        self.m_su_acik.state = bool(s["su_acik"])
        self.m_toplanti.state = bool(s["toplanti_sessiz"])
        self.m_ses.state = bool(s["ses"])
        self.m_ikon.state = bool(s["sadece_ikon"])
        self.m_giris.state = agent_installed()
        self.m_duraklat.title = "Devam et" if self.duraklatildi else "Hepsini duraklat"
        self.m_sifirla.title = "Molayı bitir" if self.mola_bitis else "Kalktım, sıfırla"
        self.m_bardak.title = f"Bir bardak içtim ({s['bardak_ml']} ml)"

    def _ekrani_guncelle(self):
        kalan = self.sonraki_uyari - self.oturma
        d = self.durum()
        dk = int(self.oturma // 60)
        kalkis = self.g.kalkis()
        mola_kalan = (self.mola_bitis - time.monotonic()) if self.mola_bitis else 0

        if d == "mola":
            h_deger = mmss(mola_kalan)
            h_alt = "Mola · bitince sayaç senin onayınla başlar"
            oran = 1.0 - mola_kalan / max(1, self.s["kalkma_dk"] * 60)
        elif d == "durdu":
            h_deger, h_alt, oran = "Durdu", "Devam etmek için “Devam et”", 0.0
        elif d == "kalk":
            h_deger = "Kalk"
            h_alt = f"{dk} dakikadır oturuyorsun · Bugün {kalkis} kez kalktın"
            oran = 1.0
        else:
            h_deger = mmss(kalan)
            h_alt = f"Kalkmaya {max(0, int(kalan // 60))} dk · Bugün {kalkis} kez kalktın"
            oran = self.oturma / max(1, self.limit)

        su_ml, hedef = self.g.su(), int(self.s["su_hedef_ml"])
        s_deger = f"{litre(su_ml)} / {litre(hedef)} L"
        if not self.s["su_acik"]:
            s_alt = "Su hatırlatıcısı kapalı"
        elif su_ml >= hedef:
            s_alt = "Bugünkü hedefe ulaştın"
        elif d == "durdu":
            s_alt = "Duraklatıldı"
        else:
            kalan_su = max(0, int((self.su_sonraki - self.su_gecen) // 60))
            s_alt = f"Sonraki hatırlatma {kalan_su} dk sonra" if kalan_su else "Su zamanı"

        if self._header:
            hd = self._header
            oran = round(max(0.0, min(1.0, oran)), 3)
            onceki = getattr(self, "_son_header", {})
            yeni = {"h_deger": h_deger, "h_alt": h_alt, "s_deger": s_deger, "s_alt": s_alt}
            for k, v in yeni.items():
                if onceki.get(k) != v:
                    hd[k].setStringValue_(v)
            if onceki.get("oran") != oran:
                hd["h_bar"].setDoubleValue_(oran)
            yeni["oran"] = oran
            self._son_header = yeni
            bv = hd["s_bardak"]
            yeni = (self.bardak_dolu(), self.bardak_toplam())
            if (getattr(bv, "dolu", None), getattr(bv, "toplam", None)) != yeni:
                bv.dolu, bv.toplam = yeni
                bv.setNeedsDisplay_(True)
        else:
            self.m_ozet.title = f"Hareket  {h_deger}"
            self.m_detay.title = f"Su  {s_deger}"

        # menü çubuğu
        metin = {"sayiyor": mmss(kalan), "kalk": "Kalk", "durdu": "Durdu",
                 "mola": "Mola " + mmss(mola_kalan)}[d]
        su_metin = None
        if self.s["su_acik"] and d != "durdu":
            su_metin = f"{self.bardak_dolu()}/{self.bardak_toplam()}"
        su_zamani = self.su_aktif() and self.su_gecen >= self.su_sonraki
        if self.s["sadece_ikon"]:
            metin, su_metin = "", None
        self._menu_cubugu(d, metin, su_metin, su_zamani)

    def _menu_cubugu(self, d: str, metin: str, su_metin, su_zamani: bool):
        anahtar = (d, metin, su_metin, su_zamani)
        if anahtar == self._son_durum:
            return
        self._son_durum = anahtar
        try:
            button = self._nsapp.nsstatusitem.button()
            ad = {"sayiyor": "chair", "kalk": "figure.walk", "durdu": "pause",
                  "mola": "figure.walk"}[d]
            renk = None
            if d in ("kalk", "mola"):
                renk = hareket_renk()
            elif d == "durdu":
                renk = sistem_renk("secondaryLabelColor")
            img = sembol(ad, None, renk)
            konum = 2 if (metin or su_metin) else 1
            if getattr(self, "_son_img", None) != (ad, d, konum):
                self._son_img = (ad, d, konum)
                button.setImage_(img)
                button.setImagePosition_(konum)

            yazi = NSFont.monospacedDigitSystemFontOfSize_weight_(13, 0.3 if d == "kalk" else 0.0)
            attrs = {NSFontAttributeName: yazi}
            if renk is not None:
                attrs[NSForegroundColorAttributeName] = renk
            title = NSMutableAttributedString.alloc().initWithString_attributes_(
                f" {metin}" if metin else "", attrs)
            if su_metin:
                s_renk = su_renk() if su_zamani else sistem_renk("labelColor")
                damla = sembol("drop.fill" if su_zamani else "drop", 11, s_renk)
                if damla is not None:
                    att = _EKLER.get(id(damla))
                    if att is None:
                        att = NSTextAttachment.alloc().init()
                        att.setImage_(damla)
                        sz = damla.size()
                        att.setBounds_(NSMakeRect(0, -2, sz.width, sz.height))
                        _EKLER[id(damla)] = att
                    title.appendAttributedString_(
                        NSAttributedString.alloc().initWithString_attributes_("  ", attrs))
                    title.appendAttributedString_(
                        NSAttributedString.attributedStringWithAttachment_(att))
                s_attrs = {NSFontAttributeName: NSFont.monospacedDigitSystemFontOfSize_weight_(
                    13, 0.3 if su_zamani else 0.0)}
                if su_zamani:
                    s_attrs[NSForegroundColorAttributeName] = s_renk
                title.appendAttributedString_(
                    NSAttributedString.alloc().initWithString_attributes_(
                        f" {su_metin}", s_attrs))
            button.setAttributedTitle_(title)
        except Exception as e:
            log(f"menü çubuğu çizilemedi: {e}")
            parca = [metin] if metin else []
            if su_metin:
                parca.append(f"Su {su_metin}")
            self.title = "  ".join(parca) or "Denge"

    # ------------------------------------------------ zamanlayıcı
    def tick(self, _):
        self._ilk_kurulum()
        now = time.monotonic()
        gecen = now - self.son_tick
        self.son_tick = now

        if gecen > SLEEP_GAP:          # uykudan döndü: sessizce sıfırla
            self._uyandi_sifirla()
            self._ekrani_guncelle()
            return
        if self.duraklatildi:
            self._ekrani_guncelle()
            return

        if now - self.son_idle_kontrol >= IDLE_EVERY:
            self.son_idle_kontrol = now
            self.bosta = idle_seconds() >= self.s["mola_dk"] * 60

        # su sayacı: bilgisayar başındayken ilerler
        if not self.bosta:
            self.su_gecen += gecen

        if self.mola_bitis is not None:
            if now >= self.mola_bitis:
                self._mola_bitti_sor()
                return
            self._ekrani_guncelle()
            return

        if self.bosta and self.oturma > 0:
            self._kalkti(sayilsin=False)   # doğal mola: sayılmaz
        elif not self.bosta:
            self.oturma += gecen

        hareket_zamani = self.oturma >= self.sonraki_uyari
        su_zamani = self.su_aktif() and self.su_gecen >= self.su_sonraki
        if hareket_zamani or su_zamani:
            if self._toplantida():
                self._ekrani_guncelle()
                return
            su_yakin = self.su_aktif() and self.su_sonraki - self.su_gecen <= YAKIN
            hareket_yakin = self.sonraki_uyari - self.oturma <= YAKIN
            if (hareket_zamani and su_yakin) or (su_zamani and hareket_yakin):
                self._birlesik_uyari()
            elif hareket_zamani:
                self._hareket_uyari()
            else:
                self._su_uyari()
            return
        self._ekrani_guncelle()

    def _uyandi_sifirla(self):
        self._kalkti(sayilsin=False)
        self.su_gecen = 0.0
        self.su_sonraki = self.su_limit
        if self.mola_bitis is not None:
            self.mola_bitis = None
            self._isaretleri_guncelle()
        self._son_durum = None
        log("Mac uyandı, sayaçlar sıfırlandı")

    def _toplantida(self) -> bool:
        """Mikrofon açıksa uyarıyı bir dakika ertele (en fazla bir saat)."""
        if not self.s["toplanti_sessiz"]:
            return False
        now = time.monotonic()
        if self.toplanti_bas is not None and now - self.toplanti_bas >= TOPLANTI_EN_FAZLA:
            return False
        if not mikrofon_acik():
            return False
        if self.toplanti_bas is None:
            self.toplanti_bas = now
            log("mikrofon açık, uyarı bekletiliyor")
        if self.oturma >= self.sonraki_uyari:
            self.sonraki_uyari = self.oturma + TOPLANTI_BEKLE
        if self.su_gecen >= self.su_sonraki:
            self.su_sonraki = self.su_gecen + TOPLANTI_BEKLE
        return True

    # ------------------------------------------------ uyarılar
    def _alert(self, baslik, metin, dugmeler, ikon, renk):
        """Ekranın ortasında, tüm masaüstlerinde görünen uyarı. Dönüş: düğme sırası."""
        try:
            from AppKit import NSAlert, NSSound
            if self.s["ses"]:
                snd = NSSound.soundNamed_("Glass")
                if snd is not None:
                    snd.play()
            a = NSAlert.alloc().init()
            a.setMessageText_(baslik)
            a.setInformativeText_(metin)
            for d in dugmeler:
                a.addButtonWithTitle_(d)
            try:
                img = sembol(ikon, 48, renk)
                if img is not None:
                    a.setIcon_(img)
            except Exception:
                pass
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            w = a.window()
            w.setLevel_(3)                       # diğer pencerelerin üstünde
            w.setCollectionBehavior_(1 | 256)    # tüm masaüstleri + tam ekran
            r = int(a.runModal())
            secim = r - 1000
        except Exception as e:
            log(f"uyarı penceresi açılamadı, bildirime geçiliyor: {e}")
            if self.notifier is not None:
                self.notifier.send(baslik, metin, self.s["ses"])
            secim = None
        # pencere açıkken geçen süre sayılmaz
        self.son_tick = time.monotonic()
        self.son_idle_kontrol = self.son_tick
        self.toplanti_bas = None
        self._son_durum = None
        return secim

    def _hareket_uyari(self):
        dk = int(self.oturma // 60)
        self.uyarildi = True
        self._ekrani_guncelle()
        secim = self._alert("Hareket zamanı",
                            f"{dk} dakikadır oturuyorsun. Kalk, biraz yürü ve esne.",
                            ["Kalktım", "5 dk ertele", "15 dk ertele"],
                            "figure.walk", hareket_renk())
        if secim == 0:
            self._kalkti(sayilsin=True, zorla=True)
            self._mola_baslat()
            log("Kalktım seçildi, mola başladı")
        else:
            ek = 15 if secim == 2 else 5
            self.uyarildi = False
            self.sonraki_uyari = self.oturma + ek * 60
            log(f"hareket {ek} dk ertelendi")
        self._ekrani_guncelle()

    def _su_uyari(self):
        dk = int(self.su_gecen // 60)
        self._son_durum = None
        self._ekrani_guncelle()
        secim = self._alert(
            "Su zamanı",
            f"Son bardaktan bu yana {dk} dakika geçti. "
            f"Bugün {litre(self.g.su())} / {litre(self.s['su_hedef_ml'])} L içtin.",
            [f"İçtim ({self.s['bardak_ml']} ml)", "15 dk ertele", "Bu sefer atla"],
            "drop.fill", su_renk())
        if secim == 0:
            self.bardak_ekle(kaynak="uyarı")
        elif secim == 2:
            self.su_gecen = 0.0
            self.su_sonraki = self.su_limit
            log("su hatırlatması atlandı")
        else:
            self.su_sonraki = self.su_gecen + 15 * 60
            log("su 15 dk ertelendi")
        self._ekrani_guncelle()

    def _birlesik_uyari(self):
        dk = int(self.oturma // 60)
        self.uyarildi = True
        self._ekrani_guncelle()
        secim = self._alert(
            "Kalk ve bir bardak su iç",
            f"{dk} dakikadır oturuyorsun ve su zamanı da geldi. "
            "Mutfağa kadar yürümek ikisini de çözer.",
            ["İkisini de yaptım", "Sadece kalktım", "Sadece su içtim", "5 dk ertele"],
            "figure.walk", hareket_renk())
        if secim in (0, 1):
            self._kalkti(sayilsin=True, zorla=True)
            self._mola_baslat()
        else:
            self.uyarildi = False
            self.sonraki_uyari = self.oturma + 5 * 60
        if secim in (0, 2):
            self.bardak_ekle(kaynak="birleşik uyarı")
        elif secim == 1:
            self.su_sonraki = self.su_gecen + 15 * 60
        else:
            self.su_sonraki = self.su_gecen + 5 * 60
        log(f"birleşik uyarı: seçim {secim}")
        self._ekrani_guncelle()

    # ------------------------------------------------ su eylemleri
    def bardak_ekle(self, kaynak="menü"):
        ml = int(self.s["bardak_ml"])
        self.g.ekle("su_ml", ml)
        self.su_bardaklar.append((self.g.bugun(), ml))
        self.su_gecen = 0.0
        self.su_sonraki = self.su_limit
        self._son_durum = None
        log(f"+{ml} ml ({kaynak}) · bugün {self.g.su()} ml")
        if self.g.su() >= int(self.s["su_hedef_ml"]) and \
                self.g.su() - ml < int(self.s["su_hedef_ml"]) and self.notifier:
            self.notifier.send("Günlük su hedefi tamam",
                               f"Bugün {litre(self.g.su())} L içtin. Bugünlük hatırlatma bitti.",
                               False)
        self._ekrani_guncelle()

    def bardak_menu(self, _):
        self.bardak_ekle(kaynak="menü")

    def bardak_geri(self, _):
        if self.su_bardaklar and self.su_bardaklar[-1][0] == self.g.bugun():
            _, ml = self.su_bardaklar.pop()
        elif self.g.su() > 0:
            ml = int(self.s["bardak_ml"])
        else:
            return
        self.g.ekle("su_ml", -ml)
        log(f"-{ml} ml geri alındı")
        self._son_durum = None
        self._ekrani_guncelle()

    # ------------------------------------------------ istatistik penceresi
    def istatistik_ac(self, _):
        if not HAS_APPKIT:
            return
        try:
            gunler = self.g.son_7_gun()
            hedef = int(self.s["su_hedef_ml"])
            kalkislar = [k for _, k, _ in gunler]
            sular = [s for _, _, s in gunler]
            etiketler = [GUNLER[t.weekday()] for t, _, _ in gunler]
            etiketler[-1] = "Bugün"

            W, H = 580, 470
            if self._istatistik is None:
                p = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                    NSMakeRect(0, 0, W, H), 1 | 2, 2, False)  # başlık + kapat
                p.setReleasedWhenClosed_(False)
                p.setHidesOnDeactivate_(False)
                p.setLevel_(3)
                p.setCollectionBehavior_(1 | 256)
                self._istatistik = p
            p = self._istatistik
            bas = gunler[0][0]
            p.setTitle_(f"Denge · Son 7 gün ({bas.day}.{bas.month:02d} – bugün)")
            icerik = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))

            def kart(x, baslik, deger, alt, renk=None):
                b = _etiket(baslik, boyut=12, ikincil=True)
                b.setFrame_(NSMakeRect(x, H - 40, 170, 16))
                d = _etiket(deger, boyut=22, kalin=True, mono=True)
                d.setFrame_(NSMakeRect(x, H - 70, 170, 28))
                if renk is not None:
                    d.setTextColor_(renk)
                a = _etiket(alt, boyut=12, ikincil=True)
                a.setFrame_(NSMakeRect(x, H - 88, 170, 16))
                for v in (b, d, a):
                    icerik.addSubview_(v)

            toplam = sum(kalkislar)
            ort = toplam / 7
            kart(20, "Toplam kalkış", str(toplam),
                 f"günde ortalama {ort:.1f}".replace(".", ","), hareket_renk())
            kart(210, "İçilen su", f"{litre(sum(sular))} L",
                 f"{sum(1 for s in sular if s >= hedef)} gün hedefe ulaştın", su_renk())
            en_iyi = max(range(7), key=lambda i: kalkislar[i])
            kart(400, "En çok kalktığın gün",
                 etiketler[en_iyi] if kalkislar[en_iyi] else "—",
                 f"{kalkislar[en_iyi]} kez" if kalkislar[en_iyi] else "henüz veri yok")

            t1 = _etiket("Günlük kalkış", kalin=True)
            t1.setFrame_(NSMakeRect(20, H - 122, 300, 17))
            g1 = GrafikView.alloc().initWithFrame_(NSMakeRect(20, 196, W - 40, 140))
            g1.degerler, g1.etiketler, g1.renk = kalkislar, etiketler, hareket_renk()
            g1.yazilar = [str(k) for k in kalkislar]
            g1.hedef = None

            t2 = _etiket("Günlük su (L)", kalin=True)
            t2.setFrame_(NSMakeRect(20, 164, 300, 17))
            t2b = _etiket(f"Kesikli çizgi: {litre(hedef)} L hedef", boyut=12,
                          ikincil=True, sag=True)
            t2b.setFrame_(NSMakeRect(W - 240, 164, 220, 16))
            g2 = GrafikView.alloc().initWithFrame_(NSMakeRect(20, 20, W - 40, 136))
            g2.degerler, g2.etiketler, g2.renk = sular, etiketler, su_renk()
            g2.yazilar = [litre(s) if s else "" for s in sular]
            g2.hedef = hedef

            for v in (t1, g1, t2, t2b, g2):
                icerik.addSubview_(v)
            p.setContentView_(icerik)
            p.center()
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            p.makeKeyAndOrderFront_(None)
        except Exception as e:
            log(f"istatistik açılamadı: {e}")
            rumps.alert("Denge", f"İstatistik açılamadı: {e}")

    # ------------------------------------------------ menü eylemleri
    def duraklat(self, _):
        self.duraklatildi = not self.duraklatildi
        self.mola_bitis = None
        if not self.duraklatildi:
            self._kalkti(sayilsin=False)
            self.su_sonraki = max(self.su_sonraki, self.su_gecen + 60)
        self._son_durum = None
        self._isaretleri_guncelle()
        self._ekrani_guncelle()

    def sifirla(self, _):
        if self.mola_bitis is not None:
            self._mola_bitir()
        else:
            self._kalkti()
            self._mola_baslat()
        self._ekrani_guncelle()

    def _mola_baslat(self):
        self.mola_bitis = time.monotonic() + self.s["kalkma_dk"] * 60
        self._son_durum = None
        self._isaretleri_guncelle()

    def _mola_bitir(self):
        self.mola_bitis = None
        self._kalkti(sayilsin=False)
        self.son_tick = time.monotonic()
        self.son_idle_kontrol = self.son_tick
        self._son_durum = None
        self._isaretleri_guncelle()
        log("mola bitti")

    def _mola_bitti_sor(self):
        """Mola bitti: kullanıcı 'Başlat' diyene kadar sayaç başlamaz."""
        self.mola_bitis = time.monotonic()   # pencere açıkken 00:00'da bekler
        self._ekrani_guncelle()
        ek = self.s["kalkma_dk"]
        secim = self._alert("Mola bitti",
                            f"Hazır olduğunda {self.s['sure_dk']} dakikalık sayacı başlat.",
                            ["Başlat", f"{ek} dk daha mola"], "chair", None)
        if secim == 1:
            self.mola_bitis = time.monotonic() + ek * 60
            log(f"mola {ek} dk uzatıldı")
        else:
            self._mola_bitir()
            log("mola bitti, sayaç başlatıldı")
        self._ekrani_guncelle()

    def _sec(self, anahtar, deger):
        self.s[anahtar] = deger
        self._kaydet()
        self._son_durum = None
        self._isaretleri_guncelle()
        self._ekrani_guncelle()

    def sure_sec(self, sender):
        self._sec("sure_dk", int(sender.title.split()[0]))
        if self.oturma < self.limit:
            self.uyarildi = False
            self.sonraki_uyari = self.limit

    def kalkma_sec(self, sender):
        self._sec("kalkma_dk", int(sender.title.split()[0]))

    def mola_sec(self, sender):
        self._sec("mola_dk", int(sender.title.split()[0]))

    def su_ac_kapa(self, _):
        self._sec("su_acik", not self.s["su_acik"])
        self.su_gecen, self.su_sonraki = 0.0, self.su_limit

    def hedef_sec(self, sender):
        ml = int(round(float(sender.title.split()[0].replace(",", ".")) * 1000))
        self._sec("su_hedef_ml", ml)

    def bardak_sec(self, sender):
        self._sec("bardak_ml", int(sender.title.split()[0]))

    def aralik_sec(self, sender):
        self._sec("su_aralik_dk", int(sender.title.split()[1]))
        self.su_sonraki = self.su_limit

    def toplanti_degistir(self, _):
        self._sec("toplanti_sessiz", not self.s["toplanti_sessiz"])

    def ses_degistir(self, _):
        self._sec("ses", not self.s["ses"])

    def ikon_degistir(self, _):
        self._sec("sadece_ikon", not self.s["sadece_ikon"])

    def giris_degistir(self, _):
        if not set_agent(not agent_installed()):
            rumps.alert("Denge",
                        "Bu seçenek uygulama Denge.app olarak kurulduğunda çalışır. "
                        "install.sh ile kurabilirsin.")
        self._isaretleri_guncelle()

    def cik(self, _):
        log("Denge kapatıldı")
        rumps.quit_application()   # normal çıkış: LaunchAgent yeniden açmaz


_APP = {}


def _uyandi():
    app = _APP.get("app")
    if app is not None:
        app._uyandi_sifirla()


try:  # rumps uyanma olayı (yoksa tick'teki boşluk kontrolü yeterli)
    rumps.events.on_wake(_uyandi)
except Exception:
    pass

if __name__ == "__main__":
    a = DengeApp()
    _APP["app"] = a
    a.run()
