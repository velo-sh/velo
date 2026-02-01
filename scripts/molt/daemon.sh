#!/bin/bash
# Moltbook Ambassador Daemon
# Keeps the Velo_Agent_v01 active 24/7

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
HEARTBEAT_SCRIPT="$SCRIPT_DIR/heartbeat.sh"
LOG_FILE="$SCRIPT_DIR/daemon.log"

# Interval between heartbeats (15 minutes = 900 seconds)
INTERVAL=900

echo "Velo Ambassador Daemon started. PID: $$"
echo "Logging to $LOG_FILE"

while true; do
  echo "[$(date)] Triggering heartbeat..." >> "$LOG_FILE"
  bash "$HEARTBEAT_SCRIPT" >> "$LOG_FILE" 2>&1
  echo "[$(date)] Heartbeat finished. Sleeping for ${INTERVAL}s..." >> "$LOG_FILE"
  sleep $INTERVAL
done
