@echo off
cd /d "D:\football_analyzer"
set PYTHONPATH=D:\
chcp 65001 >nul
title Football Analyzer Quant Pro v10.0

echo ============================================
echo  Football Analyzer Quant Pro v10.0
echo ============================================
echo.

:: Verificar Python
py --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no encontrado. Instala Python 3.10+ desde https://python.org
    pause
    exit /b 1
)

:: Borrar venv si el Python interno no funciona
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe --version >nul 2>&1
    if errorlevel 1 (
        echo [!] Venv roto detectado. Eliminando...
        rmdir /s /q venv
    )
)

:: Crear entorno virtual si no existe
if not exist "venv\" (
    echo [1/3] Creando entorno virtual...
    py -m venv venv
)

:: Activar entorno virtual
call venv\Scripts\activate.bat

:: Instalar dependencias
echo [2/3] Instalando dependencias...
pip install -r requirements.txt --quiet

:: Lanzar la app
echo [3/3] Iniciando Football Analyzer...
echo.
python main.py

if errorlevel 1 (
    echo.
    echo [ERROR] La aplicacion ha fallado. Revisa el log arriba.
    pause
)

deactivate
