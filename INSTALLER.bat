@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Installation - Billetterie Fahari Afrika
echo.
echo  === Installation de la Billetterie Fahari Afrika ===
echo.
where python >nul 2>nul
if errorlevel 1 (
  echo  Python nest pas installe.
  echo  1. Telechargez Python 3 sur https://www.python.org/downloads/
  echo  2. Pendant linstallation, cochez "Add python.exe to PATH"
  echo  3. Relancez ce fichier INSTALLER.bat
  start https://www.python.org/downloads/
  pause
  exit /b 1
)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo  ERREUR : verifiez votre connexion Internet et relancez INSTALLER.bat
  pause
  exit /b 1
)
echo.
echo  Installation terminee. Double-cliquez sur LANCER.bat pour ouvrir lapplication.
echo  (MySQL doit etre demarre : XAMPP ^> bouton Start a cote de MySQL)
pause
