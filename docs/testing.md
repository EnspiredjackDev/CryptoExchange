# 🧪 Testing the Exchange Backend (`tests.py`)

This script runs a full suite of integration tests on the exchange backend to verify:

- Market creation
- Order placement and matching
- Fee handling
- Balance updates
- Partial fills and cancellations
- Concurrency safety (e.g. avoiding double-fills)

---

## ⚠️ WARNING: DESTRUCTIVE TESTING

> **This test suite wipes all data in the database.**  
> It uses `resetTables.py` internally to drop and recreate the schema and tables.

**DO NOT run this in production.**

---

## 🛠 What It Covers

The `tests.py` script performs the following:

- Creates test users
- Spawns a sample market (`DGB/DOGE`)
- Assigns test balances
- Places buy/sell orders
- Asserts correct balances and fee calculations
- Tests edge cases like:
  - Partial fills
  - Order cancellations
  - Matching against multiple sell orders
  - Price improvement scenarios
  - Concurrency safety (two buyers vs one sell order)

---

## ▶️ How to Run

Make sure your backend is running locally:

```bash
python3 app.py
````

Then in a new terminal, run:

```bash
python3 tests.py
```

You should see output like:

```
🚀 Starting DGB/DOGE market test...
✅ Market created...
📊 Buyer DGB balance: ...
✅✅✅ Trade test passed.
...
🎉 All tests passed successfully!
```

---

## ✏️ Customising

If you'd like to change the fee rate, test coins, or amounts, edit the top of the `tests.py` file:

```python
FEE_RATE = Decimal("0.001")  # 0.1%
BASE_URL = "http://localhost:5000"
```

---

## 🧼 Resetting State

If a test fails midway and you want to reset cleanly, you can manually run:

```bash
python3 resetTables.py
```

---

## 📦 Summary

* ✅ Fully automated end-to-end testing
* 🚫 **Not safe for production**
* 🧪 Ideal for CI pipelines, dev testing, and regression checks

---
