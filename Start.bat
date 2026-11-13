@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title ByteDrop v1.0.0 Launcher
color 0B
cd /d "%~dp0"

REM Section 3.5: Prevent __pycache__ creation in the application folder
set "PYTHONDONTWRITEBYTECODE=1"
if not exist "%APPDATA%\ByteDrop\pycache" mkdir "%APPDATA%\ByteDrop\pycache" >nul 2>&1
set "PYTHONPYCACHEPREFIX=%APPDATA%\ByteDrop\pycache"

echo ==================================================
echo    ByteDrop v1.0.0 - Local ^& Cloud File Transfer
echo ==================================================
echo.

REM Section 6 & H5: Check if ByteDrop is already running via %APPDATA%\ByteDrop\running.pid
set "PID_FILE=%APPDATA%\ByteDrop\running.pid"
if exist "%PID_FILE%" (
    set /p EXISTING_PID=<"%PID_FILE%"
    if defined EXISTING_PID (
        tasklist /FI "PID eq !EXISTING_PID!" 2>nul | find "!EXISTING_PID!" >nul
        if not errorlevel 1 (
            echo [INFO] ByteDrop is already running ^(PID !EXISTING_PID!^). Restoring window...
            echo show > "%APPDATA%\ByteDrop\show_window.signal" 2>nul
            attrib +h "%APPDATA%\ByteDrop\show_window.signal" >nul 2>&1
            if exist "%~dp0.venv\Scripts\pythonw.exe" (
                "%~dp0.venv\Scripts\pythonw.exe" -c "from bytedrop.desktop.single_instance import signal_existing_instance; signal_existing_instance()" >nul 2>&1
            ) else (
                powershell -NoProfile -Command "try { $ev = [System.Threading.EventWaitHandle]::OpenExisting('Global\ByteDropShowWindow'); $ev.Set() | Out-Null } catch {}; $w = (Get-Process -Id !EXISTING_PID! -ErrorAction SilentlyContinue).MainWindowHandle; if ($w) { Add-Type -MemberDefinition '[DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow); [DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr hWnd);' -Name Win32 -Namespace U; [U.Win32]::ShowWindow($w, 9) | Out-Null; [U.Win32]::SetForegroundWindow($w) | Out-Null }" >nul 2>&1
            )
            exit /b 0
        )
    )
)

REM 1. Detect real Python >= 3.10 (prefer py -3 launcher, reject WindowsApps Store stub)
set "SYS_PYTHON="
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "SYS_PYTHON=py -3"
) else (
    for /f "delims=" %%P in ('where python 2^>nul') do (
        echo "%%P" | find /I "WindowsApps" >nul
        if errorlevel 1 (
            if not defined SYS_PYTHON (
                "%%P" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
                if not errorlevel 1 set "SYS_PYTHON=%%P"
            )
        )
    )
)

if not defined SYS_PYTHON (
    echo [ERROR] Python 3.10 or newer was not found on this PC.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo and check "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)

REM 2. Check for Microsoft Edge WebView2 Runtime on Windows
set "WV2_FOUND=0"
reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" /v pv >nul 2>&1 && set "WV2_FOUND=1"
reg query "HKLM\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" /v pv >nul 2>&1 && set "WV2_FOUND=1"
reg query "HKCU\Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" /v pv >nul 2>&1 && set "WV2_FOUND=1"

if "%WV2_FOUND%"=="0" (
    echo [WARNING] Microsoft Edge WebView2 Runtime was not detected in the registry.
    echo ByteDrop requires WebView2 to render its desktop window.
    echo Download it from: https://go.microsoft.com/fwlink/p/?LinkId=2124703
    echo.
)

REM 3. Create / verify virtual environment and hide generated directories
set "VENV_DIR=%~dp0.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "VENV_PYW=%VENV_DIR%\Scripts\pythonw.exe"
set "STAMP_FILE=%VENV_DIR%\.deps_installed"

if not exist "%VENV_PY%" (
    echo [1/4] Creating isolated virtual environment...
    %SYS_PYTHON% -m venv ".venv"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)
attrib +h ".venv" >nul 2>&1

REM Hide any leftover __pycache__ or cache directories (Section 3.5)
for /d /r "%~dp0" %%D in (__pycache__ .pytest_cache .ruff_cache .mypy_cache) do (
    if exist "%%D" attrib +h "%%D" >nul 2>&1
)

REM 4. Install or update dependencies (H7: prefer requirements.lock.txt with --prefer-binary, fallback to requirements.txt)
set "REQ_FILE=requirements.txt"
if exist "%~dp0requirements.lock.txt" set "REQ_FILE=requirements.lock.txt"

set "NEED_INSTALL=0"
if not exist "%STAMP_FILE%" (
    set "NEED_INSTALL=1"
) else (
    fc /B "%REQ_FILE%" "%STAMP_FILE%" >nul 2>&1
    if errorlevel 1 set "NEED_INSTALL=1"
)

if "%NEED_INSTALL%"=="1" (
    echo [2/4] Installing required libraries from %REQ_FILE%...
    "%VENV_PY%" -m pip install --prefer-binary -r "%REQ_FILE%" --disable-pip-version-check -q
    if errorlevel 1 (
        if /I "%REQ_FILE%"=="requirements.lock.txt" (
            echo [WARN] Lockfile install encountered an issue on this Python version; retrying with requirements.txt...
            "%VENV_PY%" -m pip install --prefer-binary -r "requirements.txt" --disable-pip-version-check -q
        )
    )
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed. Check your internet connection.
        pause
        exit /b 1
    )
    copy /Y "%REQ_FILE%" "%STAMP_FILE%" >nul 2>&1
    attrib +h "%STAMP_FILE%" >nul 2>&1
) else (
    echo [2/4] Dependencies verified ^(cached^).
)

REM 5. One-time Windows Firewall private-network rule prompt (TCP 8000-8049)
if not exist "%APPDATA%\ByteDrop" mkdir "%APPDATA%\ByteDrop" >nul 2>&1
set "FW_MARKER=%APPDATA%\ByteDrop\.firewall_prompted"
if not exist "%FW_MARKER%" (
    echo [3/4] First-run setup: Allow ByteDrop through Windows Firewall ^(Private LAN TCP 8000-8049^)?
    set /p "ADD_FW=Add Private LAN firewall rule for ByteDrop? [Y/n]: "
    if /I not "!ADD_FW!"=="n" (
        powershell -NoProfile -Command "Start-Process netsh -ArgumentList 'advfirewall firewall add rule name=\"ByteDrop LAN\" dir=in action=allow protocol=TCP localport=8000-8049 profile=private enable=yes' -Verb RunAs -WindowStyle Hidden" >nul 2>&1
    )
    echo prompted > "%FW_MARKER%"
    attrib +h "%FW_MARKER%" >nul 2>&1
) else (
    echo [3/4] Firewall check complete.
)

REM 6. Launch via pythonw.exe; poll running.pid up to 25s (1s intervals), then close console cleanly (G5)
echo [4/4] Launching ByteDrop v1.0.0...
if exist "%VENV_PYW%" (
    start "" "%VENV_PYW%" main.py
    set "LAUNCH_OK=0"
    for /L %%I in (1,1,25) do (
        if "!LAUNCH_OK!"=="0" (
            if exist "%PID_FILE%" (
                set /p NEW_PID=<"%PID_FILE%"
                if defined NEW_PID (
                    tasklist /FI "PID eq !NEW_PID!" 2>nul | find "!NEW_PID!" >nul
                    if not errorlevel 1 set "LAUNCH_OK=1"
                )
            )
            if "!LAUNCH_OK!"=="0" timeout /t 1 /nobreak >nul
        )
    )
    if "!LAUNCH_OK!"=="1" (
        echo [OK] ByteDrop is running.
        endlocal
        exit /b 0
    )
    echo [WARN] Background launch did not register running.pid after 25s. Re-running in console mode for diagnostics...
    "%VENV_PY%" main.py
    if errorlevel 1 pause
) else (
    "%VENV_PY%" main.py
    if errorlevel 1 pause
)
endlocal
exit /b 0
