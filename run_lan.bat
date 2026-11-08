@echo off
chcp 65001 >nul
cd /d "%~dp0"
title CRM АвтоБрокер (доступ из сети)
python -c "import flask" 2>nul || python -m pip install -r requirements.txt
echo.
echo  CRM доступна в локальной сети. Адрес для сотрудников:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do for /f "tokens=*" %%b in ("%%a") do echo     http://%%b:5000
echo.
echo  Если с другого компьютера не открывается — разрешите Python в брандмауэре Windows.
echo  Окно не закрывайте — пока оно открыто, CRM работает.
echo.
python app.py --lan
pause
