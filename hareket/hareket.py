#!/usr/bin/env python3
"""
Hareket — Mac menü çubuğu için Türkçe "kalk ve hareket et" hatırlatıcısı.

- Menü çubuğunda sandalye ikonu + kalan süre (SF Symbols, açık/koyu moda uyar).
- Süre dolunca sessiz bir bildirim; ikon yürüyen adama döner ve "Kalk" yazar.
- Bilgisayarı birkaç dakika kullanmazsan kalktın sayılır, sayaç sıfırlanır.
- Mac uyuyup uyanınca sayaç sıfırlanır.
- App Nap'e karşı korumalı: arka planda da zamanında çalışır.

Gerekenler: pip install -r requirements.txt
"""
import datetime as dt
import json
import plistlib
import re
import subprocess
import time
import uuid
from pathlib import Path

import rumps

try:  # macOS yerel arayüz parçaları (yoksa sade metin moduna düşer)
    from AppKit import (NSAttributedString, NSColor, NSFont,
                        NSFontAttributeName, NSForegroundColorAttributeName,
                        NSImage, NSImageSymbolConfiguration, NSMakeRect,
                        NSProgressIndicator, NSTextField, NSView)
    from Foundation import NSBundle, NSProcessInfo
    HAS_APPKIT = True
except Exception:  # pragma: no cover
    HAS_APPKIT = False

# ---------------------------------------------------------------- sabitler
APP_ID = "com.bugra.hareket"
DATA_DIR = Path.home() / "Library" / "Application Support" / "Hareket"
SETTINGS_FILE = DATA_DIR / "ayarlar.json"
LOG_FILE = Path.home() / "Library" / "Logs" / "Hareket.log"
AGENT_FILE = Path.home() / "Library" / "LaunchAgents" / f"{APP_ID}.plist"

DEFAULTS = {
    "sure_dk": 30,          # kaç dakika oturunca uyarsın
    "mola_dk": 3,           # kaç dakika boşta kalınca "kalktı" sayılsın
    "tekrar_dk": 5,         # kalkmazsan kaç dakikada bir tekrar uyarsın
    "kalkma_dk": 5,         # "Kalktım" sonrası mola süresi
    "ses": True,            # bildirimde ses
    "sadece_ikon": False,   # menü çubuğunda sadece ikon
    "gun": "",
    "bugun_kalkis": 0,
}
SURE_SECENEKLERI = [20, 30, 45, 60]
MOLA_SECENEKLERI = [2, 3, 5]
KALKMA_SECENEKLERI = [2, 5, 10]

ACCENT_LIGHT = (0x2F, 0x7D, 0x6D)   # açık mod vurgu
ACCENT_DARK = (0x6C, 0xC4, 0xB0)    # koyu mod vurgu

TICK = 1           # ekran güncelleme (sn)
IDLE_EVERY = 5     # boşta kalma kontrolü (sn)
SLEEP_GAP = 300    # bu kadar sn tick gelmezse Mac uyumuş say


# ---------------------------------------------------------------- yardımcılar
def log(msg: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
    except Exception:
        pass


def load_settings() -> dict:
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return s


def save_settings(s: dict) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    except Exception as e:
        log(f"ayar kaydedilemedi: {e}")


def idle_seconds() -> float:
    """Son klavye/mouse hareketinden bu yana geçen süre (sn)."""
    try:
        out = subprocess.run(["ioreg", "-c", "IOHIDSystem"],
                             capture_output=True, text=True, timeout=3).stdout
        m = re.search(r'"HIDIdleTime" = (\d+)', out)
        return int(m.group(1)) / 1e9 if m else 0.0
    except Exception:
        return 0.0


def mmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def bundle_executable():
    """Uygulama .app olarak çalışıyorsa çalıştırılabilir dosyanın yolu."""
    if not HAS_APPKIT:
        return None
    b = NSBundle.mainBundle()
    if b.bundleIdentifier() and str(b.bundlePath()).endswith(".app"):
        return str(b.executablePath())
    return None


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
            # 2 = ses, 4 = uyarı
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
                "KeepAlive": {"SuccessfulExit": False},  # çökerse yeniden aç
                "ProcessType": "Interactive",
                "StandardErrorPath": str(LOG_FILE),
            }, f)
    elif AGENT_FILE.exists():
        AGENT_FILE.unlink()
    return True


# ---------------------------------------------------------------- uygulama
class HareketApp(rumps.App):
    def __init__(self):
        super().__init__("Hareket", title="Hareket", quit_button=None)
        self.s = load_settings()
        self._yeni_gun_kontrol()
        self.notifier = None
        self._activity = None
        self._header = None
        self._son_durum = None

        self.oturma = 0.0
        self.sonraki_uyari = self.limit
        self.uyarildi = False
        self.duraklatildi = False
        self.mola_bitis = None      # mola sürüyorsa bitiş zamanı (monotonic)
        self.son_tick = time.monotonic()
        self.son_idle_kontrol = 0.0

        # ---- menü
        self.m_ozet = rumps.MenuItem("Hatırlatmaya kalan")
        self.m_detay = rumps.MenuItem("")
        self.m_duraklat = rumps.MenuItem("Duraklat", callback=self.duraklat, key="p")
        self.m_sifirla = rumps.MenuItem("Kalktım, sıfırla", callback=self.sifirla, key="r")

        self.m_sure = rumps.MenuItem("Hatırlatma süresi")
        for dk in SURE_SECENEKLERI:
            self.m_sure.add(rumps.MenuItem(f"{dk} dk", callback=self.sure_sec))
        self.m_kalkma = rumps.MenuItem("Mola süresi")
        for dk in KALKMA_SECENEKLERI:
            self.m_kalkma.add(rumps.MenuItem(f"{dk} dk mola", callback=self.kalkma_sec))
        self.m_mola = rumps.MenuItem("Kalktı sayılsın")
        for dk in MOLA_SECENEKLERI:
            self.m_mola.add(rumps.MenuItem(f"{dk} dk boşta", callback=self.mola_sec))

        self.m_ses = rumps.MenuItem("Bildirim sesi", callback=self.ses_degistir)
        self.m_ikon = rumps.MenuItem("Sadece ikon göster", callback=self.ikon_degistir)
        self.m_giris = rumps.MenuItem("Oturum açınca başlat", callback=self.giris_degistir)

        self.menu = [
            self.m_ozet, self.m_detay, None,
            self.m_duraklat, self.m_sifirla, None,
            self.m_sure, self.m_kalkma, self.m_mola, self.m_ses, self.m_ikon, None,
            self.m_giris, None,
            rumps.MenuItem("Hareket'ten çık", callback=self.cik, key="q"),
        ]
        self._isaretleri_guncelle()

        self.timer = rumps.Timer(self.tick, TICK)
        self.timer.start()

    # ------------------------------------------------ yaşam döngüsü
    def _ilk_kurulum(self):
        """Uygulama döngüsü başladıktan sonra (ilk tick'te) bir kez çalışır."""
        if self.notifier is not None:
            return
        self.notifier = Notifier()
        if HAS_APPKIT:
            try:  # App Nap'i engelle (uykuya izin ver)
                self._activity = NSProcessInfo.processInfo() \
                    .beginActivityWithOptions_reason_(0x00EFFFFF,
                                                      "Oturma süresini sayıyor")
            except Exception as e:
                log(f"App Nap engellenemedi: {e}")
            self._header_kur()
        log("Hareket başladı")

    def _header_kur(self):
        """Menünün en üstüne başlık + ilerleme çubuğu yerleştir."""
        try:
            view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 268, 58))
            sol = NSTextField.labelWithString_("Hatırlatmaya kalan")
            sol.setFont_(NSFont.systemFontOfSize_weight_(13, 0.3))
            sol.setFrame_(NSMakeRect(14, 36, 160, 17))
            sag = NSTextField.labelWithString_("30:00")
            sag.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(13, 0.3))
            sag.setAlignment_(1)  # sağa yasla
            sag.setFrame_(NSMakeRect(170, 36, 84, 17))
            bar = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(14, 22, 240, 10))
            bar.setStyle_(0)
            bar.setIndeterminate_(False)
            bar.setControlSize_(2)  # mini
            bar.setMinValue_(0.0)
            bar.setMaxValue_(1.0)
            alt = NSTextField.labelWithString_("")
            alt.setFont_(NSFont.systemFontOfSize_(12))
            alt.setTextColor_(NSColor.secondaryLabelColor())
            alt.setFrame_(NSMakeRect(14, 2, 240, 16))
            for v in (sol, sag, bar, alt):
                view.addSubview_(v)
            self.m_ozet._menuitem.setView_(view)
            self.m_detay._menuitem.setHidden_(True)
            self._header = {"sol": sol, "sag": sag, "bar": bar, "alt": alt}
        except Exception as e:
            log(f"menü başlığı kurulamadı, metin moduna geçiliyor: {e}")
            self._header = None

    # ------------------------------------------------ ortak mantık
    @property
    def limit(self) -> int:
        return int(self.s["sure_dk"]) * 60

    def _yeni_gun_kontrol(self):
        bugun = dt.date.today().isoformat()
        if self.s.get("gun") != bugun:
            self.s["gun"] = bugun
            self.s["bugun_kalkis"] = 0
            save_settings(self.s)

    def _kalkti(self, sayilsin: bool = True, zorla: bool = False):
        if sayilsin and (zorla or self.oturma >= 60):
            self._yeni_gun_kontrol()
            self.s["bugun_kalkis"] += 1
            save_settings(self.s)
        self.oturma = 0.0
        self.sonraki_uyari = self.limit
        self.uyarildi = False

    def durum(self) -> str:
        if self.duraklatildi:
            return "durdu"
        if self.mola_bitis is not None:
            return "mola"
        return "kalk" if self.uyarildi else "sayiyor"

    # ------------------------------------------------ çizim
    def _isaretleri_guncelle(self):
        for item in self.m_sure.values():
            item.state = item.title == f"{self.s['sure_dk']} dk"
        for item in self.m_mola.values():
            item.state = item.title == f"{self.s['mola_dk']} dk boşta"
        self.m_ses.state = bool(self.s["ses"])
        self.m_ikon.state = bool(self.s["sadece_ikon"])
        self.m_giris.state = agent_installed()
        self.m_duraklat.title = "Devam et" if self.duraklatildi else "Duraklat"
        self.m_sure.title = f"Hatırlatma süresi · {self.s['sure_dk']} dk"
        self.m_mola.title = f"Kalktı sayılsın · {self.s['mola_dk']} dk boşta"
        for item in self.m_kalkma.values():
            item.state = item.title == f"{self.s['kalkma_dk']} dk mola"
        self.m_kalkma.title = f"Mola süresi · {self.s['kalkma_dk']} dk"
        self.m_sifirla.title = "Molayı bitir" if self.mola_bitis else "Kalktım, sıfırla"

    def _ekrani_guncelle(self):
        kalan = self.sonraki_uyari - self.oturma
        d = self.durum()
        dk = int(self.oturma // 60)

        mola_kalan = (self.mola_bitis - time.monotonic()) if self.mola_bitis else 0
        if d == "mola":
            ozet, deger = "Mola", mmss(mola_kalan)
            alt = f"Kalk, biraz yürü · Bitince {self.s['sure_dk']} dk yeniden başlar"
        elif d == "durdu":
            ozet, deger, alt = "Duraklatıldı", "", "Devam etmek için menüden “Devam et”"
        elif d == "kalk":
            ozet, deger = "Kalkma zamanı", f"{dk} dk"
            alt = f"{dk} dakikadır oturuyorsun · Bugün {self.s['bugun_kalkis']} kez kalktın"
        else:
            ozet, deger = "Hatırlatmaya kalan", mmss(kalan)
            alt = f"{dk} dakikadır oturuyorsun · Bugün {self.s['bugun_kalkis']} kez kalktın"

        # menü başlığı
        if self._header:
            self._header["sol"].setStringValue_(ozet)
            self._header["sag"].setStringValue_(deger)
            if d == "mola":
                oran = 1.0 - mola_kalan / max(1, self.s["kalkma_dk"] * 60)
            else:
                oran = self.oturma / self.limit
            self._header["bar"].setDoubleValue_(max(0.0, min(1.0, oran)))
            self._header["alt"].setStringValue_(alt)
        else:
            self.m_ozet.title = f"{ozet}  {deger}".strip()
            self.m_detay.title = alt

        # menü çubuğu
        metin = {"sayiyor": mmss(kalan), "kalk": "Kalk", "durdu": "Durdu",
                 "mola": "Mola " + mmss(mola_kalan)}[d]
        if self.s["sadece_ikon"]:
            metin = ""
        self._menu_cubugu(d, metin)

    def _menu_cubugu(self, d: str, metin: str):
        anahtar = (d, metin)
        if anahtar == self._son_durum:
            return
        self._son_durum = anahtar
        try:
            button = self._nsapp.nsstatusitem.button()
            sembol = {"sayiyor": "chair", "kalk": "figure.walk", "durdu": "pause",
                      "mola": "figure.walk"}[d]
            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                sembol, "Hareket")
            renk = None
            if d in ("kalk", "mola"):
                renk = _accent_color()
            elif d == "durdu":
                renk = NSColor.secondaryLabelColor()
            if renk is not None and img is not None:
                cfg = NSImageSymbolConfiguration.configurationWithHierarchicalColor_(renk)
                img = img.imageWithSymbolConfiguration_(cfg)
                img.setTemplate_(False)
            elif img is not None:
                img.setTemplate_(True)
            button.setImage_(img)
            button.setImagePosition_(2 if metin else 1)  # 2: ikon solda, 1: sadece ikon
            weight = 0.3 if d == "kalk" else 0.0
            attrs = {
                NSFontAttributeName:
                    NSFont.monospacedDigitSystemFontOfSize_weight_(13, weight),
            }
            if renk is not None:
                attrs[NSForegroundColorAttributeName] = renk
            title = f" {metin}" if metin else ""
            button.setAttributedTitle_(
                NSAttributedString.alloc().initWithString_attributes_(title, attrs))
        except Exception:
            # yerel API yoksa emoji ile sade metin
            ikon = {"sayiyor": "🪑", "kalk": "🚶", "durdu": "⏸", "mola": "🚶"}[d]
            self.title = f"{ikon} {metin}".strip()

    # ------------------------------------------------ zamanlayıcı
    def tick(self, _):
        self._ilk_kurulum()
        now = time.monotonic()
        gecen = now - self.son_tick
        self.son_tick = now

        if self.mola_bitis is not None and not self.duraklatildi:
            if now >= self.mola_bitis:
                self._mola_bitti_sor()
                return
            self._ekrani_guncelle()
            return

        if gecen > SLEEP_GAP:          # uykudan döndü: sessizce sıfırla
            self._kalkti(sayilsin=False)
        elif not self.duraklatildi:
            if now - self.son_idle_kontrol >= IDLE_EVERY:
                self.son_idle_kontrol = now
                if idle_seconds() >= self.s["mola_dk"] * 60:
                    self._kalkti(sayilsin=False)   # doğal mola: sayılmaz
                    self._ekrani_guncelle()
                    return
            self.oturma += gecen
            if self.oturma >= self.sonraki_uyari:
                self._uyari_goster()
                return
        self._ekrani_guncelle()

    # ------------------------------------------------ ekranda uyarı
    def _uyari_goster(self):
        dk = int(self.oturma // 60)
        self.uyarildi = True
        self._ekrani_guncelle()
        secim = "ertele5"
        try:
            from AppKit import NSAlert, NSApplication, NSSound
            if self.s["ses"]:
                snd = NSSound.soundNamed_("Glass")
                if snd is not None:
                    snd.play()
            a = NSAlert.alloc().init()
            a.setMessageText_("Hareket zamanı")
            a.setInformativeText_(
                f"{dk} dakikadır oturuyorsun. Kalk, biraz yürü ve esne.")
            a.addButtonWithTitle_("Kalktım")
            a.addButtonWithTitle_("5 dk ertele")
            a.addButtonWithTitle_("15 dk ertele")
            try:
                img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                    "figure.walk", "Hareket")
                if img is not None:
                    cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(48, 0.0)
                    img = img.imageWithSymbolConfiguration_(cfg) or img
                    a.setIcon_(img)
            except Exception:
                pass
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            w = a.window()
            w.setLevel_(3)                       # diğer pencerelerin üstünde
            w.setCollectionBehavior_(1 | 256)    # tüm masaüstleri + tam ekran
            r = a.runModal()
            secim = {1000: "kalktim", 1001: "ertele5", 1002: "ertele15"}.get(r, "ertele5")
        except Exception as e:
            log(f"uyarı penceresi açılamadı, bildirime geçiliyor: {e}")
            if self.notifier is not None:
                self.notifier.send(
                    "Hareket zamanı",
                    f"{dk} dakikadır oturuyorsun. Kalk, biraz yürü ve esne.",
                    self.s["ses"])
        # pencere açıkken geçen süre sayılmaz
        self.son_tick = time.monotonic()
        self.son_idle_kontrol = self.son_tick
        if secim == "kalktim":
            self._kalkti(sayilsin=True, zorla=True)
            self._mola_baslat()
            log("Kalktım seçildi, mola başladı")
        else:
            ek = 5 if secim == "ertele5" else 15
            self.uyarildi = False
            self.sonraki_uyari = self.oturma + ek * 60
            log(f"{ek} dk ertelendi")
        self._son_durum = None
        self._ekrani_guncelle()

    # ------------------------------------------------ menü eylemleri
    def duraklat(self, _):
        self.duraklatildi = not self.duraklatildi
        self.mola_bitis = None
        if not self.duraklatildi:
            self._kalkti(sayilsin=False)
        self._isaretleri_guncelle()
        self._ekrani_guncelle()

    def sifirla(self, _):
        if self.mola_bitis is not None:
            self._mola_bitir(bildir=False)
        else:
            self._kalkti()
            self._mola_baslat()
        self._ekrani_guncelle()

    def _mola_baslat(self):
        self.mola_bitis = time.monotonic() + self.s["kalkma_dk"] * 60
        self._son_durum = None
        self._isaretleri_guncelle()

    def _mola_bitir(self, bildir: bool):
        self.mola_bitis = None
        self._kalkti(sayilsin=False)
        self.son_tick = time.monotonic()
        self.son_idle_kontrol = self.son_tick
        self._son_durum = None
        self._isaretleri_guncelle()
        log("mola bitti")
        if bildir and self.notifier is not None:
            self.notifier.send("Mola bitti",
                               f"{self.s['sure_dk']} dakikalık sayaç yeniden başladı.",
                               self.s["ses"])

    def _mola_bitti_sor(self):
        """Mola bitti: kullanıcı 'Başlat' diyene kadar sayaç başlamaz."""
        self.mola_bitis = time.monotonic()   # pencere açıkken 00:00'da bekler
        self._ekrani_guncelle()
        secim = "baslat"
        ek = self.s["kalkma_dk"]
        try:
            from AppKit import NSAlert, NSApplication, NSSound
            if self.s["ses"]:
                snd = NSSound.soundNamed_("Glass")
                if snd is not None:
                    snd.play()
            a = NSAlert.alloc().init()
            a.setMessageText_("Mola bitti")
            a.setInformativeText_(
                f"Hazır olduğunda {self.s['sure_dk']} dakikalık sayacı başlat.")
            a.addButtonWithTitle_("Başlat")
            a.addButtonWithTitle_(f"{ek} dk daha mola")
            try:
                img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                    "chair", "Hareket")
                if img is not None:
                    cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(48, 0.0)
                    img = img.imageWithSymbolConfiguration_(cfg) or img
                    a.setIcon_(img)
            except Exception:
                pass
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            w = a.window()
            w.setLevel_(3)
            w.setCollectionBehavior_(1 | 256)
            r = a.runModal()
            secim = "baslat" if r == 1000 else "uzat"
        except Exception as e:
            log(f"mola sonu penceresi açılamadı: {e}")
            if self.notifier is not None:
                self.notifier.send("Mola bitti",
                                   f"{self.s['sure_dk']} dakikalık sayaç yeniden başladı.",
                                   self.s["ses"])
        if secim == "baslat":
            self._mola_bitir(bildir=False)
            log("mola bitti, sayaç başlatıldı")
        else:
            self.mola_bitis = time.monotonic() + ek * 60
            self.son_tick = time.monotonic()
            self.son_idle_kontrol = self.son_tick
            self._son_durum = None
            log(f"mola {ek} dk uzatıldı")
        self._ekrani_guncelle()

    def kalkma_sec(self, sender):
        self.s["kalkma_dk"] = int(sender.title.split()[0])
        save_settings(self.s)
        self._isaretleri_guncelle()

    def sure_sec(self, sender):
        self.s["sure_dk"] = int(sender.title.split()[0])
        save_settings(self.s)
        if self.oturma < self.limit:
            self.uyarildi = False
            self.sonraki_uyari = self.limit
        self._isaretleri_guncelle()
        self._ekrani_guncelle()

    def mola_sec(self, sender):
        self.s["mola_dk"] = int(sender.title.split()[0])
        save_settings(self.s)
        self._isaretleri_guncelle()

    def ses_degistir(self, _):
        self.s["ses"] = not self.s["ses"]
        save_settings(self.s)
        self._isaretleri_guncelle()

    def ikon_degistir(self, _):
        self.s["sadece_ikon"] = not self.s["sadece_ikon"]
        save_settings(self.s)
        self._isaretleri_guncelle()
        self._ekrani_guncelle()

    def giris_degistir(self, _):
        if not set_agent(not agent_installed()):
            rumps.alert("Hareket",
                        "Bu seçenek uygulama Hareket.app olarak kurulduğunda çalışır. "
                        "install.sh ile kurabilirsin.")
        self._isaretleri_guncelle()

    def cik(self, _):
        log("Hareket kapatıldı")
        rumps.quit_application()   # normal çıkış: LaunchAgent yeniden açmaz


def _accent_color():
    """Açık modda koyu yeşil, koyu modda açık yeşil (dinamik renk)."""
    def rgb(c):
        return NSColor.colorWithSRGBRed_green_blue_alpha_(
            c[0] / 255, c[1] / 255, c[2] / 255, 1.0)
    try:
        light, dark = rgb(ACCENT_LIGHT), rgb(ACCENT_DARK)

        def provider(appearance):
            name = appearance.bestMatchFromAppearancesWithNames_(
                ["NSAppearanceNameAqua", "NSAppearanceNameDarkAqua"])
            return dark if name and "Dark" in str(name) else light
        return NSColor.colorWithName_dynamicProvider_("HareketAccent", provider)
    except Exception:
        return NSColor.systemTealColor()


_APP = {}


def _uyandi():
    app = _APP.get("app")
    if app is not None:
        app._kalkti(sayilsin=False)
        log("Mac uyandı, sayaç sıfırlandı")


try:  # rumps uyanma olayı (yoksa tick'teki boşluk kontrolü yeterli)
    rumps.events.on_wake(_uyandi)
except Exception:
    pass

if __name__ == "__main__":
    a = HareketApp()
    _APP["app"] = a
    a.run()
