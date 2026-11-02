@echo off
chcp 65001 > nul
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%.."

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    pause
    exit /b 1
)

python -c "import nuitka" 2>nul
if errorlevel 1 (
    echo [ERROR] Nuitka is not installed. Run:
    echo.
    echo     python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

python -c "import PyQt6" 2>nul
if errorlevel 1 (
    echo [ERROR] PyQt6 is not installed. Run:
    echo.
    echo     python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

python -c "import zstandard" 2>nul
if errorlevel 1 (
    echo [ERROR] zstandard is not installed. Run:
    echo.
    echo     python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "%SCRIPT_DIR%assets\icon.ico" (
    echo [ERROR] gui\assets\icon.ico is missing - it must be committed to the repo.
    pause
    exit /b 1
)

if not exist "%SCRIPT_DIR%assets\logo.png" (
    echo [ERROR] gui\assets\logo.png is missing - it must be committed to the repo.
    pause
    exit /b 1
)

echo Building dist\tg-ws-turn-proxy.dist\tg-ws-turn-proxy.exe with Nuitka. This can take a while ...
python "%SCRIPT_DIR%build_exe.py"
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed - see the output above.
    pause
    exit /b 1
)

if not exist "installer.iss" (
    echo.
    echo [ERROR] installer.iss not found in the repository root.
    pause
    exit /b 1
)

set "ISCC_PATH=%ISCC%"
if defined ISCC_PATH if not exist "%ISCC_PATH%" (
    echo [WARN] ISCC path from the ISCC variable does not exist: "%ISCC_PATH%"
    set "ISCC_PATH="
)
if not defined ISCC_PATH for %%I in (ISCC.exe) do if not "%%~$PATH:I"=="" set "ISCC_PATH=%%~$PATH:I"

set "PF=%ProgramFiles%"
set "PF86=%ProgramFiles(x86)%"
if not defined ISCC_PATH if exist "%PF%\Inno Setup 7\ISCC.exe" set "ISCC_PATH=%PF%\Inno Setup 7\ISCC.exe"
if not defined ISCC_PATH if exist "%PF%\Inno Setup 6\ISCC.exe" set "ISCC_PATH=%PF%\Inno Setup 6\ISCC.exe"
if not defined ISCC_PATH if exist "%PF86%\Inno Setup 7\ISCC.exe" set "ISCC_PATH=%PF86%\Inno Setup 7\ISCC.exe"
if not defined ISCC_PATH if exist "%PF86%\Inno Setup 6\ISCC.exe" set "ISCC_PATH=%PF86%\Inno Setup 6\ISCC.exe"
if not defined ISCC_PATH if defined PF for /d %%D in ("%PF%\Inno Setup*") do if exist "%%~fD\ISCC.exe" set "ISCC_PATH=%%~fD\ISCC.exe"
if not defined ISCC_PATH if defined PF86 for /d %%D in ("%PF86%\Inno Setup*") do if exist "%%~fD\ISCC.exe" set "ISCC_PATH=%%~fD\ISCC.exe"

if not defined ISCC_PATH (
    echo.
    echo [ERROR] Inno Setup compiler ^(ISCC.exe^) was not found.
    echo         Install Inno Setup 6.3+ from https://jrsoftware.org/isinfo.php
    echo         or set ISCC to the full path of ISCC.exe.
    echo.
    echo         The portable build is ready: dist\tg-ws-turn-proxy.dist\
    pause
    exit /b 1
)

echo.
echo [INFO] Building the installer with "%ISCC_PATH%" ...
"%ISCC_PATH%" installer.iss
if errorlevel 1 (
    echo.
    echo [ERROR] Inno Setup failed - see the output above.
    pause
    exit /b 1
)

echo.
echo [OK] Portable build: dist\tg-ws-turn-proxy.dist\
echo [OK] Installer     : dist\tg-ws-turn-proxy-setup.exe
pause
exit /b 0