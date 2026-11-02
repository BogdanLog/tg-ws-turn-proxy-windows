@echo off
chcp 65001 > nul

setlocal

set "LOCAL_BIN=%~dp0bin\"
set "ZAPRET_BIN=%~dp0bin\"
if not exist "%ZAPRET_BIN%winws.exe" set "ZAPRET_BIN=C:\zapret\bin\"
if defined ZAPRET_BIN_USER set "ZAPRET_BIN=%ZAPRET_BIN_USER%\"
if not exist "%ZAPRET_BIN%winws.exe" (
    echo [ERROR] winws.exe не найден.
    echo.
    echo   Проверенные папки:
    echo     "%LOCAL_BIN%"
    echo     "%ZAPRET_BIN%"
    echo.
    echo   Если приложение установлено, переустановите его или добавьте
    echo   папку zapret в исключения антивируса: winws.exe, WinDivert.dll
    echo   и cygwin1.dll должны лежать в zapretin.
    echo.
    pause
    exit /b 1
)

if not exist "%ZAPRET_BIN%cygwin1.dll" (
    echo [ERROR] рядом с winws.exe нет cygwin1.dll - winws.exe не стартует.
    echo.
    pause
    exit /b 1
)
if not exist "%ZAPRET_BIN%WinDivert.dll" (
    echo [ERROR] рядом с winws.exe нет WinDivert.dll - драйвер не загрузится.
    echo.
    pause
    exit /b 1
)

set "LISTS=%~dp0..\lists\"
if not exist "%LISTS%list-cloudflare.txt" (
    echo [ERROR] list-cloudflare.txt не найден в "%LISTS%"
    echo.
    pause
    exit /b 1
)

tasklist /FI "IMAGENAME eq winws.exe" 2>nul | find /I "winws.exe" >nul
if not errorlevel 1 (
    echo [i] winws.exe уже запущен - этот профиль не нужен.
    pause
    exit /b 0
)

set "STUNFAKE="
if exist "%ZAPRET_BIN%stun.bin" (
    set "STUNFAKE=--dpi-desync-fake-stun=%ZAPRET_BIN%stun.bin"
) else (
    echo [i] stun.bin нет - правило STUN сработает без payload-а.
)

if defined TG_CALLS_GUI goto run
set "IS_ADMIN=False"
for /f %%A in ('powershell -NoProfile -Command "([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)" 2^>nul') do set "IS_ADMIN=%%A"
if /i "%IS_ADMIN%"=="True" goto run

echo   Запрос прав администратора (WinDivert, как и у winws)...
set "ELEV=%TEMP%\winws_tg_calls_relay_elev.bat"
if exist "%ELEV%" del /q "%ELEV%" >nul 2>&1
> "%ELEV%" echo @echo off
>> "%ELEV%" echo chcp 65001 ^> nul
>> "%ELEV%" echo cd /d "%~dp0"
>> "%ELEV%" echo call "%~f0" --elevated
>> "%ELEV%" echo del /q "%%~f0"
powershell -NoProfile -Command "Start-Process -FilePath '%ELEV%' -Verb RunAs"
exit /b 0

:run
set WINWS_ARGS=--wf-tcp=80,443 --wf-udp=1400,3478,3482,4244,5349,7985 --filter-tcp=443 --hostlist="%LISTS%list-cloudflare.txt" --ip-id=zero --dpi-desync=fake,multisplit --dpi-desync-split-pos=1 --dpi-desync-split-seqovl=681 --dpi-desync-fooling=ts --dpi-desync-repeats=8 --dpi-desync-fake-tls="%ZAPRET_BIN%tls_clienthello_www_google_com.bin" --dpi-desync-split-seqovl-pattern="%ZAPRET_BIN%tls_clienthello_www_google_com.bin" --new --filter-udp=1400,3478,3482,4244,5349,7985 --filter-l7=stun --dpi-desync=fake --dpi-desync-repeats=8 %STUNFAKE%

if defined TG_CALLS_GUI goto rungui
start "zapret: tg-calls-relay" "%ZAPRET_BIN%winws.exe" %WINWS_ARGS%
exit /b 0

:rungui
"%ZAPRET_BIN%winws.exe" %WINWS_ARGS%
exit /b %errorlevel%