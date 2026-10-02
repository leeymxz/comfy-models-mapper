@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title ComfyUI 模型目录映射工具

set "LOG=%~dp0启动诊断.log"
>"%LOG%" echo === 解释器探测  %date% %time% ===
>>"%LOG%" echo 工作目录 : %~dp0

echo ==========================================
echo   ComfyUI 模型目录映射工具  正在启动...
echo ==========================================
echo.

set "SCRIPT=%~dp0comfy_models_mapper.py"
if not exist "%SCRIPT%" (
  echo   [错误] 找不到主程序 comfy_models_mapper.py
  echo.
  echo   请确认本 bat 和主程序放在同一个文件夹里。
  echo.
  pause
  exit /b 2
)

rem ---- 依次尝试各路来源，第一个通过实测的胜出 ----
set "PY="
call :TRY_BUNDLED
call :TRY_MANUAL
call :TRY_LAUNCHER
call :TRY_REGISTRY
call :TRY_SCAN
call :TRY_WHERE
call :TRY_STORE

if not defined PY goto NOPYTHON

echo   使用解释器 : !PY!
echo   正在启动，请稍候...
echo.
>>"%LOG%" echo [最终采用] !PY!

"!PY!" "%SCRIPT%"
set "RC=%ERRORLEVEL%"
>>"%LOG%" echo [程序退出码] %RC%

if "%RC%"=="0" exit /b 0
if "%RC%"=="9009" goto E9009

echo.
echo   ------------------------------------------
echo   [失败] 程序异常退出，退出码 %RC%
echo   ------------------------------------------
echo.
echo   若目录下出现 崩溃日志.txt，里面有完整堆栈。
echo   解释器探测记录见 启动诊断.log
echo.
pause
exit /b %RC%


rem ============ 候选来源 ============

:TRY_BUNDLED
if defined PY goto :eof
if exist "%~dp0python\pythonw.exe" call :ACCEPT "%~dp0python\pythonw.exe"
if not defined PY if exist "%~dp0python\python.exe" call :ACCEPT "%~dp0python\python.exe"
goto :eof

:TRY_MANUAL
if defined PY goto :eof
if not exist "%~dp0python路径.txt" goto :eof
set "CUSTOM="
set /p CUSTOM=<"%~dp0python路径.txt"
if not defined CUSTOM goto :eof
set "CUSTOM=!CUSTOM:"=!"
call :ACCEPT_EXE "!CUSTOM!"
goto :eof

:TRY_LAUNCHER
if defined PY goto :eof
set "PYEXE="
if exist "%SystemRoot%\py.exe" set "PYEXE=%SystemRoot%\py.exe"
if not defined PYEXE if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\py.exe" set "PYEXE=%LOCALAPPDATA%\Microsoft\WindowsApps\py.exe"
if not defined PYEXE goto :eof
>>"%LOG%" echo [来源] py 启动器 : !PYEXE!
for /f "delims=" %%R in ('"!PYEXE!" -3 -c "import sys;print(sys.executable)" 2^>nul') do (
  if not defined PY call :ACCEPT_EXE "%%R"
)
goto :eof

:TRY_REGISTRY
if defined PY goto :eof
for %%K in (
  "HKLM\SOFTWARE\Python\PythonCore"
  "HKCU\SOFTWARE\Python\PythonCore"
  "HKLM\SOFTWARE\WOW6432Node\Python\PythonCore"
) do (
  if not defined PY (
    for /f "tokens=2*" %%A in ('reg query %%K /s /v InstallPath 2^>nul ^| findstr /i "REG_SZ"') do (
      if not defined PY call :ACCEPT_DIR "%%B"
    )
  )
)
goto :eof

:TRY_SCAN
if defined PY goto :eof
for %%d in (c d e f g h i j k) do (
  if not defined PY if exist "%%d:\" (
    for /d %%p in ("%%d:\Python3*") do if not defined PY call :ACCEPT_DIR "%%p"
    for /d %%p in ("%%d:\Program Files\Python3*") do if not defined PY call :ACCEPT_DIR "%%p"
    for /d %%p in ("%%d:\Program Files (x86)\Python3*") do if not defined PY call :ACCEPT_DIR "%%p"
  )
)
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python" (
  for /d %%p in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if not defined PY call :ACCEPT_DIR "%%p"
)
if not defined PY if exist "%AppData%\Python\Python3*" (
  for /d %%p in ("%AppData%\Python\Python3*") do if not defined PY call :ACCEPT_DIR "%%p"
)
goto :eof

:TRY_WHERE
if defined PY goto :eof
for /f "delims=" %%P in ('where pythonw 2^>nul') do if not defined PY call :ACCEPT "%%P"
for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY call :ACCEPT "%%P"
goto :eof

:TRY_STORE
if defined PY goto :eof
for /f "delims=" %%P in ('where pythonw 2^>nul') do if not defined PY call :ACCEPT_STORE "%%P"
for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY call :ACCEPT_STORE "%%P"
goto :eof


rem ============ 候选判定 ============

rem %1 = 解释器完整路径。必须能真正跑起来且带 tkinter 才算数。
:ACCEPT
if defined PY goto :eof
if not exist "%~1" goto :eof
set "C=%~1"
echo(!C! | findstr /i /c:"WindowsApps" >nul
if not errorlevel 1 (
  >>"%LOG%" echo   跳过 [WindowsApps 商店代理]  !C!
  goto :eof
)
"!C!" -c "import tkinter" >nul 2>nul
if errorlevel 1 (
  >>"%LOG%" echo   跳过 [无法运行 或 缺 tkinter]  !C!
  goto :eof
)
>>"%LOG%" echo   [实测通过] !C!
set "PY=!C!"
goto :eof

rem %1 = exe 路径，优先用同目录的 pythonw.exe（不带黑窗口）
:ACCEPT_EXE
if defined PY goto :eof
if not exist "%~1" goto :eof
set "E=%~1"
if /i not "%~nx1"=="pythonw.exe" if exist "%~dp1pythonw.exe" call :ACCEPT "%~dp1pythonw.exe"
if not defined PY call :ACCEPT "!E!"
goto :eof

rem %1 = 安装目录，优先 pythonw.exe
:ACCEPT_DIR
if defined PY goto :eof
set "D=%~1"
if "!D:~-1!"=="\" set "D=!D:~0,-1!"
if not exist "!D!\" goto :eof
if exist "!D!\pythonw.exe" call :ACCEPT "!D!\pythonw.exe"
if not defined PY if exist "!D!\python.exe" call :ACCEPT "!D!\python.exe"
goto :eof

rem 最后兜底：商店代理。它在有些机器上能跑，有些机器返回 9009。
:ACCEPT_STORE
if defined PY goto :eof
if not exist "%~1" goto :eof
>>"%LOG%" echo   兜底候选 [WindowsApps 商店代理，可能 9009]  %~1
set "PY=%~1"
goto :eof


rem ============ 失败分支 ============

:NOPYTHON
echo   [错误] 没有找到可用的 Python 运行环境。
echo.
echo   探测记录已写入 启动诊断.log
echo.
echo   解决办法：
echo     1. 到 https://www.python.org/downloads/windows/ 下载 Python 3.8+
echo     2. 安装时务必勾选这两项：
echo          [x] Add python.exe to PATH
echo          [x] tcl/tk and IDLE
echo     3. 装完关掉窗口重新双击本文件
echo.
echo   如果 Python 装在很特殊的位置，可以把 python.exe 的完整路径
echo   单独写成一行，存到本目录的  python路径.txt ，本脚本会优先用它。
echo.
pause
exit /b 1

:E9009
echo.
echo   ------------------------------------------
echo   [失败] 退出码 9009 —— 解释器根本没跑起来
echo   ------------------------------------------
echo.
echo   9009 是 Windows 的"命令未找到"。最常见的原因：
echo     找到的是微软商店的 python.exe 空壳（WindowsApps 里的转发代理），
echo     它在批处理里被调用会直接失败。
echo.
echo   解决办法（做第 1 条基本就好了）：
echo     1. 到 https://www.python.org/downloads/windows/ 装一个 Python 3.8+，
echo        安装时勾选 "Add python.exe to PATH" 和 "tcl/tk and IDLE"；
echo     2. 或打开 Windows 设置 → 应用 → 高级应用设置 → 应用执行别名，
echo        把 python.exe / python3.exe 两个开关关掉；
echo     3. 或把可用的 python.exe 完整路径写进本目录的 python路径.txt。
echo.
echo   本次探测记录见 启动诊断.log
echo.
pause
exit /b 9009
