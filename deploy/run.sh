#!/usr/bin/env bash
# One bot run: check prices, send Telegram alerts, rebuild the dashboard.
# Called by cron every 30 min. flock prevents overlapping runs.
set -u
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"
mkdir -p logs site
exec 9>"$DIR/.run.lock"
flock -n 9 || { echo "$(date) previous run still going, skipping" >> logs/run.log; exit 0; }
{
  echo "===== $(date '+%F %T') ====="
  .venv/bin/python src/main.py "$@"
  .venv/bin/python src/dashboard.py
} >> logs/run.log 2>&1
# keep the log from growing forever (~last 5000 lines)
tail -n 5000 logs/run.log > logs/run.log.tmp && mv logs/run.log.tmp logs/run.log
