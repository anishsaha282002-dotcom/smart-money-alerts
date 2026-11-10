#!/usr/bin/env bash
# One-time setup of Smart Money Stories on an always-on Ubuntu server (e.g. Oracle Cloud Always Free).
# Run as the normal login user (e.g. "ubuntu"), not root:
#   curl -fsSL https://raw.githubusercontent.com/anishsaha282002-dotcom/smart-money-alerts/smart-money-stories/deploy/install.sh | bash
# Safe to run again: it updates the code and restarts the services.
set -euo pipefail

REPO="${SMS_REPO:-https://github.com/anishsaha282002-dotcom/smart-money-alerts.git}"
BRANCH="${SMS_BRANCH:-smart-money-stories}"
DIR="${SMS_DIR:-$HOME/smart-money-alerts}"

echo "==> Installing system packages (needs your password once)"
sudo apt-get update -qq
sudo apt-get install -y -qq git python3 python3-venv python3-pip

echo "==> Getting the code into $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch -q origin "$BRANCH"
  git -C "$DIR" checkout -q "$BRANCH"
  git -C "$DIR" pull -q --rebase origin "$BRANCH"
else
  git clone -q -b "$BRANCH" "$REPO" "$DIR"
fi
cd "$DIR"

echo "==> Python environment"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[stream]"

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo
  echo "==> .env created. Fill in your keys now:"
  echo "      nano $DIR/.env"
  echo "    You need at least HELIUS_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID and GITHUB_TOKEN."
  echo "    Then run this script again."
  exit 0
fi

echo "==> Installing the three services"
for unit in sms-stream.service sms-watch.service sms-publish.service sms-publish.timer; do
  sed -e "s#__DIR__#$DIR#g" -e "s#__USER__#$USER#g" "deploy/$unit" | sudo tee "/etc/systemd/system/$unit" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now sms-stream.service sms-watch.service sms-publish.timer
sudo systemctl restart sms-stream.service sms-watch.service

echo
echo "==> Done. Check it with:"
echo "      bash $DIR/deploy/status.sh"
