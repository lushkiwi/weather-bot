@echo off
cd /d C:\Users\shikh\dev\testbench
python -m kalshi_weather_bot.app --port 8787 --execute-demo --production-shadow --interval-seconds 900
