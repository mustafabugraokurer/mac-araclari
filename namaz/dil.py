"""
Dil seçimi (Türkçe / English).

Metinler Türkçe yazılır ve t() ile çevrilir:  t("{dk} dk ertele", dk=5)
İngilizce karşılığı yoksa Türkçesi gösterilir. "oto": Mac'in diline göre.
"""
import os
import subprocess

_DURUM = {"kod": "tr"}
EN = {}


def sistem_dili() -> str:
    try:
        from Foundation import NSLocale
        diller = NSLocale.preferredLanguages()
        if diller and str(diller[0]).lower().startswith("tr"):
            return "tr"
        return "en"
    except Exception:
        return "tr"


def ayarla(secim, sozluk: dict) -> str:
    """secim: "oto" / "tr" / "en". Etkin dil kodunu döndürür."""
    _DURUM["kod"] = sistem_dili() if secim not in ("tr", "en") else secim
    EN.clear()
    EN.update(sozluk)
    return _DURUM["kod"]


def kod() -> str:
    return _DURUM["kod"]


def t(metin: str, **kw) -> str:
    s = EN.get(metin, metin) if _DURUM["kod"] == "en" else metin
    return s.format(**kw) if kw else s


def yeniden_baslat(agent_var: bool) -> None:
    """Dil değişince uygulamayı yeniden aç (menüler baştan kurulsun)."""
    try:
        from Foundation import NSBundle
        yol = str(NSBundle.mainBundle().bundlePath())
    except Exception:
        yol = ""
    if agent_var:
        os._exit(1)          # LaunchAgent (KeepAlive) yeniden başlatır
    if yol.endswith(".app"):
        subprocess.Popen(["/bin/sh", "-c", f'sleep 1; open "{yol}"'])
    os._exit(0)
