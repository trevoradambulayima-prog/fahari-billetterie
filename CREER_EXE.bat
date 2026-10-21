@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo  Creation de Billetterie.exe (quelques minutes)...
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name Billetterie --add-data "logo_fahari.png;." billetterie.py
if errorlevel 1 ( pause & exit /b 1 )
copy /y dist\Billetterie.exe . >nul
echo.
echo  Termine : Billetterie.exe est dans ce dossier. Vous pouvez le copier sur un autre PC Windows
echo  (MySQL doit etre installe et demarre sur ce PC ou accessible sur le reseau).
pause
