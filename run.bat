@echo off
echo ================================================
echo    SafeGuard AI - Claude Bilingual Chatbot
echo    Hindi + English Disaster Safety Advisor
echo ================================================
echo.
echo Step 1: Get FREE API key from https://console.anthropic.com
echo Step 2: Open this file (run.bat) in Notepad
echo Step 3: Replace YOUR_API_KEY_HERE with your key
echo Step 4: Save and double-click run.bat again
echo.
echo ================================================
echo  OR: Edit app.py line 296 directly:
echo  api_key = os.environ.get("ANTHROPIC_API_KEY", "sk-ant-YOURKEY")
echo ================================================
echo.

REM ---- PASTE YOUR API KEY BELOW (between the quotes) ----
set ANTHROPIC_API_KEY=YOUR_API_KEY_HERE

pip install flask -q
python app.py
pause
