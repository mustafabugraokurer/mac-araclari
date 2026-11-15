#!/bin/bash
# Hareket'i durdurur ve kaldırır (ayarların kalır).
LABEL="com.bugra.hareket"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
pkill -f "Hareket.app/Contents/MacOS/Hareket" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$HOME/Applications/Hareket.app"
echo "✓ Hareket kaldırıldı."
echo "  Ayarları da silmek istersen: rm -rf ~/Library/Application\\ Support/Hareket"
