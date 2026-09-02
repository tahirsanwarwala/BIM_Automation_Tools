@echo off
REM ============================================================
REM  Point Cloud MEP Engine — Environment Setup
REM  Creates a Python venv and installs processing dependencies.
REM  Run this once before using the Point Cloud MEP tools.
REM ============================================================

echo ============================================================
echo  Point Cloud MEP Engine — Environment Setup
echo ============================================================
echo.

REM Use the same Python base as the existing Tahir venv
set PYTHON_EXE=C:\Users\TahirSanwarwala\AppData\Local\Python\pythoncore-3.11-64\python.exe

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python 3.11 not found at: %PYTHON_EXE%
    echo Please update PYTHON_EXE path in this script.
    pause
    exit /b 1
)

echo [1/3] Creating virtual environment...
"%PYTHON_EXE%" -m venv "%~dp0.venv"
if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

echo [2/3] Upgrading pip...
"%~dp0.venv\Scripts\python.exe" -m pip install --upgrade pip

echo [3/3] Installing dependencies...
"%~dp0.venv\Scripts\pip.exe" install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Setup complete! Engine environment is ready.
echo  Python: %~dp0.venv\Scripts\python.exe
echo ============================================================
pause
