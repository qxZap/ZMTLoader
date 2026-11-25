@echo off
setlocal
rem Builds out\mt_plugin_ZMTLoader.dll and runs the offline tests. Needs MSVC 2022 (any edition) and Python 3.
set VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe
for /f "usebackq delims=" %%i in (`call "%VSWHERE%" -latest -products * -property installationPath`) do set VS=%%i
if not exist "%VS%\VC\Auxiliary\Build\vcvars64.bat" (echo MSVC not found & exit /b 1)
call "%VS%\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d "%~dp0"
if not exist out\obj mkdir out\obj
cl /nologo /O2 /MT /EHsc /std:c++17 /LD /Fo:out\obj\ plugins\zmt_loader.cpp /Fe:out\mt_plugin_ZMTLoader.dll /link /NOLOGO user32.lib || exit /b 1
python tools\zmt_loader_test.py demo || exit /b 1
cl /nologo /O2 /MT /EHsc /std:c++17 /Fo:out\obj\ tools\zmt_fixpak_test.cpp /Fe:out\zmt_fixpak_test.exe || exit /b 1
out\zmt_fixpak_test.exe || exit /b 1
echo built %~dp0out
