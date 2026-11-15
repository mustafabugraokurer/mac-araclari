#!/bin/bash
cd "$(dirname "$0")"
{
echo "== Cep.log (son 25 satır)"; tail -25 ~/Library/Logs/Cep.log
echo; echo "== çalışan süreç"; pgrep -fl "Cep.app" || echo "yok"
} > teshis.log 2>&1
echo "TAMAM" >> teshis.log
