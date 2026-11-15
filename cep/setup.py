"""Cep.app oluşturur. Genelde install.sh üzerinden çalışır."""
import os

from setuptools import setup

OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "Cep",
        "CFBundleDisplayName": "Cep",
        "CFBundleIdentifier": "com.bugra.cep",
        "CFBundleShortVersionString": "1.1",
        "CFBundleVersion": "1.1",
        "LSUIElement": True,
        "LSMinimumSystemVersion": "12.0",
        "NSHumanReadableCopyright": "© 2026 Mustafa Buğra Okurer · MIT",
    },
    "includes": ["store", "panel", "Vision"],
    "packages": ["quickmachotkey"],
}
if os.path.exists("Cep.icns"):
    OPTIONS["iconfile"] = "Cep.icns"

setup(app=["cep.py"], name="Cep", options={"py2app": OPTIONS}, setup_requires=["py2app"])
