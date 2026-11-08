@echo off
chcp 65001 >nul
cd /d "%~dp0"
title CRM АвтоБрокер
where python >nul 2>nul
if errorlevel 1 (
  echo Python не найден. Установите Python 3.10+ с python.org и отметьте "Add python.exe to PATH".
  pause
  exit /b 1
)
python -c "import flask" 2>nul || (
  echo Устанавливаю Flask...
  python -m pip install -r requirements.txt
)
echo.
echo  Чтобы сотрудники заходили с других компьютеров в вашей сети, запустите run_lan.bat
echo  Окно не закрывайте — пока оно открыто, CRM работает.
echo.
python app.py
pause
