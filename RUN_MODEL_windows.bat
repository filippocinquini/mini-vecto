@echo off
rem Double click to run the whole model on Windows.
cd /d "%~dp0"
py -m pip install -q -r requirements.txt
py run_all.py
pause
