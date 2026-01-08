#!/usr/bin/env bash
# Baseline: Standard Python Execution
echo "🐍 Starting standard Python server (Baseline)..."
START=$(date +%s%3N)

# Using standard python to run the flask app
# We use -u for unbuffered output
python3 app.py &
PID=$!

# Wait until the port is open (Timeout after 10s)
COUNT=0
while ! nc -z localhost 8000; do   
  sleep 0.1
  COUNT=$((COUNT+1))
  if [ $COUNT -gt 100 ]; then
    echo "❌ Timeout waiting for server"
    kill $PID
    exit 1
  fi
done

END=$(date +%s%3N)
RSS=$(ps -o rss= -p $PID)
echo "⏱ Total Startup Time (Cold): $((END-START))ms"
echo "💎 Memory Usage (RSS): $((RSS/1024))MB"
echo "🚀 Server ready at http://localhost:8000"
echo "Press Ctrl+C to stop."
wait $PID
