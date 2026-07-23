@echo off
setlocal

title SceneSmith VTT

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul 2>&1

REM ############ BAT SETTINGS

REM Name of file to run without drag and drop
set "APP_NAME=app.py"

REM Server port (must match VTT_PORT env var if set, otherwise app.py defaults to 3000)
set "PORT=3000"

REM Embedded Python Version
set "PY_VER=3.12.10"

REM ################### Vars for the Bat File

set "APP_PATH=%SCRIPT_DIR%%APP_NAME%"
set "APP_WORKDIR=%SCRIPT_DIR%"

set "PY_DIR=python-embed-%PY_VER%"
set "PY_EXE=%SCRIPT_DIR%%PY_DIR%\python.exe"
set "PY_ZIP=python-%PY_VER%-embed-amd64.zip"
set "PY_URL=https://www.python.org/ftp/python/%PY_VER%/%PY_ZIP%"
set "GET_PIP=https://bootstrap.pypa.io/get-pip.py"
set "ACTIVE_PY_EXE="
set "HAS_REQUIREMENTS=0"
set "NEEDS_REQUIREMENTS=0"
set "REQUIREMENTS_REASON="
set "LOCAL_IP=unknown"

:parse_args
if "%~1"=="" goto args_done
set "ARG_EXT=%~x1"
if /I "%ARG_EXT%"==".py" goto set_app_target
if /I "%ARG_EXT%"==".pyw" goto set_app_target
echo [!] Ignoring unknown arg: %~1
shift
goto parse_args

:set_app_target
set "APP_NAME=%~nx1"
set "APP_PATH=%~f1"
set "APP_WORKDIR=%~dp1"
shift
goto parse_args
:args_done

echo.
echo ==========================================
echo   SceneSmith VTT Launcher
echo   Running: %APP_NAME%
echo ==========================================
echo.

if not exist "%APP_PATH%" (
    echo ERROR: Script not found: %APP_PATH%
    pause
    popd >nul 2>&1
    exit /b 1
)

set "ACTIVE_PY_EXE=%PY_EXE%"
if exist "%PY_EXE%" goto requirements

echo [1/3] Downloading Python %PY_VER% embeddable package...
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_ZIP%'" 2>nul
if not exist "%PY_ZIP%" (
    echo ERROR: Download failed. Check internet connection.
    pause
    popd >nul 2>&1
    exit /b 1
)

echo [2/3] Extracting Python...
powershell -NoProfile -Command "Expand-Archive -Path '%PY_ZIP%' -DestinationPath '%PY_DIR%' -Force" >nul 2>&1
del "%PY_ZIP%" 2>nul

for %%f in (%PY_DIR%\python*._pth) do (
    powershell -NoProfile -Command "$c = Get-Content '%%f' -Raw; $c = $c -replace '(?m)^#\s*import site','import site'; Set-Content '%%f' $c" >nul 2>&1
)

powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%GET_PIP%' -OutFile '%PY_DIR%\get-pip.py'" 2>nul
"%PY_EXE%" "%PY_DIR%\get-pip.py" --no-warn-script-location >nul 2>&1
del "%PY_DIR%\get-pip.py" 2>nul
set "NEEDS_REQUIREMENTS=1"
set "REQUIREMENTS_REASON=Fresh embedded runtime detected"
echo [OK] Embedded Python ready.

:requirements
set "HAS_REQUIREMENTS=0"
if exist "requirements.txt" set "HAS_REQUIREMENTS=1"

if not "%HAS_REQUIREMENTS%"=="1" goto launch
if not "%NEEDS_REQUIREMENTS%"=="1" goto launch
echo [3/3] %REQUIREMENTS_REASON% - installing from requirements.txt ...
"%ACTIVE_PY_EXE%" -m pip install -r requirements.txt --no-warn-script-location
if errorlevel 1 (
    echo ERROR: Failed to install requirements. Check requirements.txt.
    pause
    popd >nul 2>&1
    exit /b 1
)
echo [OK] Requirements installed.

:launch
REM Detect LAN IP for sharing with other devices
for /f "delims=" %%I in ('powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred | Where-Object {$_.IPAddress -notlike '127.*'} | Sort-Object InterfaceMetric | Select-Object -First 1 -ExpandProperty IPAddress) 2>$null"') do set "LOCAL_IP=%%I"

echo [OK] Using embedded Python: %ACTIVE_PY_EXE%
echo.
echo ==========================================
echo   SceneSmith VTT is starting...
echo ==========================================
echo.
echo   -- Localhost --
echo   Player       : http://localhost:%PORT%/
echo.
echo   -- Network (share with players) --
echo   Player       : http://%LOCAL_IP%:%PORT%/

echo.
echo   Close this window to stop the server.
echo ==========================================
echo.

REM Open DM page in browser after a short delay to let the server start
start /b cmd /c "timeout /t 2 >nul && start http://localhost:%PORT%/"

pushd "%APP_WORKDIR%" >nul
"%ACTIVE_PY_EXE%" "%APP_PATH%"
set "RUN_ERR=%ERRORLEVEL%"
popd >nul

pause
popd >nul 2>&1
exit /b %RUN_ERR%
