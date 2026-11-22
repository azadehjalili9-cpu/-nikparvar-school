@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
  echo نصب پیش نیازها ناموفق بود.
  pause
  exit /b 1
)
pyinstaller --clean --noconfirm --onedir --name NikParvarSmartSchool app.py
echo.
echo EXE در پوشه dist\NikParvarSmartSchool ساخته شد.
echo برای اجرای برنامه، فایل NikParvarSmartSchool.exe را اجرا کنید.
pause
