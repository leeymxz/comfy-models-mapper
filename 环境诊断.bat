@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title ComfyUI 模型目录映射工具 - 环境诊断

set "LOG=%~dp0环境诊断.log"
>"%LOG%" echo === 环境诊断  %date% %time% ===

echo ==========================================
echo   ComfyUI 模型目录映射工具  环境诊断
echo ==========================================
echo.

echo [1] 系统信息
echo     CPU 架构    : %PROCESSOR_ARCHITECTURE%
echo     当前用户    : %USERNAME%
echo     工作目录    : %~dp0
echo.

echo [2] 程序文件
if exist "%~dp0comfy_models_mapper.py" (echo     comfy_models_mapper.py  存在) else (echo     comfy_models_mapper.py  缺失  ^<== 问题在这)
if exist "%~dp0崩溃日志.txt" (echo     崩溃日志.txt            存在  ^<== 上次启动崩过) else (echo     崩溃日志.txt            无)
echo.

echo [3] python路径.txt（手动指定用）
if exist "%~dp0python路径.txt" (
  set "CUSTOM="
  set /p CUSTOM=<"%~dp0python路径.txt"
  echo     内容 : !CUSTOM!
) else (
  echo     未创建（可选）
)
echo.

echo [4] where 命令结果（这个顺序决定脚本会先看到谁）
echo     --- where pythonw ---
for /f "delims=" %%P in ('where pythonw 2^>nul') do echo         %%P
echo     --- where python ---
for /f "delims=" %%P in ('where python 2^>nul') do echo         %%P
echo.

echo [5] 微软商店代理检测（9009 的元凶）
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe"  echo     WindowsApps\python.exe   存在
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\pythonw.exe" echo     WindowsApps\pythonw.exe  存在
echo     上面这些是"应用执行别名"，批处理里调用可能直接返回 9009。
echo     可在 设置 → 应用 → 高级应用设置 → 应用执行别名 里关掉。
echo.

echo [6] 逐个实测候选解释器（能跑 + 带 tkinter 才算可用）
call :PROBE "%~dp0python\pythonw.exe"
call :PROBE "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe"
for %%d in (c d e f g h i j k) do (
  for /d %%p in ("%%d:\Python3*") do call :PROBE "%%p\pythonw.exe"
)
for /d %%p in ("%LOCALAPPDATA%\Programs\Python\Python3*") do call :PROBE "%%p\pythonw.exe"
for /f "delims=" %%P in ('where pythonw 2^>nul') do call :PROBE "%%P"
for /f "delims=" %%P in ('where python 2^>nul') do call :PROBE "%%P"
echo.

echo [7] py 启动器登记的版本
for /f "delims=" %%L in ('py -0p 2^>nul') do echo     %%L
echo.

echo ==========================================
echo   诊断结束。整份报告也写进了 环境诊断.log
echo   如果上面 [6] 里有标 [可用] 的，把它的路径写进
echo   python路径.txt 就一定能启动。
echo ==========================================
echo.
pause
exit /b 0


:PROBE
rem %1 = 候选路径
if not exist "%~1" goto :eof
set "C=%~1"
set "MARK="
echo(!C! | findstr /i /c:"WindowsApps" >nul
if not errorlevel 1 set "MARK=  <== 商店代理，可能 9009"
"!C!" -c "import tkinter" >nul 2>nul
if errorlevel 1 (
  echo     [不可用] !C!!MARK!
  >>"%LOG%" echo [不可用] !C!!MARK!
) else (
  echo     [可用]   !C!!MARK!
  >>"%LOG%" echo [可用]   !C!!MARK!
)
goto :eof
