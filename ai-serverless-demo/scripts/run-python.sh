#!/usr/bin/env bash
# Baseline Python Execution with Cold-Start and RSS Measurement
set -e
cd "$(dirname "$0")/.."

echo "🐍 Python Server (Baseline)"
echo "----------------------------"

# Kill any existing process on port 8000
lsof -ti:8000 | xargs kill -9 2>/dev/null || true

START=$(python3 -c "import time; print(int(time.time() * 1000))")

python3 app.py &
PID=$!

# Wait for server to be ready (max 10s)
for i in {1..100}; do
    if nc -z localhost 8000 2>/dev/null; then
        break
    fi
    sleep 0.1
done

END=$(python3 -c "import time; print(int(time.time() * 1000))")
COLD_START=$((END - START))

# Get RSS in KB
RSS_KB=$(ps -o rss= -p $PID 2>/dev/null || echo "0")
RSS_MB=$((RSS_KB / 1024))

echo "⏱  Cold-start time: ${COLD_START} ms"
echo "📊 RSS memory:      ${RSS_MB} MB"

# Cleanup
kill $PID 2>/dev/null || true
