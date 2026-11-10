#!/usr/bin/env bash
# Plain-English health check for the always-on server.
DIR="${SMS_DIR:-$HOME/smart-money-alerts}"
for s in sms-stream sms-watch; do
  if systemctl is-active --quiet "$s"; then echo "OK      $s is running"; else echo "PROBLEM $s is NOT running"; fi
done
if systemctl is-active --quiet sms-publish.timer; then echo "OK      website updates are scheduled"; else echo "PROBLEM website updates are NOT scheduled"; fi
echo
echo "Last stream messages:"
journalctl -u sms-stream -n 5 --no-pager -o cat 2>/dev/null | sed 's/api-key=[^& ]*/api-key=***/g'
echo
echo "Last website update:"
journalctl -u sms-publish -n 2 --no-pager -o cat 2>/dev/null
