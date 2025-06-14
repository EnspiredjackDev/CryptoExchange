from db import SessionLocal
from helpers import get_or_create_balance
from models import Address, Transaction, Balance, SyncState
from coinNodes import get_node
from decimal import Decimal
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

MIN_CONFIRMATIONS = 2

def sync_balances():
    db = SessionLocal()
    try:
        addresses = db.query(Address).all()
        grouped = {}

        for addr in addresses:
            grouped.setdefault(addr.coin_symbol, []).append(addr)

        for coin_symbol, addrs in grouped.items():
            node = get_node(coin_symbol)
            print(f"[{coin_symbol}] Syncing {len(addrs)} addresses...")

            # Monero mode detection
            is_monero = node.__class__.__name__.lower() == "moneronode"

            # Sync state (block hash for BTC-style, timestamp for Monero)
            state = db.query(SyncState).filter_by(coin_symbol=coin_symbol).first()
            since_marker = state.last_block_hash if state else None

            if is_monero:
                # Group addresses by subaddr index (minor = actual subaddress index)
                index_map = {
                    int(a.extra_info.get("address_index", -1)): a
                    for a in addrs
                    if a.extra_info.get("address_index") is not None
                }

                transfers = node.get_transfers(account_index=0, in_=True)
                incoming = transfers.get("in", [])
                seen_timestamp = None

                for tx in incoming:
                    subaddr_info = tx.get("subaddr_index", {})
                    index = subaddr_info.get("minor")

                    if index is None:
                        continue

                    addr = index_map.get(index)
                    if not addr:
                        continue

                    txid = tx["txid"]
                    if db.query(Transaction).filter_by(tx_id=txid).first():
                        continue

                    amount = Decimal(tx["amount"]) / Decimal("1e12")
                    timestamp = datetime.fromtimestamp(tx["timestamp"], tz=timezone.utc)

                    if tx["confirmations"] < MIN_CONFIRMATIONS:
                        continue
                    if since_marker and timestamp <= datetime.fromisoformat(since_marker):
                        continue

                    balance = get_or_create_balance(db, addr.user_id, coin_symbol)
                    balance.total += amount
                    balance.available += amount

                    db.add(Transaction(
                        user_id=addr.user_id,
                        tx_id=txid,
                        amount=amount,
                        direction='received',
                        coin_symbol=coin_symbol,
                        created_at=timestamp
                    ))

                    seen_timestamp = max(seen_timestamp or timestamp, timestamp)
                    print(f"➕ {coin_symbol} | Subaddr idx {index} | {amount} | {txid}")

                # Update sync state
                if seen_timestamp:
                    if not state:
                        state = SyncState(coin_symbol=coin_symbol)
                        db.add(state)
                    state.last_block_hash = seen_timestamp.isoformat()

            else:
                # Bitcoin-like sync logic
                txs = node._rpc_request("listtransactions", ["*", 1000, 0, True, since_marker])
                seen_blockhash = None

                for addr in addrs:
                    for tx in txs:
                        if tx.get("address") != addr.address:
                            continue
                        if tx.get("category") != "receive":
                            continue
                        if tx.get("confirmations", 0) < MIN_CONFIRMATIONS:
                            continue

                        txid = tx.get("txid")
                        if db.query(Transaction).filter_by(tx_id=txid).first():
                            continue

                        amount = Decimal(str(tx.get("amount")))
                        seen_blockhash = tx.get("blockhash") or seen_blockhash

                        balance = get_or_create_balance(db, addr.user_id, coin_symbol)
                        balance.total += amount
                        balance.available += amount

                        db.add(Transaction(
                            user_id=addr.user_id,
                            tx_id=txid,
                            amount=amount,
                            direction='received',
                            coin_symbol=coin_symbol,
                            created_at=datetime.fromtimestamp(tx.get("time"), tz=timezone.utc)
                        ))

                        print(f"➕ {coin_symbol} | {addr.address} | {amount} | {txid}")

                if seen_blockhash:
                    if not state:
                        state = SyncState(coin_symbol=coin_symbol)
                        db.add(state)
                    state.last_block_hash = seen_blockhash

            db.commit()

    except Exception as e:
        db.rollback()
        print("❌ Error syncing:", str(e))
    finally:
        db.close()

if __name__ == "__main__":
    sync_balances()
