@echo off
setlocal
cd /d "%~dp0backend"
echo.
echo ============================================
echo   KARIGAR LINK V13 - ARTISAN BUSINESS OS
echo ============================================
echo.
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Dependency installation failed. Check that Python is installed.
  pause
  exit /b 1
)
echo.
echo Starting Karigar Link on http://127.0.0.1:8765
start "Karigar Link" cmd /k "cd /d \"%~dp0backend\" && python -m uvicorn app.main:app --reload --port 8765"
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:8765/
start "" http://127.0.0.1:8765/app/store.html
endlocal
