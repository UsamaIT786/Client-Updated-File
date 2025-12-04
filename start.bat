@echo off
REM This script starts the Satta AI Bot application on Windows.

SET VENV_DIR=myenv
SET PYTHON_EXECUTABLE=%VENV_DIR%\Scripts\python.exe
SET PROJECT_ROOT=%~dp0

echo Starting Satta AI Bot...

REM Check if virtual environment exists
if not exist "%VENV_DIR%" (
    echo Virtual environment not found. Creating one...
    python -m venv %VENV_DIR%
    if %errorlevel% neq 0 (
        echo Failed to create virtual environment. Ensure Python is installed and in PATH.
        pause
        exit /b 1
    )
)

REM Activate virtual environment
call "%VENV_DIR%\Scripts\activate.bat"
if %errorlevel% neq 0 (
    echo Failed to activate virtual environment.
    pause
    exit /b 1
)

REM Install dependencies
echo Installing Python dependencies...
pip install --upgrade pip
if %errorlevel% neq 0 (
    echo Failed to upgrade pip.
    pause
    exit /b 1
)
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)

REM Run the main application
echo Running main.py...
"%PYTHON_EXECUTABLE%" "%PROJECT_ROOT%main.py"

REM Deactivate virtual environment (this line might not be reached if main.py runs indefinitely)
REM deactivate

echo Application stopped.
pause
