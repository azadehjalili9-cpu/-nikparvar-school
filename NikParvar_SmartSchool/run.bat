@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>&1
if not errorlevel 1 goto use_py
where python >nul 2>&1
if not errorlevel 1 goto use_python

echo Python is not installed or is not added to PATH.
echo Install Python 3.11 or 3.12 and enable "Add Python to PATH".
pause
exit /b 1

:use_py
set "PYTHON_CMD=py -3"
goto install

:use_python
set "PYTHON_CMD=python"

:install
%PYTHON_CMD% --version
if errorlevel 1 goto failed
%PYTHON_CMD% -m pip install -r "%~dp0requirements-windows.txt"
if errorlevel 1 goto failed
start "" "http://127.0.0.1:5000"
%PYTHON_CMD% "%~dp0app.py"
echo.
echo The application has stopped. Read any error message above.
pause
exit /b 0

:failed
echo.
echo Setup failed. Check your Python installation and internet connection.
pause
exit /b 1
