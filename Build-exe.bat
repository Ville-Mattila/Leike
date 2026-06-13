@echo off
REM Rebuilds dist\VideoTrimCropResize.exe from video_trim_crop.py
cd /d "%~dp0"
python -m PyInstaller --noconfirm --onefile --windowed ^
  --name VideoTrimCropResize ^
  --collect-all tkinterdnd2 ^
  --collect-all sv_ttk ^
  video_trim_crop.py
echo.
echo Done. The exe is in the "dist" folder.
pause
