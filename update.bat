@echo off
echo Fetching latest code from GitHub...
git fetch --all
git reset --hard origin/main

echo Done! Project is up to date and ready.
pause
