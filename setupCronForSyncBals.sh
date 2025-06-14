#!/bin/bash

CRON_LINE="*/2 * * * * cd $(pwd) && /usr/bin/python3 $(pwd)/sync_balances.py >> $(pwd)/cron.log 2>&1"

# Add only if it doesn't already exist
(crontab -l 2>/dev/null | grep -v 'sync_balances.py'; echo "$CRON_LINE") | crontab -

echo "✅ Cron job installed. Running sync_balances.py every 2 minutes."
