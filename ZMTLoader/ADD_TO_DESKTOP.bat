@echo off
setlocal

REM Get the current directory
set "current_dir=%cd%"

REM Get the user's desktop path
set "desktop=%USERPROFILE%\Desktop"

REM Copy ZMTLoader.exe to desktop
copy "%current_dir%\ZMTLoader.exe" "%desktop%\" /Y

REM Run the copied ZMTLoader.exe from the desktop
start "" "%desktop%\ZMTLoader.exe"

endlocal