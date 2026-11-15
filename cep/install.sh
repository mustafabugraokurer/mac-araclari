#!/bin/bash
# Cep'i kurar: derler, ~/Applications'a koyar, oturum açınca başlatır, çökerse yeniden açar.
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="Cep"
LABEL="com.bugra.cep"
APP_DIR="$HOME/Applications"
AGENT="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/Cep.log"
UID_NUM="$(id -u)"

echo "→ Python ortamı hazırlanıyor"
PY="${PYTHON:-python3}"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

if [ -f icon_1024.png ] && [ ! -f Cep.icns ]; then
  echo "→ Uygulama ikonu oluşturuluyor"
  rm -rf Cep.iconset && mkdir Cep.iconset
  for s in 16 32 64 128 256 512; do
    sips -z $s $s icon_1024.png --out "Cep.iconset/icon_${s}x${s}.png" >/dev/null
    d=$((s * 2))
    sips -z $d $d icon_1024.png --out "Cep.iconset/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns Cep.iconset -o Cep.icns
  rm -rf Cep.iconset
fi

echo "→ Cep.app derleniyor"
rm -rf build dist
.venv/bin/python setup.py py2app >/dev/null

echo "→ Çalışan sürüm kapatılıyor"
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
pkill -f "$APP_NAME.app/Contents/MacOS/$APP_NAME" 2>/dev/null || true
sleep 1

echo "→ ~/Applications klasörüne kopyalanıyor"
mkdir -p "$APP_DIR"
rm -rf "$APP_DIR/$APP_NAME.app"
cp -R "dist/$APP_NAME.app" "$APP_DIR/"
xattr -dr com.apple.quarantine "$APP_DIR/$APP_NAME.app" 2>/dev/null || true

echo "→ Oturum açınca başlatma ayarlanıyor"
mkdir -p "$(dirname "$AGENT")" "$(dirname "$LOG")"
cat > "$AGENT" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$APP_DIR/$APP_NAME.app/Contents/MacOS/$APP_NAME</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key>
  <dict><key>SuccessfulExit</key><false/></dict>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST

launchctl bootstrap "gui/$UID_NUM" "$AGENT"

echo ""
echo "✓ Cep kuruldu ve çalışıyor. Menü çubuğunda pano ikonuna bak."
echo "  Seçince yapıştırma için: Sistem Ayarları → Gizlilik ve Güvenlik → Erişilebilirlik → Cep'i aç."
echo "  (Her yeniden kurulumdan sonra bu izni kapatıp açman gerekebilir.)"
echo "  Kaldırmak için: ./uninstall.sh"
