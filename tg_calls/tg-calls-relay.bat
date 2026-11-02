@echo off
chcp 65001 > nul
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "PYEXE="
where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE (
    echo [ERROR] Python not found in PATH.
    pause
    exit /b 1
)

set "MODE=%~1"
if "%MODE%"=="" set "MODE=relay"
set "EXTRA="
shift
:collect
if "%~1"=="" goto collected
set "EXTRA=%EXTRA% %1"
shift
goto collect
:collected

set "PYTHONIOENCODING=utf-8"
set "PS1=%SCRIPT_DIR%tg_calls_relay"

if /i "%MODE%"=="mint" goto mint
if /i "%MODE%"=="dry-run" goto run
if /i "%MODE%"=="capture-only" goto run
if /i "%MODE%"=="relay" goto need_admin
echo [ERROR] Unknown mode "%MODE%". Use: relay ^| dry-run ^| capture-only ^| mint
pause
exit /b 1

:mint
%PYEXE% -m tg_calls_relay mint%EXTRA%
set "RC=%errorlevel%"
echo.
pause
exit /b %RC%

:need_admin
set "IS_ADMIN=False"
for /f %%A in ('powershell -NoProfile -Command "([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)" 2^>nul') do set "IS_ADMIN=%%A"
if /i "%IS_ADMIN%"=="True" goto run

echo   Requesting admin rights (WinDivert needs them, like winws)...
set "ELEV=%TEMP%\tg_calls_relay_elev.bat"
if exist "%ELEV%" del /q "%ELEV%" >nul 2>&1
> "%ELEV%" echo @echo off
>> "%ELEV%" echo chcp 65001 ^> nul
>> "%ELEV%" echo cd /d "%SCRIPT_DIR%"
>> "%ELEV%" echo set PYTHONIOENCODING=utf-8
>> "%ELEV%" echo %PYEXE% -m tg_calls_relay%EXTRA%
>> "%ELEV%" echo echo.
>> "%ELEV%" echo pause
powershell -NoProfile -Command "Start-Process -FilePath '%ELEV%' -Verb RunAs"
del /q "%ELEV%" >nul 2>&1
exit /b 0

:run
if /i "%MODE%"=="dry-run" (
    %PYEXE% -m tg_calls_relay --dry-run%EXTRA%
) else if /i "%MODE%"=="capture-only" (
    %PYEXE% -m tg_calls_relay --capture-only%EXTRA%
) else (
    %PYEXE% -m tg_calls_relay%EXTRA%
)
set "RC=%errorlevel%"
echo.
pause
exit /b %RC%