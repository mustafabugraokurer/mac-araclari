"""
Namaz.app oluşturur. Genelde doğrudan değil, install.sh üzerinden çalışır:
    ./install.sh
Elle:
    python3 setup.py py2app   ->  dist/Namaz.app
"""
import os

from setuptools import setup

OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "Namaz",
        "CFBundleDisplayName": "Namaz",
        "CFBundleIdentifier": "com.bugra.namaz",
        "CFBundleShortVersionString": "1.1",
        "CFBundleVersion": "1.1",
        "LSUIElement": True,          # Dock'ta görünmez, sadece menü çubuğu
        "LSMinimumSystemVersion": "12.0",
        "NSHumanReadableCopyright": "© 2026 Mustafa Buğra Okurer · MIT",
    },
    "packages": ["rumps"],
    "includes": ["UserNotifications", "vakit", "sehirler", "zoneinfo", "dil"],
}
if os.path.exists("Namaz.icns"):
    OPTIONS["iconfile"] = "Namaz.icns"

setup(
    app=["namaz.py"],
    name="Namaz",
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
