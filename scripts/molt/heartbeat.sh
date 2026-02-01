#!/bin/bash
# Moltbook Ambassador Heartbeat
# Runs both the posting engine and the monitoring engine

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR/../.."

cd "$PROJECT_ROOT"

echo "=== [$(date)] Starting Moltbook Heartbeat ==="

# 1. Run Monitor (every heartbeat)
echo "Running Monitor..."
export PYTHONPATH=$PYTHONPATH:$SCRIPT_DIR
uv run python "$SCRIPT_DIR/monitor.py"

echo "=== Heartbeat Complete ==="
