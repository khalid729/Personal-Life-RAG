#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Activate venv
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Error: venv not found. Run: python3 -m venv venv && pip install -r requirements.txt"
    exit 1
fi

# Check Docker containers
echo "Checking Docker containers..."
for container in falkordb-personal qdrant-personal redis-personal; do
    if docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null | grep -q true; then
        echo "  ✓ $container is running"
    else
        echo "  ✗ $container is NOT running. Starting docker compose..."
        docker compose up -d
        echo "  Waiting 10s for containers to start..."
        sleep 10
        break
    fi
done

# Run FalkorDB setup
echo "Setting up FalkorDB schema..."
python scripts/setup_graph.py

# Start API
echo "Starting Personal Life RAG API on port 8500..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8500 --log-level info
