#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "[SemXMLDiff] Creating virtual environment..."
  python3 -m venv .venv
  echo "[SemXMLDiff] Installing dependencies..."
  .venv/bin/pip install -r requirements.txt
fi

echo "[SemXMLDiff] Starting at http://127.0.0.1:8765"
exec .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
