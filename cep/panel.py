"""
Cep — menü çubuğundan açılan panel.

Üstte arama + ayarlar, altında "Geçmiş" ve "Taşıma alanı" sekmeleri.
Geçmiş: Sabitlenenler · Sık kullanılanlar · Geçmiş. Satırın üzerine gelince
sabitle ve sil düğmeleri görünür. Klavye: ↑↓ seç, ↩ yapıştır, ⌘1–9, ⌘P sabitle,
⌘⌫ sil, Esc kapat.
"""
import time

import objc
from AppKit import (
    NSAttributedString, NSBezierPath, NSButton, NSColor, NSEvent, NSFont,
    NSFontAttributeName, NSForegroundColorAttributeName, NSImage, NSMakePoint,
    NSMakeRect, NSMakeSize, NSMutableParagraphStyle, NSPanel,
    NSParagraphStyleAttributeName, NSRectFillUsingOperation, NSScreen,
    NSScrollView, NSSearchField, NSSegmentedControl, NSTextField,
    NSTrackingArea, NSView, NSVisualEffectView, NSWorkspace,
)
from Foundation import NSObject

from store import Store
from dil import t

W = 380
PAD = 12
ROW_H = 46
HDR_H = 28
UST = 84          # arama + sekmeler
ALT = 40          # alt çubuk
LISTE_MIN, LISTE_MAX = 150, 440

MOD_SHIFT, MOD_ALT, MOD_CMD = 1 << 17, 1 << 19, 1 << 20


def yazi(s, boyut=13, agirlik=0.0, renk=None, hiza=0, mono=False):
    ps = NSMutableParagraphStyle.alloc().init()
    ps.setLineBreakMode_(4)
    ps.setAlignment_(hiza)
    font = (NSFont.monospacedSystemFontOfSize_weight_(boyut - 1, agirlik) if mono
            else NSFont.systemFontOfSize_weight_(boyut, agirlik))
    return NSAttributedString.alloc().initWithString_attributes_(s, {
        NSFontAttributeName: font,
        NSForegroundColorAttributeName: renk or NSColor.labelColor(),
        NSParagraphStyleAttributeName: ps,
    })


def sembol(ad, boyut=15):
    img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(ad, None)
    if img is not None:
        img.setTemplate_(True)
    return img


def ciz(img, rect, renk=None):
    """Görseli oranını koruyarak çiz; şablon görselleri verilen renge boya."""
    if img is None:
        return
    sw, sh = img.size().width, img.size().height
    if sw <= 0 or sh <= 0:
        return
    o = min(rect.size.width / sw, rect.size.height / sh)
    dw, dh = sw * o, sh * o
    hedef = NSMakeRect(rect.origin.x + (rect.size.width - dw) / 2,
                       rect.origin.y + (rect.size.height - dh) / 2, dw, dh)
    if img.isTemplate() and renk is not None:
        boyali = NSImage.alloc().initWithSize_(NSMakeSize(dw, dh))
        boyali.lockFocus()
        img.drawInRect_fromRect_operation_fraction_(
            NSMakeRect(0, 0, dw, dh), NSMakeRect(0, 0, 0, 0), 2, 1.0)
        renk.set()
        NSRectFillUsingOperation(NSMakeRect(0, 0, dw, dh), 5)  # sourceAtop
        boyali.unlockFocus()
        img = boyali
    img.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
        hedef, NSMakeRect(0, 0, 0, 0), 2, 1.0, True, None)


def icinde(r, p):
    return (r.origin.x <= p.x <= r.origin.x + r.size.width and
            r.origin.y <= p.y <= r.origin.y + r.size.height)


# ---------------------------------------------------------------- pencere
class KeyPanel(NSPanel):
    """Uygulamayı öne getirmeden klavye alabilen panel."""

    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return False

    def performKeyEquivalent_(self, event):
        ctrl = getattr(self, "ctrl", None)
        if ctrl is not None:
            try:
                if ctrl.kisayol(event):
                    return True
            except Exception as e:
                ctrl.log(f"kısayol hatası: {e}")
        return objc.super(KeyPanel, self).performKeyEquivalent_(event)

    def cancelOperation_(self, sender):
        ctrl = getattr(self, "ctrl", None)
        if ctrl is not None:
            ctrl.kapat()


class FlippedView(NSView):
    def isFlipped(self):
        return True


# ---------------------------------------------------------------- liste
class HistoryView(NSView):

    def initWithFrame_(self, frame):
        self = objc.super(HistoryView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.ctrl = None
        self.hover = -1
        self._ta = None
        return self

    def isFlipped(self):
        return True

    def acceptsFirstMouse_(self, event):
        return True

    def updateTrackingAreas(self):
        objc.super(HistoryView, self).updateTrackingAreas()
        if self._ta is not None:
            self.removeTrackingArea_(self._ta)
        # girme/çıkma + hareket + her zaman etkin + görünen alan
        self._ta = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(), 0x01 | 0x02 | 0x80 | 0x200, self, None)
        self.addTrackingArea_(self._ta)

    @objc.python_method
    def satir_at(self, p):
        for i, r in enumerate(self.ctrl.satirlar):
            if r["y"] <= p.y < r["y"] + r["h"]:
                return i
        return -1

    @objc.python_method
    def dugmeler(self, r):
        w = self.bounds().size.width
        sag = w - 6 - 8
        sil = NSMakeRect(sag - 26, r["y"] + (ROW_H - 26) / 2, 26, 26)
        pin = NSMakeRect(sag - 56, r["y"] + (ROW_H - 26) / 2, 26, 26)
        return pin, sil

    def mouseMoved_(self, event):
        p = self.convertPoint_fromView_(event.locationInWindow(), None)
        i = self.satir_at(p)
        if i != self.hover:
            self.hover = i
            self.setNeedsDisplay_(True)

    def mouseExited_(self, event):
        self.hover = -1
        self.setNeedsDisplay_(True)

    def mouseDown_(self, event):
        p = self.convertPoint_fromView_(event.locationInWindow(), None)
        i = self.satir_at(p)
        if i < 0:
            return
        r = self.ctrl.satirlar[i]
        if r["tur"] != "oge":
            return
        pin, sil = self.dugmeler(r)
        if icinde(sil, p):
            self.ctrl.sil(r["oge"]["id"])
        elif icinde(pin, p):
            self.ctrl.sabitle(r["oge"]["id"])
        else:
            self.ctrl.secili = i
            self.ctrl.kullan(r["oge"]["id"])

    def drawRect_(self, dirty):
        c = self.ctrl
        if c is None:
            return
        w = self.bounds().size.width
        acc = NSColor.controlAccentColor()
        sec = NSColor.secondaryLabelColor()
        for i, r in enumerate(c.satirlar):
            y = r["y"]
            if r["tur"] == "baslik":
                yazi(r["metin"].upper(), 11, 0.4, sec).drawInRect_(
                    NSMakeRect(PAD + 2, y + 10, w - 2 * PAD, 15))
                continue
            if r["tur"] == "bos":
                yazi(r["metin"], 13, 0, sec, hiza=1).drawInRect_(
                    NSMakeRect(PAD, y + 14, w - 2 * PAD, 18))
                continue
            oge = r["oge"]
            kutu = NSMakeRect(6, y + 2, w - 12, ROW_H - 4)
            secili = i == c.secili
            ustunde = i == self.hover
            if secili:
                acc.set()
                NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(kutu, 8, 8).fill()
            elif ustunde:
                NSColor.colorWithWhite_alpha_(0.5, 0.14).set()
                NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(kutu, 8, 8).fill()
            ana = NSColor.whiteColor() if secili else NSColor.labelColor()
            ikinci = NSColor.colorWithWhite_alpha_(1.0, 0.8) if secili else sec

            # simge
            ik = NSMakeRect(kutu.origin.x + 8, y + 9, 28, 28)
            tur = oge["kind"]
            if tur not in ("gorsel", "renk"):
                (NSColor.colorWithWhite_alpha_(1.0, 0.2) if secili
                 else NSColor.colorWithWhite_alpha_(0.5, 0.15)).set()
                NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(ik, 7, 7).fill()
                ic = NSMakeRect(ik.origin.x + 6, ik.origin.y + 6, 16, 16)
            else:
                ic = ik
            try:
                ciz(c.app._ikon(oge), ic, ana)
            except Exception:
                pass

            # yazılar
            x0 = kutu.origin.x + 46
            gosterim = ustunde or secili
            sag_bosluk = 70 if gosterim else 40
            tw = kutu.size.width - 46 - sag_bosluk
            mono = tur == "metin" and any(k in (oge.get("text") or "")
                                          for k in ("(", "=", "{", ";", "import "))
            yazi(Store.label(oge), 13, 0, ana, mono=mono).drawInRect_(
                NSMakeRect(x0, y + 6, tw, 18))
            alt = Store.detail(oge)
            k = int(oge.get("kullanim", 0))
            if k >= 2:
                alt += t(" · {k} kez", k=k)
            yazi(alt, 11, 0, ikinci).drawInRect_(NSMakeRect(x0, y + 25, tw, 15))

            # sağ taraf
            if gosterim:
                pin, sil = self.dugmeler(r)
                for rr, ad in ((pin, "pin.slash" if oge["pinned"] else "pin"), (sil, "trash")):
                    (NSColor.colorWithWhite_alpha_(1.0, 0.18) if secili
                     else NSColor.colorWithWhite_alpha_(0.5, 0.16)).set()
                    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rr, 6, 6).fill()
                    ciz(sembol(ad), NSMakeRect(rr.origin.x + 6, rr.origin.y + 6, 14, 14), ana)
            elif r.get("no"):
                yazi(f"⌘{r['no']}", 11, 0, ikinci, hiza=2).drawInRect_(
                    NSMakeRect(kutu.origin.x + kutu.size.width - 44, y + 15, 36, 15))


# ---------------------------------------------------------------- denetleyici
class PanelController(NSObject):

    def init(self):
        self = objc.super(PanelController, self).init()
        if self is None:
            return None
        self.app = None
        self.satirlar = []
        self.secili = -1
        self.sekme = 0
        self._izleyici = None
        self.son_kapanis = 0.0
        return self

    @objc.python_method
    def log(self, m):
        try:
            self.app._log(m)
        except Exception:
            pass

    @objc.python_method
    def kur(self, app, shelf_cls):
        self.app = app
        p = KeyPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, 400), (1 << 7), 2, False)  # borderless + nonactivating
        p.ctrl = self
        p.setLevel_(3)
        p.setOpaque_(False)
        p.setBackgroundColor_(NSColor.clearColor())
        p.setHasShadow_(True)
        p.setHidesOnDeactivate_(False)
        p.setBecomesKeyOnlyIfNeeded_(False)
        p.setCollectionBehavior_(1 | 256)
        p.setDelegate_(self)

        fx = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, W, 400))
        fx.setMaterial_(6)          # popover
        fx.setBlendingMode_(0)
        fx.setState_(1)
        fx.setWantsLayer_(True)
        fx.layer().setCornerRadius_(14)
        fx.layer().setMasksToBounds_(True)
        fx.setAutoresizingMask_(2 | 16)
        kok = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, W, 400))
        kok.setAutoresizingMask_(2 | 16)
        fx.addSubview_(kok)
        p.setContentView_(fx)

        ara = NSSearchField.alloc().initWithFrame_(NSMakeRect(PAD, PAD, W - 2 * PAD - 36, 28))
        ara.setPlaceholderString_(t("Ara"))
        ara.setDelegate_(self)
        ara.setFocusRingType_(1)
        kok.addSubview_(ara)

        dis = NSButton.buttonWithImage_target_action_(sembol("gearshape"), self, "ayarlar:")
        dis.setBordered_(False)
        dis.setFrame_(NSMakeRect(W - PAD - 30, PAD, 30, 28))
        dis.setToolTip_(t("Ayarlar"))
        kok.addSubview_(dis)

        seg = NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_(
            [t("Geçmiş"), t("Taşıma alanı")], 0, self, "sekmeDegisti:")
        seg.setFrame_(NSMakeRect(PAD, 48, W - 2 * PAD, 26))
        try:
            seg.setSegmentDistribution_(2)   # eşit genişlik
        except Exception:
            pass
        seg.setSelectedSegment_(0)
        kok.addSubview_(seg)

        sc = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, UST, W, 300))
        sc.setHasVerticalScroller_(True)
        sc.setAutohidesScrollers_(True)
        sc.setDrawsBackground_(False)
        sc.setBorderType_(0)
        hv = HistoryView.alloc().initWithFrame_(NSMakeRect(0, 0, W, 300))
        hv.ctrl = self
        sc.setDocumentView_(hv)
        kok.addSubview_(sc)

        sc2 = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, UST, W, 300))
        sc2.setHasVerticalScroller_(True)
        sc2.setAutohidesScrollers_(True)
        sc2.setDrawsBackground_(False)
        sc2.setBorderType_(0)
        sv = shelf_cls.alloc().initWithFrame_(NSMakeRect(0, 0, W - 4, 300))
        sv.app = app
        sc2.setDocumentView_(sv)
        sc2.setHidden_(True)
        kok.addSubview_(sc2)

        bilgi = NSTextField.labelWithString_(t("Geçmiş 30 gün tutulur"))
        bilgi.setFont_(NSFont.systemFontOfSize_(11))
        bilgi.setTextColor_(NSColor.secondaryLabelColor())
        kok.addSubview_(bilgi)

        temizle = NSButton.buttonWithTitle_target_action_(
            t("Sabitlenmemişleri temizle"), self, "temizle:")
        temizle.setBordered_(False)
        temizle.setFont_(NSFont.systemFontOfSize_(12))
        try:
            temizle.setContentTintColor_(NSColor.systemRedColor())
        except Exception:
            pass
        kok.addSubview_(temizle)

        self.panel, self.kok, self.ara, self.seg = p, kok, ara, seg
        self.sc, self.hv, self.sc2, self.sv = sc, hv, sc2, sv
        self.bilgi, self.temizle_btn = bilgi, temizle

    # ---- aç / kapat
    @objc.python_method
    def acik(self):
        return bool(self.panel and self.panel.isVisible())

    @objc.python_method
    def ac(self, konum="ikon", sekme=0):
        self.sekme = sekme
        self.seg.setSelectedSegment_(sekme)
        self.ara.setStringValue_("")
        self.app.store.shelf_cleanup()
        self.yenile(ilk=True)
        h = self.panel.frame().size.height
        m = NSEvent.mouseLocation()
        scr = NSScreen.mainScreen()
        for s in NSScreen.screens():
            f = s.frame()
            if icinde(f, m):
                scr = s
                break
        vf = scr.visibleFrame()
        if konum == "ikon":
            try:
                bf = self.app.status.button().window().frame()
                cx = bf.origin.x + bf.size.width / 2
                ust = bf.origin.y - 6
                bs = self.app.status.button().window().screen()
                if bs is not None:
                    vf = bs.visibleFrame()
            except Exception:
                cx, ust = m.x, vf.origin.y + vf.size.height - 6
        else:
            cx, ust = m.x, m.y - 12
        x = max(vf.origin.x + 8, min(cx - W / 2, vf.origin.x + vf.size.width - W - 8))
        ust = min(ust, vf.origin.y + vf.size.height - 6)
        y = max(vf.origin.y + 8, ust - h)
        self.panel.setFrameOrigin_(NSMakePoint(x, y))
        self.panel.makeKeyAndOrderFront_(None)
        self.panel.makeFirstResponder_(self.ara)
        if self._izleyici is None:
            # panel dışına tıklanınca kapat
            self._izleyici = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                (1 << 1) | (1 << 3), lambda ev: self.kapat())

    @objc.python_method
    def kapat(self):
        if self._izleyici is not None:
            NSEvent.removeMonitor_(self._izleyici)
            self._izleyici = None
        if self.panel is not None and self.panel.isVisible():
            self.panel.orderOut_(None)
            self.son_kapanis = time.time()

    def windowDidResignKey_(self, note):
        self.kapat()

    # ---- içerik
    @objc.python_method
    def _satirlari_kur(self):
        st = self.app.store
        sorgu = str(self.ara.stringValue() or "").strip()
        satirlar, y = [], 4

        def baslik(metin):
            nonlocal y
            satirlar.append({"tur": "baslik", "metin": metin, "y": y, "h": HDR_H})
            y += HDR_H

        def oge(o, no=None):
            nonlocal y
            satirlar.append({"tur": "oge", "oge": o, "y": y, "h": ROW_H, "no": no})
            y += ROW_H

        if sorgu:
            sonuc = st.search(sorgu)
            if sonuc:
                baslik(t("Sonuçlar · {n}", n=len(sonuc)))
                for i, o in enumerate(sonuc[:200]):
                    oge(o, i + 1 if i < 9 else None)
            else:
                satirlar.append({"tur": "bos", "metin": t("Sonuç yok"), "y": y, "h": 48})
                y += 48
        else:
            pin = st.pinned()
            sik = st.frequent()
            sik_id = {o["id"] for o in sik}
            gecmis = [o for o in st.recent() if o["id"] not in sik_id]
            no = 1
            if pin:
                baslik(t("Sabitlenenler · sen silene kadar kalır"))
                for o in pin:
                    oge(o, no if no <= 9 else None)
                    no += 1
            if sik:
                baslik(t("Sık kullanılanlar"))
                for o in sik:
                    oge(o, no if no <= 9 else None)
                    no += 1
            baslik(t("Geçmiş") + (t(" · kayıt duraklatıldı") if self.app.ayar.get("duraklat") else ""))
            if not gecmis:
                satirlar.append({"tur": "bos", "metin": t("Henüz kopyalanan bir şey yok"),
                                 "y": y, "h": 48})
                y += 48
            for o in gecmis[:200]:
                oge(o, no if no <= 9 else None)
                no += 1
        self.satirlar = satirlar
        return y + 6

    @objc.python_method
    def _ogeler(self):
        return [i for i, r in enumerate(self.satirlar) if r["tur"] == "oge"]

    @objc.python_method
    def yenile(self, ilk=False):
        if self.app is None:
            return
        n = len(self.app.store.shelf)
        self.seg.setLabel_forSegment_(t("Taşıma alanı") + (f" ({n})" if n else ""), 1)
        if self.sekme == 0:
            onceki_id = None
            if not ilk and 0 <= self.secili < len(self.satirlar):
                onceki_id = (self.satirlar[self.secili].get("oge") or {}).get("id")
            toplam = self._satirlari_kur()
            ogeler = self._ogeler()
            self.secili = ogeler[0] if ogeler else -1
            if onceki_id:
                for i in ogeler:
                    if self.satirlar[i]["oge"]["id"] == onceki_id:
                        self.secili = i
                        break
            liste_h = max(LISTE_MIN, min(LISTE_MAX, toplam))
        else:
            toplam = self.sv.yerlesim()["h"]
            liste_h = max(LISTE_MIN, min(LISTE_MAX, toplam))
        self._yerlestir(liste_h, toplam)

    @objc.python_method
    def _yerlestir(self, liste_h, toplam):
        H = UST + liste_h + ALT
        fr = self.panel.frame()
        ust = fr.origin.y + fr.size.height
        if abs(fr.size.height - H) > 0.5:
            self.panel.setFrame_display_(NSMakeRect(fr.origin.x, ust - H, W, H), True)
        self.kok.setFrame_(NSMakeRect(0, 0, W, H))
        gecmis = self.sekme == 0
        self.sc.setHidden_(not gecmis)
        self.sc2.setHidden_(gecmis)
        hedef = self.sc if gecmis else self.sc2
        hedef.setFrame_(NSMakeRect(0, UST, W, liste_h))
        icg = hedef.contentSize().width
        if gecmis:
            self.hv.setFrame_(NSMakeRect(0, 0, icg, max(toplam, liste_h)))
            self.hv.setNeedsDisplay_(True)
        else:
            self.sv.setFrame_(NSMakeRect(0, 0, icg, max(toplam, liste_h)))
            self.sv.setNeedsDisplay_(True)
        ay = UST + liste_h
        self.bilgi.setHidden_(not gecmis)
        self.temizle_btn.setHidden_(not gecmis)
        self.bilgi.setFrame_(NSMakeRect(PAD + 2, ay + 12, 160, 16))
        self.temizle_btn.sizeToFit()
        bw = self.temizle_btn.frame().size.width
        self.temizle_btn.setFrame_(NSMakeRect(W - PAD - bw, ay + 8, bw, 24))

    @objc.python_method
    def _gorunur_yap(self):
        if 0 <= self.secili < len(self.satirlar):
            r = self.satirlar[self.secili]
            self.hv.scrollRectToVisible_(NSMakeRect(0, r["y"] - 4, 10, r["h"] + 8))
        self.hv.setNeedsDisplay_(True)

    # ---- eylemler
    @objc.python_method
    def kullan(self, item_id):
        self.kapat()
        self.app.ogeyi_kullan(item_id)

    @objc.python_method
    def sil(self, item_id):
        self.app.store.remove(item_id)
        self.yenile()

    @objc.python_method
    def sabitle(self, item_id):
        self.app.store.toggle_pin(item_id)
        self.yenile()

    @objc.python_method
    def _secili_oge(self):
        if 0 <= self.secili < len(self.satirlar):
            return self.satirlar[self.secili].get("oge")
        return None

    @objc.python_method
    def kisayol(self, event):
        f = event.modifierFlags()
        ch = str(event.charactersIgnoringModifiers() or "").lower()
        if not (f & MOD_CMD):
            return False
        if ch == "w":
            self.kapat()
            return True
        if self.sekme != 0:
            return False
        if ch in "123456789" and ch:
            n = int(ch)
            for i in self._ogeler():
                if self.satirlar[i].get("no") == n:
                    self.kullan(self.satirlar[i]["oge"]["id"])
                    return True
            return True
        if ch == "p":
            o = self._secili_oge()
            if o:
                self.sabitle(o["id"])
            return True
        return False

    def control_textView_doCommandBySelector_(self, control, textView, sel):
        s = sel if isinstance(sel, str) else bytes(sel).decode()
        ogeler = self._ogeler()
        if s == "cancelOperation:":
            if str(self.ara.stringValue() or ""):
                self.ara.setStringValue_("")
                self.yenile()
            else:
                self.kapat()
            return True
        if self.sekme != 0:
            return False
        if s in ("moveDown:", "moveUp:") and ogeler:
            if self.secili not in ogeler:
                self.secili = ogeler[0]
            else:
                k = ogeler.index(self.secili) + (1 if s == "moveDown:" else -1)
                self.secili = ogeler[max(0, min(len(ogeler) - 1, k))]
            self._gorunur_yap()
            return True
        if s == "insertNewline:":
            o = self._secili_oge()
            if o:
                self.kullan(o["id"])
            return True
        if s == "deleteToBeginningOfLine:" and not str(self.ara.stringValue() or ""):
            o = self._secili_oge()      # ⌘⌫ (arama boşken) seçili öğeyi siler
            if o:
                self.sil(o["id"])
            return True
        return False

    def controlTextDidChange_(self, note):
        self.yenile(ilk=True)
        self.hv.scrollPoint_(NSMakePoint(0, 0))

    def sekmeDegisti_(self, sender):
        self.sekme = int(sender.selectedSegment())
        self.yenile(ilk=True)
        if self.sekme == 0:
            self.panel.makeFirstResponder_(self.ara)

    def ayarlar_(self, sender):
        menu = self.app._ayar_menusu()
        menu.popUpMenuPositioningItem_atLocation_inView_(
            None, NSMakePoint(0, sender.frame().size.height + 4), sender)

    def temizle_(self, sender):
        self.app.clearUnpinned_(None)
        self.yenile()
