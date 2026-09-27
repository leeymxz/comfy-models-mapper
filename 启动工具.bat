@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==========================================
echo   ComfyUI 模型目录映射工具  正在启动...
echo ==========================================
echo.

set "PY="

if exist "C:\Python314\pythonw.exe" set "PY=C:\Python314\pythonw.exe"
if not defined PY if exist "C:\Python314\python.exe" set "PY=C:\Python314\python.exe"

if not defined PY (
  for %%D in (
    "%LOCALAPPDATA%\Programs\Python\Python313"
    "%LOCALAPPDATA%\Programs\Python\Python312"
    "%LOCALAPPDATA%\Programs\Python\Python311"
    "%LOCALAPPDATA%\Programs\Python\Python310"
  ) do (
    if not defined PY if exist "%%~D\pythonw.exe" set "PY=%%~D\pythonw.exe"
  )
)

if not defined PY (
  for /f "delims=" %%P in ('where pythonw 2^>nul') do (
    if not defined PY set "PY=%%P"
  )
)

if not defined PY (
  for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PY set "PY=%%P"
  )
)

if not defined PY goto NOPYTHON

echo   使用解释器 : !PY!
echo   正在启动，请稍候...
echo.

"!PY!" "%~dp0comfy_models_mapper.py"
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" goto FAILED
exit /b 0

:NOPYTHON
echo   [错误] 没有找到 Python 运行环境。
echo.
echo   本工具需要 Python 3.8 以上，且安装时勾选了 tcl/tk。
echo   下载地址: https://www.python.org/downloads/windows/
echo.
pause
exit /b 1

:FAILED
echo.
echo   ------------------------------------------
echo   [失败] 程序异常退出，退出码 %RC%
echo   ------------------------------------------
echo.
echo   请把上面的报错信息截图反馈。
echo.
pause
exit /b %RC%
