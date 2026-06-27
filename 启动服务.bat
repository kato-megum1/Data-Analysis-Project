@echo off
chcp 65001 >nul
:: 数据分析 Agent 集群 — 双击启动（Windows）
cd /d "%~dp0"
python start.py
pause
