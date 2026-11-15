#!/bin/bash
# Cep'i durdurur ve kaldırır (geçmişin ve ayarların kalır).
LABEL="com.bugra.cep"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
pkill -f "Cep.app/Contents/MacOS/Cep" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$HOME/Applications/Cep.app"
echo "✓ Cep kaldırıldı."
echo "  Geçmişi de silmek istersen: rm -rf ~/Library/Application\\ Support/Cep"
