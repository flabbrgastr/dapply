#!/bin/bash
# Daily Dapply update script
# Scrapes fresh pages from each site and ensures the web UI is running
set -e

cd /home/woodmastr/code/fg/dapply || { echo "dapply repo not found"; exit 1; }
export PATH="$HOME/.local/bin:$PATH"

LOG="/tmp/dapply-daily.log"
echo "===== Dapply daily update: $(date) =====" | tee -a "$LOG"

# 1. Scrape 3 fresh pages per site with auto-stop on empty pages
uv run python orchestator.py >> "$LOG" 2>&1
echo "Scrape done." | tee -a "$LOG"

# 2. Ensure web UI is running on port 8009
if ! lsof -i:8009 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Web UI not running — restarting..." | tee -a "$LOG"
    nohup uv run python db_viewer.py > /tmp/db_viewer.log 2>&1 &
    sleep 2
    if lsof -i:8009 -sTCP:LISTEN >/dev/null 2>&1; then
        echo "Web UI started on port 8009." | tee -a "$LOG"
    else
        echo "WARNING: Web UI failed to start!" | tee -a "$LOG"
    fi
else
    echo "Web UI already running on port 8009." | tee -a "$LOG"
fi

echo "===== Done: $(date) =====" | tee -a "$LOG"
