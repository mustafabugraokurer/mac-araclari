#!/bin/bash
cd "$(dirname "$0")"
./install.sh 2>&1 | tee kurulum.log
echo "BITTI: $?" >> kurulum.log
echo ""
echo "Bu pencereyi kapatabilirsin."
