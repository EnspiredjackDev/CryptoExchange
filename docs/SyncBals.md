# 🔄 Wallet Sync Script – `sync_balances.py`

This script scans deposit addresses and updates user balances based on on-chain transactions. It's intended to run continuously in the background (via cron or another scheduler).

---

## ⚙️ What It Does

- Syncs all known deposit addresses across all supported coins.
- Detects confirmed incoming transactions from both:
  - **Bitcoin-style** RPC nodes (e.g. BTC, LTC)
  - **Monero** wallet RPC (via subaddresses)
- Adds confirmed transactions to the `transactions` table.
- Updates user balances accordingly.
- Maintains a **`sync_state`** marker to avoid duplicate scanning.

> ⚠️ Only transactions with **at least 2 confirmations** are processed.

---

## 🧪 Running the Script Manually

You can run the sync manually:

```bash
python3 sync_balances.py
````

Output will log received transactions like:

```
[DOGE] Syncing 3 addresses...
➕ DOGE | DEPOSIT_ADDR | 52.34 | TXID...
```

---

## 🕒 Automating with Cron

To keep balances in sync regularly, you can schedule it using `cron`.

Use the provided `setupCronForSyncBals.sh`:

```bash
chmod +x setupCronForSyncBals.sh
./setupCronForSyncBals.sh
```

This will install a cron job that runs the script every **2 minutes**, logging output to `cron.log` in your project directory.

### 🔁 What It Adds to Your Crontab:

```
*/2 * * * * cd /your/project/path && /usr/bin/python3 /your/project/path/sync_balances.py >> /your/project/path/cron.log 2>&1
```

> 💡 You can view your current crontab with:
>
> ```bash
> crontab -l
> ```

---

### ⏱ Changing the Frequency

The default interval is every **2 minutes**, controlled by this part of the cron expression:

```
*/2 * * * *
```

To change how often the script runs, simply adjust this value in the `setupCronForSyncBals.sh` script. For example:

* Every minute: `* * * * *`
* Every 5 minutes: `*/5 * * * *`
* Every hour: `0 * * * *`

You can learn more about cron syntax here: [crontab.guru](https://crontab.guru)

---

## 📁 Log Output

All output is appended to `cron.log`. You can check it with:

```bash
tail -f cron.log
```

Or clear it periodically:

```bash
> cron.log
```

---

## 🔐 Notes

* Make sure the `syncBals.py` script has access to environment variables (via `.env`).
* Your coin RPC nodes must be online and responding.
* Ensure proper DB access and permissions.

