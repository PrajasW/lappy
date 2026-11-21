#!/usr/bin/env bash
# One-time setup on the server: venv, dependencies, .env, cron jobs.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"
chmod +x deploy/*.sh
if [ ! -x .venv/bin/pip ]; then
  python3 -m venv --without-pip .venv
  curl -sSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
  .venv/bin/python /tmp/get-pip.py -q
fi
.venv/bin/pip install -q -r requirements.txt
if [ ! -f .env ]; then
  printf 'TELEGRAM_BOT_TOKEN=\nTELEGRAM_CHAT_ID=\n' > .env
fi
chmod 600 .env
# cron: run every 30 min, keep the dashboard server alive, start it on boot
( { crontab -l 2>/dev/null | grep -v 'lappy/deploy/' || true; } ;
  echo "*/30 * * * * $DIR/deploy/run.sh"
  echo "*/5 * * * * $DIR/deploy/serve.sh >/dev/null 2>&1"
  echo "@reboot sleep 30 && $DIR/deploy/serve.sh >/dev/null 2>&1" ) | crontab -
"$DIR/deploy/serve.sh"
echo "Installed. Cron:"; crontab -l | grep lappy
