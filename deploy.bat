@echo off
setlocal ENABLEEXTENSIONS ENABLEDELAYEDEXPANSION

REM VectorWeaver offline production deployment script for Windows.
REM This script does not download anything and does not require internet access.
REM If PyInstaller is already installed locally, it will build a native .exe.
REM Otherwise it creates a production folder runnable with an installed Python 3.

set APP_NAME=VectorWeaver
set ROOT=%~dp0
set SRC=%ROOT%src\vectorweaver.py
set DIST=%ROOT%dist
set PROD=%DIST%\%APP_NAME%-production
set BUILD=%ROOT%build

echo.
echo =============================================
echo   %APP_NAME% Offline Production Deployment
echo =============================================
echo.

if not exist "%SRC%" (
    echo ERROR: Source file not found: %SRC%
    exit /b 1
)

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set PY=py -3
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        set PY=python
    ) else (
        echo ERROR: Python 3 was not found.
        echo Install Python 3 from your organization-approved offline installer, then rerun deploy.bat.
        exit /b 1
    )
)

echo Using Python command: %PY%
%PY% --version
if %ERRORLEVEL% NEQ 0 exit /b 1

echo.
echo Cleaning previous production output...
if exist "%PROD%" rmdir /s /q "%PROD%"
mkdir "%PROD%" || exit /b 1
mkdir "%PROD%\src" || exit /b 1

echo Copying source files...
copy "%SRC%" "%PROD%\src\vectorweaver.py" >nul || exit /b 1

echo Creating runnable launchers...
(
    echo @echo off
    echo cd /d "%%~dp0"
    echo py -3 src\vectorweaver.py
    echo if %%ERRORLEVEL%% NEQ 0 python src\vectorweaver.py
) > "%PROD%\VectorWeaver.bat"

(
    echo Set WshShell = CreateObject("WScript.Shell"^
    echo WshShell.Run chr(34^) ^& CreateObject("Scripting.FileSystemObject"^).GetParentFolderName(WScript.ScriptFullName^) ^& "\VectorWeaver.bat" ^& chr(34^), 0
    echo Set WshShell = Nothing
) > "%PROD%\VectorWeaver.vbs"

(
    echo VectorWeaver production package
    echo.
    echo Run VectorWeaver.bat to start the app with installed Python 3.
    echo If VectorWeaver.exe exists in this folder, you can run that instead.
    echo No internet access is required.
) > "%PROD%\README.txt"

echo.
echo Checking syntax...
%PY% -m py_compile "%PROD%\src\vectorweaver.py"
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python source failed syntax check.
    exit /b 1
)

echo.
echo Checking whether PyInstaller is available locally...
%PY% -m PyInstaller --version >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo PyInstaller found. Building native Windows executable...
    if exist "%BUILD%" rmdir /s /q "%BUILD%"
    %PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name %APP_NAME% --distpath "%PROD%" --workpath "%BUILD%" --specpath "%BUILD%" "%SRC%"
    if %ERRORLEVEL% NEQ 0 (
        echo WARNING: PyInstaller build failed. Production Python launcher was still created.
    ) else (
        echo Native executable created: %PROD%\%APP_NAME%.exe
    )
) else (
    echo PyInstaller is not installed locally. Skipping .exe build.
    echo To build an exe completely offline, install PyInstaller from an offline wheelhouse, then rerun this script.
)

echo.
echo Production package is ready:
echo %PROD%
echo.
echo Launch options:
echo   1. %PROD%\VectorWeaver.bat
echo   2. %PROD%\VectorWeaver.exe   ^(if PyInstaller was available^)
echo.
pause
endlocal
