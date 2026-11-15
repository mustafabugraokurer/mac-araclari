"""
Hareket.app oluşturur. Genelde doğrudan değil, install.sh üzerinden çalışır:
    ./install.sh
Elle:
    python3 setup.py py2app   ->  dist/Hareket.app
"""
import os

from setuptools import setup

OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "Hareket",
        "CFBundleDisplayName": "Hareket",
        "CFBundleIdentifier": "com.bugra.hareket",
        "CFBundleShortVersionString": "1.1",
        "CFBundleVersion": "1.1",
        "LSUIElement": True,          # Dock'ta görünmez, sadece menü çubuğu
        "LSMinimumSystemVersion": "12.0",
        "NSHumanReadableCopyright": "© 2026 Buğra Okurer · MIT",
    },
    "packages": ["rumps"],
    "includes": ["UserNotifications"],
}
if os.path.exists("Hareket.icns"):
    OPTIONS["iconfile"] = "Hareket.icns"

setup(
    app=["hareket.py"],
    name="Hareket",
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
