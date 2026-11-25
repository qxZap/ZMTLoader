@echo off
setlocal

REM Get paths
set "current_dir=%cd%"
set "desktop=%USERPROFILE%\Desktop"
set "target=%current_dir%\ZMTLoader.exe"
set "shortcut=%desktop%\ZMTLoader.lnk"

REM Create the shortcut using PowerShell
powershell -nologo -command ^
  "$s=(New-Object -COM WScript.Shell).CreateShortcut('%shortcut%');" ^
  "$s.TargetPath='%target%';" ^
  "$s.WorkingDirectory='%current_dir%';" ^
  "$s.WindowStyle=1;" ^
  "$s.Save()"

echo Shortcut created on Desktop.
pause
