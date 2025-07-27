# ⚙️ Adding a New Coin Node to the Exchange

Integrating a new coin into the exchange is fast and simple. All you need to do is add the node connection details to your `.env` file — no code changes are required.

---

## 🧾 Example `.env` Entry

Here’s a general format for configuring coin RPC nodes:

```env
<COIN>_NODE_HOST=127.0.0.1
<COIN>_NODE_PORT=12345
<COIN>_NODE_USER=rpcuser
<COIN>_NODE_PASS=rpcpass
<COIN>_NODE_TYPE=btc  # optional (defaults to 'btc'), use 'monero' for Monero nodes
````

Replace `<COIN>` with the uppercase ticker symbol (e.g. `BTC`, `DOGE`, `XMR`).

---

## 💡 Supported Node Types

* `btc`: For Bitcoin-style JSON-RPC nodes (e.g. BTC, DOGE, LTC, RVN, DGB)
* `monero`: For Monero’s `wallet-rpc`

If `*_NODE_TYPE` is omitted, it defaults to `btc`.

---

## ✅ Example

```env
DOGE_NODE_HOST=192.168.1.50
DOGE_NODE_PORT=22555
DOGE_NODE_USER=myuser
DOGE_NODE_PASS=mypassword

XMR_NODE_HOST=192.168.1.51
XMR_NODE_PORT=18082
XMR_NODE_USER=myuser
XMR_NODE_PASS=mypassword
XMR_NODE_TYPE=monero
```

---

## 🔁 Restart Required

After updating the `.env` file:

1. Restart the backend (or reload environment variables)
2. The new node will be recognised immediately via `get_node(coin)` in the code

> 🔍 You can test address generation by hitting the `/generate_address` endpoint.

---

## 🧪 Tip: Check Connection

You can verify if a node is working by pinging it manually or testing the RPC credentials with a curl command or Postman before integrating it into the exchange.

---

## 🔐 Reminder

* Do **not** share sensitive `.env` details publicly.
* Use strong RPC passwords, especially on externally exposed nodes.
* Always restrict RPC access by IP wherever possible.

---
