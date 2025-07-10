@echo off
setlocal enabledelayedexpansion

REM === CONFIGURATION ===
set "PROJECT_ROOT=%~dp0.."
set "FREECAD_DIR=%PROJECT_ROOT%\freecad"
set "FREECAD_ARCHIVE=%FREECAD_DIR%\FreeCAD.7z"
set "FREECAD_TEMP_DIR=%FREECAD_DIR%\FreeCAD"
set "FREECAD_EXE=%FREECAD_DIR%\bin\FreeCAD.exe"
set "FREECAD_URL=https://github.com/FreeCAD/FreeCAD/releases/download/1.0.1/FreeCAD_1.0.1-conda-Windows-x86_64-py311.7z"
set "SEVEN_ZIP_PATH=C:\Program Files\7-Zip\7z.exe"

set "A2PLUS_DIR=%PROJECT_ROOT%\a2plus"
set "A2PLUS_ZIP=%A2PLUS_DIR%\a2plus.zip"
set "A2PLUS_URL=https://github.com/kbwbe/A2plus/archive/v0.4.26.zip"
set "A2PLUS_EXTRACTED=%A2PLUS_DIR%\A2plus-0.4.26"

set "WORKBENCH_NAME=SatelliteWorkbench"
set "WORKBENCH_SRC=%PROJECT_ROOT%\workbench"
set "MOD_DEST=%FREECAD_DIR%\Mod\%WORKBENCH_NAME%"
set "REQUIREMENTS=%PROJECT_ROOT%\requirements.txt"

REM === CHECK EXISTING FREECAD SETUP ===
if exist "%FREECAD_EXE%" (
    echo [✔] FreeCAD already extracted. Skipping setup.
) else (
    echo [➤] Setting up FreeCAD...

    if not exist "%FREECAD_ARCHIVE%" (
        echo [⬇] Downloading FreeCAD...
        curl -L -o "%FREECAD_ARCHIVE%" "%FREECAD_URL%" || (
            echo [✘] Failed to download FreeCAD.
            exit /b
        )
    ) else (
        echo [✔] FreeCAD.7z already exists.
    )

    REM === CLEAN TEMP DIR IF EXISTS ===
    if exist "%FREECAD_TEMP_DIR%" (
        echo [🧹] Removing old temp FreeCAD folder...
        rmdir /S /Q "%FREECAD_TEMP_DIR%"
    )

    REM === Extract to TEMP directory ===
    echo [📦] Extracting FreeCAD to temp dir...
    "%SEVEN_ZIP_PATH%" x "%FREECAD_ARCHIVE%" -o"%FREECAD_TEMP_DIR%" -aoa >nul || (
        echo [✘] Extraction failed.
        exit /b
    )

    REM === Find the inner extracted FreeCAD folder ===
    for /d %%D in ("%FREECAD_TEMP_DIR%\*") do (
        set "INNER_EXTRACTED=%%D"
        goto :move_files
    )

    :move_files
    echo [📁] Moving extracted contents from !INNER_EXTRACTED! to %FREECAD_DIR%...
    xcopy /E /Y "!INNER_EXTRACTED!\*" "%FREECAD_DIR%\" >nul

    echo [🧽] Cleaning up temp folders...
    rmdir /S /Q "%FREECAD_TEMP_DIR%"
)

REM === COPY WORKBENCH INTO Mod FOLDER ===
if exist "%MOD_DEST%\InitGui.py" (
    echo [✔] Workbench already installed. Skipping copy.
) else (
    echo [📁] Installing SatelliteWorkbench into FreeCAD/Mod...
    mkdir "%MOD_DEST%" >nul 2>&1
    xcopy /E /Y "%WORKBENCH_SRC%\*" "%MOD_DEST%" >nul
)

REM === SETUP A2PLUS ===
if exist "%A2PLUS_EXTRACTED%" (
    echo [✔] A2plus already extracted. Skipping.
) else (
    if not exist "%A2PLUS_ZIP%" (
        echo [⬇] Downloading A2plus...
        curl -L -o "%A2PLUS_ZIP%" "%A2PLUS_URL%" || (
            echo [✘] Failed to download A2plus.
            exit /b
        )
    ) else (
        echo [✔] A2plus.zip already exists.
    )

    echo [📦] Extracting A2plus...
    "%SEVEN_ZIP_PATH%" x "%A2PLUS_ZIP%" -o"%A2PLUS_DIR%" -aoa >nul || (
        echo [✘] Failed to extract A2plus.
        exit /b
    )
)

REM === INSTALL PYTHON DEPENDENCIES ===
echo [🐍] Installing Python dependencies...
"%FREECAD_DIR%\bin\python.exe" -m pip install -r "%REQUIREMENTS%" >nul || (
    echo [✘] Failed to install Python dependencies.
    exit /b
)

REM === LAUNCH FREECAD ===
echo [🚀] Launching FreeCAD...
start "" "%FREECAD_EXE%"

endlocal
