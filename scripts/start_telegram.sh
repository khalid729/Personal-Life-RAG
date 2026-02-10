#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Error: venv not found. Run: python3 -m venv venv && pip install -r requirements.txt"
    exit 1
fi

echo "Starting Telegram bot..."
exec python -m app.integrations.telegram_bot
