@echo off
setlocal
title Build UDM.exe
cd /d "%~dp0"

echo ============================================================
echo  UDM - Ultimate Download Manager : build UDM.exe
echo ============================================================
echo.

rem --- Check the logo icon is present (it becomes the .exe icon) ---
if exist "udm.ico" (
    echo [OK] Logo icon found: udm.ico
) else (
    echo [!!] udm.ico not found. A plain fallback icon will be generated.
    echo      Place your logo icon at: %~dp0udm.ico
)
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_exe.ps1"
if errorlevel 1 (
    echo.
    echo ============================================================
    echo  BUILD FAILED - read the messages above.
    echo ============================================================
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  BUILD OK:  %~dp0dist\UDM.exe
echo.
echo  If Explorer still shows the OLD icon, Windows is using its
echo  icon cache. Rename or move UDM.exe, or run:
echo      ie4uinit.exe -show
echo  (or restart Explorer) and it will refresh.
echo ============================================================
echo.
pause
endlocal
