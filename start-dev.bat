@echo off
rem Рабочая копия журнала. Порт 8173, чтобы личный журнал на 8172 работал одновременно.
cd /d %~dp0
set PORT=8173
start "" http://localhost:8173/
python app.py
