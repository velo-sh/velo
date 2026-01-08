#!/usr/bin/env bash
# Docker Python Execution with Cold-Start and RSS Measurement
set -e
cd "$(dirname "$0")/.."

echo "🐳 Docker Python Server"
echo "----------------------------"

# Build Docker image
docker build -t velo-demo-python -f - . <<EOF
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "app.py"]
EOF

START=$(python3 -c "import time; print(int(time.time() * 1000))")

CID=$(docker run -d -p 8000:8000 velo-demo-python)

# Wait for server to be ready (max 10s)
for i in {1..100}; do
    if nc -z localhost 8000 2>/dev/null; then
        break
    fi
    sleep 0.1
done

END=$(python3 -c "import time; print(int(time.time() * 1000))")
COLD_START=$((END - START))

# Get memory usage from Docker stats
MEM=$(docker stats --no-stream $CID --format "{{.MemUsage}}" | cut -d'/' -f1)

echo "⏱  Cold-start time: ${COLD_START} ms"
echo "📊 Memory usage:    ${MEM}"

# Cleanup
docker kill $CID >/dev/null 2>&1 || true
docker rm $CID >/dev/null 2>&1 || true
