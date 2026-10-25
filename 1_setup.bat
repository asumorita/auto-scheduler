@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt || goto :error
python -m playwright install chromium || goto :error
if not exist .env copy .env.example .env > nul
echo.
echo Setup finished. Write your Keepa API key in the notepad window and save it.
notepad .env
pause
exit /b 0
:error
echo.
echo Setup failed. Check that Python is installed and "python" works in the command prompt.
pause
exit /b 1
