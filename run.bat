@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [SemXMLDiff] Creating virtual environment...
    python -m venv .venv || goto :error
    echo [SemXMLDiff] Installing dependencies...
    ".venv\Scripts\pip.exe" install -r requirements.txt || goto :error
)

echo [SemXMLDiff] Starting at http://127.0.0.1:8765
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
goto :eof

:error
echo Setup failed. Make sure Python 3.11+ is installed and available as "python".
exit /b 1
