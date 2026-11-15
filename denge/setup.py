"""
Denge.app oluşturur. Genelde doğrudan değil, install.sh üzerinden çalışır:
    ./install.sh
Elle:
    python3 setup.py py2app   ->  dist/Denge.app
"""
import os

from setuptools import setup

OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "Denge",
        "CFBundleDisplayName": "Denge",
        "CFBundleIdentifier": "com.bugra.denge",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1.0",
        "LSUIElement": True,          # Dock'ta görünmez, sadece menü çubuğu
        "LSMinimumSystemVersion": "12.0",
        "NSHumanReadableCopyright": "© 2026 Mustafa Buğra Okurer · MIT",
    },
    "packages": ["rumps"],
    "includes": ["UserNotifications", "Quartz"],
}
if os.path.exists("Denge.icns"):
    OPTIONS["iconfile"] = "Denge.icns"

setup(
    app=["denge.py"],
    name="Denge",
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
