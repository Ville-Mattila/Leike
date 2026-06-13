@echo off
REM Rebuilds dist\Leike.exe from leike.py
cd /d "%~dp0"
python -m PyInstaller --noconfirm --onefile --windowed ^
  --name Leike ^
  --icon leike.ico ^
  --add-data "leike.ico;." ^
  --collect-all tkinterdnd2 ^
  leike.py
echo.
echo Done. The exe is in the "dist" folder.
pause
