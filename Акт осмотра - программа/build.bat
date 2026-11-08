@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  Сборка программы "Акт осмотра" (AktOsmotra.exe)
echo ============================================
echo.
python --version >nul 2>&1
if errorlevel 1 (
    echo Python не найден. Установите Python 3.10+ с python.org
    echo и при установке отметьте "Add python.exe to PATH".
    pause
    exit /b 1
)
echo [1/2] Устанавливаю pywebview и pyinstaller...
python -m pip install --upgrade pywebview pyinstaller
if errorlevel 1 goto :fail
echo.
echo [2/2] Собираю AktOsmotra.exe...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name AktOsmotra ^
    --icon icon.ico ^
    --add-data "akt_osmotra.html;." ^
    app.py
if errorlevel 1 goto :fail
echo.
echo Готово! Программа: %~dp0dist\AktOsmotra.exe
echo Её можно скопировать на рабочий стол или на флешку.
explorer "%~dp0dist"
pause
exit /b 0
:fail
echo.
echo Сборка не удалась. Скопируйте текст ошибки выше и пришлите мне.
pause
exit /b 1
