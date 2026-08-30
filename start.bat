@echo off
cd /d %~dp0
start "" http://localhost:8172/
python app.py
