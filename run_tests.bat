@echo off
cd /d "D:\football_analyzer"
chcp 65001 >nul
title AlphaBet - Tests

echo ============================================
echo  AlphaBet v15.0 - Suite de tests
echo ============================================
echo.

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] No existe el entorno virtual. Ejecuta run.bat primero.
    pause
    exit /b 1
)

venv\Scripts\python.exe -m pytest

if errorlevel 1 (
    echo.
    echo [X] HAY TESTS EN ROJO - revisa la salida de arriba.
    pause
    exit /b 1
) else (
    echo.
    echo [OK] Todos los tests en verde.
    pause
)
