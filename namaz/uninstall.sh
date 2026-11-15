#!/bin/bash
# Namaz'ı durdurur ve kaldırır (ayarların kalır).
LABEL="com.bugra.namaz"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
pkill -f "Namaz.app/Contents/MacOS/Namaz" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$HOME/Applications/Namaz.app"
echo "✓ Namaz kaldırıldı."
echo "  Ayarları da silmek istersen: rm -rf ~/Library/Application\\ Support/Namaz"
