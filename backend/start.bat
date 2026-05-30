@echo off
cd /d "%~dp0"
title ForgeStore

echo ========================================
echo    🔥 ForgeStore — Starting Server
echo ========================================
echo.

:: Create necessary directories
if not exist "app\static\uploads\products" mkdir "app\static\uploads\products"
if not exist "logs" mkdir "logs"

:: Install dependencies if needed
pip install -r requirements.txt --quiet 2>nul

:: Run pending database migrations
echo 🔄 Running pending migrations...
python -m migrations.run_migration 2>nul
if %errorlevel% neq 0 (
    echo ✓ No migrations to apply.
)

:: Run database seed if DB doesn't exist
if not exist "forgestore.db" (
    echo 📦 Running database seed...
    python seed.py
    echo.
)

:: Start server
echo 🚀 Server starting at http://127.0.0.1:8000
echo.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

pause
