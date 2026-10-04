@echo off
REM InEra All-in-One Plugins - start on Windows
cd /d "%~dp0"
if not exist "%USERPROFILE%\.inera-venv" (
  echo Creating virtual environment...
  py -3 -m venv "%USERPROFILE%\.inera-venv" || python -m venv "%USERPROFILE%\.inera-venv"
)
call "%USERPROFILE%\.inera-venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
if not exist .env copy .env.example .env >nul
echo Starting InEra on http://localhost:8000
python main.py
pause
