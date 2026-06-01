@echo off
setlocal enabledelayedexpansion

echo [1/3] Checking for local changes...

git status -uno --porcelain > temp_status.txt
set /p STATUS=<temp_status.txt
del temp_status.txt

if not "%STATUS%"=="" (
    echo.
    echo ====================================================
    echo ! WARNING: You have made changes to the code !
    echo Updating will PERMANENTLY ERASE your local changes.
    echo ====================================================
    echo.
    set /p CONFIRM="Do you want to proceed and overwrite your changes? (Y/N): "

    if /I not "!CONFIRM!"=="Y" (
        echo Update canceled. Your changes were saved.
        pause
        exit /b
    )
)

echo.
echo [2/3] Fetching latest code from GitHub...
git fetch --all
git reset --hard origin/main

echo.
echo Done! Project is up to date and ready.
pause
