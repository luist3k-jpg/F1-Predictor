#!/bin/bash
cd "$(dirname "$0")"
python3 download_f1_data.py
echo ""
echo "=== DONE - press any key to close ==="
read -n 1
