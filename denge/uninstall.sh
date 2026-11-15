#!/bin/bash
# Denge'yi durdurur ve kaldırır (ayarların ve günlük kayıtların kalır).
LABEL="com.bugra.denge"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
pkill -f "Denge.app/Contents/MacOS/Denge" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$HOME/Applications/Denge.app"
echo "✓ Denge kaldırıldı."
echo "  Ayarları da silmek istersen: rm -rf ~/Library/Application\\ Support/Denge"
