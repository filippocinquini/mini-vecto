#!/bin/bash
# Double click to run the whole model on macOS (first time: right click > Open).
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null; then echo "Python 3 not found. Install it from https://www.python.org/downloads/ and try again."; read -p "Press Enter to close"; exit 1; fi
python3 -m pip install --quiet -r requirements.txt 2>/dev/null || python3 -m pip install --quiet --user -r requirements.txt
python3 run_all.py
read -p "Press Enter to close"
