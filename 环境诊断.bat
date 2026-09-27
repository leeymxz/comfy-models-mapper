@echo off
chcp 65001 >nul 2>nul
title ComfyUI Mapper - Environment Check
cd /d "%~dp0"

echo ==========================================
echo   Environment Diagnostic
echo ==========================================
echo.

echo [1] Working directory:
echo     %CD%
echo.

echo [2] Files present:
if exist "comfy_models_mapper.py" (echo     OK  comfy_models_mapper.py) else (echo     MISSING comfy_models_mapper.py)
echo.

echo [3] Searching Python...
set "PY="
if exist "C:\Python314\python.exe" set "PY=C:\Python314\python.exe"
if not defined PY if exist "C:\Python314\pythonw.exe" set "PY=C:\Python314\pythonw.exe"

if not defined PY (
  for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PY set "PY=%%P"
  )
)

if not defined PY (
  echo     NOT FOUND
  echo.
  echo     Please install Python 3.8+ from:
  echo     https://www.python.org/downloads/windows/
  echo     Remember to check "tcl/tk and IDLE" during install.
  echo.
  goto END
)

echo     Found: %PY%
echo.

echo [4] Python version:
"%PY%" -c "import sys; print('    ' + sys.version.replace(chr(10),' '))"
echo.

echo [5] tkinter check:
"%PY%" -c "import tkinter; print('    OK  tkinter ' + str(tkinter.TkVersion))" 2>nul
if errorlevel 1 echo     FAILED - tkinter is missing! Reinstall Python with tcl/tk option.
echo.

echo [6] Try importing the tool:
"%PY%" -c "import sys; sys.path.insert(0,'.'); import comfy_models_mapper; print('    OK  module imports fine')" 2>&1

echo.
echo ==========================================
echo   Diagnostic finished. Press any key.
echo ==========================================
:END
pause
