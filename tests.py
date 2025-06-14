from decimal import Decimal
import threading
import requests
from db import SessionLocal
from models import Balance, User
from utils import hash_api_key
from sqlalchemy.orm.exc import NoResultFound
from resetTables import wipe_tables

BASE_URL = "http://localhost:5000"
FEE_RATE = Decimal("0.001")  # 0.1%


def auth_headers(api_key):
    return {"Authorization": f"Bearer {api_key}"}


def create_user():
    r = requests.post(f"{BASE_URL}/create_account")
    r.raise_for_status()
    return r.json()["api_key"]


def create_market(base="DGB", quote="DOGE", fee_rate=Decimal("0.001")):
    r = requests.post(f"{BASE_URL}/admin/create_market", json={
        "base_coin": base,
        "quote_coin": quote,
        "fee_rate": str(fee_rate)
    })
    r.raise_for_status()
    return r.json()["market_id"]


def set_balance(api_key, coin, amount):
    db = SessionLocal()
    try:
        hashed = hash_api_key(api_key)
        user = db.query(User).filter_by(api_key_hash=hashed).first()
        assert user, "User not found by hashed key!"

        balance = db.query(Balance).filter_by(user_id=user.id, coin_symbol=coin).first()
        if not balance:
            balance = Balance(
                user_id=user.id,
                coin_symbol=coin,
                available=amount,
                total=amount,
                locked=Decimal("0.0")
            )
            db.add(balance)
        else:
            balance.available = amount
            balance.total = amount
            balance.locked = Decimal("0.0")
        db.commit()
        print(f"✅ Balance set for user_id={user.id}, {coin} = {amount}")
    finally:
        db.close()


def get_balance(api_key, coin):
    r = requests.get(f"{BASE_URL}/balance", headers=auth_headers(api_key), params={"coin": coin})
    r.raise_for_status()
    return r.json().get(coin, {})


def place_order(api_key, market_id, side, price, amount):
    r = requests.post(f"{BASE_URL}/order", headers=auth_headers(api_key), json={
        "market_id": market_id,
        "side": side,
        "price": str(price),
        "amount": str(amount)
    })
    if r.status_code != 201:
        print(f"❌ Failed placing {side} order: {r.status_code}")
        print(r.text)
        r.raise_for_status()
    return r.json()


def get_fees():
    r = requests.get(f"{BASE_URL}/admin/fees")
    r.raise_for_status()
    return r.json()

def run_test():
    print("🚀 Starting DGB/DOGE market test...")

    # Create users
    buyer_key = create_user()
    seller_key = create_user()

    # Create market
    market_id = create_market()
    print(f"✅ Market created: ID {market_id}")

    # ----------- Initial Trade Test ----------- #
    reset_balances_and_orders(buyer_key, ["DOGE", "DGB"])
    reset_balances_and_orders(seller_key, ["DOGE", "DGB"])
    set_balance(buyer_key, "DOGE", Decimal("1000"))
    set_balance(seller_key, "DGB", Decimal("100"))

    buy = place_order(buyer_key, market_id, "buy", Decimal("1"), Decimal("10"))
    print(f"✅ Buy order placed: {buy}")
    sell = place_order(seller_key, market_id, "sell", Decimal("1"), Decimal("10"))
    print(f"✅ Sell order placed: {sell}")

    buyer_bal = get_balance(buyer_key, "DGB")
    seller_bal = get_balance(seller_key, "DOGE")
    print(f"📊 Buyer DGB balance: {buyer_bal}")
    print(f"📊 Seller DOGE balance: {seller_bal}")

    expected = Decimal("10") * (Decimal("1") - FEE_RATE)
    assert Decimal(buyer_bal["available"]) == expected
    assert Decimal(seller_bal["available"]) == expected

    fees = get_fees()
    print(f"💰 Fee balances: DGB={fees.get('DGB')}, DOGE={fees.get('DOGE')}")
    assert Decimal(fees.get("DGB", "0")) >= FEE_RATE * Decimal("10")
    assert Decimal(fees.get("DOGE", "0")) >= FEE_RATE * Decimal("10")
    print("✅✅✅ Trade test passed.")

    # ----------- Partial Fill Test ----------- #
    print("\n🧪 Testing partial fill...")
    reset_balances_and_orders(buyer_key, ["DOGE", "DGB"])
    reset_balances_and_orders(seller_key, ["DOGE", "DGB"])
    set_balance(buyer_key, "DOGE", Decimal("1000"))
    set_balance(seller_key, "DGB", Decimal("5"))

    partial_buy = place_order(buyer_key, market_id, "buy", Decimal("1"), Decimal("10"))
    partial_sell = place_order(seller_key, market_id, "sell", Decimal("1"), Decimal("5"))

    buyer_bal = get_balance(buyer_key, "DGB")
    seller_bal = get_balance(seller_key, "DOGE")

    expected_partial = Decimal("5") * (Decimal("1") - FEE_RATE)
    assert Decimal(buyer_bal["available"]) == expected_partial
    assert Decimal(seller_bal["available"]) == expected_partial

    print(f"📊 Buyer DGB balance (partial): {buyer_bal}")
    print(f"📊 Seller DOGE balance (partial): {seller_bal}")
    print("✅ Partial fill test passed.")

    # ----------- Order Cancellation Test ----------- #
    print("\n🧪 Testing order cancellation...")

    open_orders = requests.get(f"{BASE_URL}/orders", headers=auth_headers(buyer_key)).json()
    open_order_id = next((o["order_id"] for o in open_orders if Decimal(o["remaining"]) > 0), None)
    assert open_order_id, "No open order to cancel"

    cancel = requests.post(
        f"{BASE_URL}/cancel_order",
        headers=auth_headers(buyer_key),
        json={"order_id": open_order_id}
    )
    cancel.raise_for_status()
    print(f"✅ Cancelled open order: {cancel.json()}")

    buyer_doge = get_balance(buyer_key, "DOGE")
    print(f"📊 Buyer DOGE after cancellation: {buyer_doge}")

    expected_refund = Decimal("5")
    assert Decimal(buyer_doge["available"]) >= expected_refund - Decimal("0.00000001")

    print("✅ Cancellation test passed.")
    print("\n🎉 All tests passed successfully!")

        # ------------------------------------------------------------

    print("\n🧪 Testing multi-match...")

    reset_balances_and_orders(buyer_key, ["DOGE", "DGB"])
    reset_balances_and_orders(seller_key, ["DOGE", "DGB"])

    set_balance(buyer_key, "DOGE", Decimal("1000"))

    # Seller 1: 3 DGB
    seller_key_1 = create_user()
    reset_balances_and_orders(seller_key_1, ["DGB", "DOGE"])
    set_balance(seller_key_1, "DGB", Decimal("3"))
    place_order(seller_key_1, market_id, "sell", Decimal("1"), Decimal("3"))

    # Seller 2: 3 DGB
    seller_key_2 = create_user()
    reset_balances_and_orders(seller_key_2, ["DGB", "DOGE"])
    set_balance(seller_key_2, "DGB", Decimal("3"))
    place_order(seller_key_2, market_id, "sell", Decimal("1"), Decimal("3"))

    # Seller 3: 3 DGB
    seller_key_3 = create_user()
    reset_balances_and_orders(seller_key_3, ["DGB", "DOGE"])
    set_balance(seller_key_3, "DGB", Decimal("3"))
    place_order(seller_key_3, market_id, "sell", Decimal("1"), Decimal("3"))

    # Buyer wants 9 DGB
    buy_resp = place_order(buyer_key, market_id, "buy", Decimal("1"), Decimal("9"))
    assert len(buy_resp["trades"]) == 3, "Should match 3 trades"
    print(f"✅ Buyer order matched against {len(buy_resp['trades'])} sellers.")

    buyer_bal = get_balance(buyer_key, "DGB")
    expected_total = Decimal("9") * (Decimal("1") - FEE_RATE)
    assert Decimal(buyer_bal["available"]) == expected_total
    print(f"📊 Buyer DGB after multi-match: {buyer_bal}")
    print("✅ Multi-match test passed.")

    # ----------- Price Improvement Test ----------- #
    print("\n🧪 Testing price improvement...")

    reset_balances_and_orders(buyer_key, ["DOGE", "DGB"])
    reset_balances_and_orders(seller_key, ["DOGE", "DGB"])

    set_balance(buyer_key, "DOGE", Decimal("1000"))
    set_balance(seller_key, "DGB", Decimal("10"))

    # Buyer willing to pay 1.00 per DGB
    place_order(buyer_key, market_id, "buy", Decimal("1.00"), Decimal("5"))

    # Seller offers DGB for 0.95 (cheaper)
    place_order(seller_key, market_id, "sell", Decimal("0.95"), Decimal("5"))

    buyer_bal_dgb = get_balance(buyer_key, "DGB")
    buyer_bal_doge = get_balance(buyer_key, "DOGE")

    # Expected received DGB after fee
    expected_received_dgb = Decimal("5") * (Decimal("1") - FEE_RATE)
    assert Decimal(buyer_bal_dgb["available"]) == expected_received_dgb.quantize(Decimal("0.00000001"))

    # DOGE balance breakdown
    trade_price = Decimal("0.95")
    trade_amount = Decimal("5")
    spent = trade_price * trade_amount  # 4.75
    fee = spent * FEE_RATE              # 0.00475
    total_deducted = spent + fee        # 4.75475
    expected_available_doge = Decimal("1000") - total_deducted
    expected_locked_doge = Decimal("5.00") - spent  # Unused quote locked (0.25)
    expected_total_doge = expected_available_doge + expected_locked_doge

    # Assertions
    assert Decimal(buyer_bal_doge["available"]) == expected_available_doge.quantize(Decimal("0.00000001"))
    assert Decimal(buyer_bal_doge["locked"]) == expected_locked_doge.quantize(Decimal("0.00000001"))
    assert Decimal(buyer_bal_doge["total"]) == expected_total_doge.quantize(Decimal("0.00000001")), \
        f"Total mismatch: expected {expected_total_doge}, got {buyer_bal_doge['total']}"

    print(f"📊 Buyer DGB (price improvement): {buyer_bal_dgb}")
    print(f"📊 Buyer DOGE (after fee/lock): {buyer_bal_doge}")

    print("✅ Price improvement test passed.")

    concurrency_test()



# Helper stays unchanged
def reset_balances_and_orders(api_key, coins):
    db = SessionLocal()
    try:
        hashed = hash_api_key(api_key)
        user = db.query(User).filter_by(api_key_hash=hashed).first()
        assert user, "User not found"

        # Reset balances
        for coin in coins:
            bal = db.query(Balance).filter_by(user_id=user.id, coin_symbol=coin).first()
            if bal:
                bal.available = Decimal("0")
                bal.locked = Decimal("0")
                bal.total = Decimal("0")
        db.commit()
    finally:
        db.close()

    # Cancel all open orders
    orders = requests.get(f"{BASE_URL}/orders", headers=auth_headers(api_key)).json()
    for o in orders:
        if o["status"] in ["open", "partially_filled"]:
            requests.post(f"{BASE_URL}/cancel_order", headers=auth_headers(api_key), json={"order_id": o["order_id"]})

def concurrency_test():
    print("\n🧪 Testing concurrency safety...")

    # Reset everything
    wipe_tables()
    buyer_key_1 = create_user()
    buyer_key_2 = create_user()
    seller_key = create_user()

    reset_balances_and_orders(buyer_key_1, ["DOGE", "DGB"])
    reset_balances_and_orders(buyer_key_2, ["DOGE", "DGB"])
    reset_balances_and_orders(seller_key, ["DOGE", "DGB"])

    set_balance(buyer_key_1, "DOGE", Decimal("1000"))
    set_balance(buyer_key_2, "DOGE", Decimal("1000"))
    set_balance(seller_key, "DGB", Decimal("10"))

    # Create a fresh market
    market_id = create_market(base="DGB", quote="DOGE")

    # Seller places a single sell order
    place_order(seller_key, market_id, "sell", Decimal("1.0"), Decimal("10"))

    results = {}

    def buyer_thread(api_key, label):
        try:
            resp = place_order(api_key, market_id, "buy", Decimal("1.0"), Decimal("10"))
            results[label] = resp
        except Exception as e:
            results[label] = {"error": str(e)}

    # Spawn two concurrent buyers
    t1 = threading.Thread(target=buyer_thread, args=(buyer_key_1, "buyer1"))
    t2 = threading.Thread(target=buyer_thread, args=(buyer_key_2, "buyer2"))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    print(f"👤 Buyer 1 result: {results['buyer1']}")
    print(f"👤 Buyer 2 result: {results['buyer2']}")

    # Now check balances
    bal_1 = get_balance(buyer_key_1, "DGB")
    bal_2 = get_balance(buyer_key_2, "DGB")
    seller_bal = get_balance(seller_key, "DOGE")
    fees = get_fees()

    print(f"📊 Buyer 1 DGB: {bal_1}")
    print(f"📊 Buyer 2 DGB: {bal_2}")
    print(f"📊 Seller DOGE: {seller_bal}")
    print(f"💰 Fees: {fees}")

    # Validate: exactly one buyer got the DGB
    b1 = Decimal(bal_1.get("available", "0"))
    b2 = Decimal(bal_2.get("available", "0"))
    assert (b1 > 0 and b2 == 0) or (b2 > 0 and b1 == 0), "❌ Both buyers got DGB (double match!) or none did"

    # Validate: only one trade occurred (DGB = 10 - 0.01)
    expected = Decimal("10") * (Decimal("1") - FEE_RATE)
    actual = max(b1, b2)
    assert actual == expected, f"❌ Incorrect DGB received: got {actual}, expected {expected}"

    # Validate: seller received DOGE minus fee
    seller_expected = Decimal("10") * (Decimal("1") - FEE_RATE)
    assert Decimal(seller_bal["available"]) == seller_expected, "❌ Seller DOGE incorrect"

    # Validate: fee balance is only from one trade
    assert Decimal(fees.get("DGB", "0")) >= Decimal("0.01")
    assert Decimal(fees.get("DOGE", "0")) >= Decimal("0.01")

    print("✅ Concurrency test passed — no double match occurred.")

if __name__ == "__main__":
    run_test()
