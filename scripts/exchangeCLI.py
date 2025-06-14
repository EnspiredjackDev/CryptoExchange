import requests
import json
import os

BASE_URL = "http://127.0.0.1:5000"
CONFIG_FILE = "api_key.json"

def save_api_key(key):
    with open(CONFIG_FILE, "w") as f:
        json.dump({"api_key": key}, f)

def load_api_key():
    if not os.path.exists(CONFIG_FILE):
        return None
    with open(CONFIG_FILE, "r") as f:
        return json.load(f).get("api_key")

def call_api(endpoint, method="GET", data=None):
    api_key = load_api_key()
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = f"{BASE_URL}{endpoint}"

    try:
        if method == "GET":
            res = requests.get(url, headers=headers, params=data)
        else:
            res = requests.post(url, headers=headers, json=data)
        print(json.dumps(res.json(), indent=2))
    except Exception as e:
        print(f"Error: {str(e)}")

def main():
    while True:
        print("\n--- Exchange CLI ---")
        print("1. Create Account")
        print("2. Show Balance")
        print("3. Generate Address")
        print("4. Withdraw")
        print("5. Place Order")
        print("6. Create Market (admin)")
        print("7. Exit")
        print("8. View Trade History")
        print("9. Cancel Order")
        print("10. View Order Book")
        print("11. View Open Orders")
        print("12. View Fee Balances (admin)")
        print("13. Withdraw Fee Balance (admin)")

        choice = input("Select option: ").strip()

        if choice == "1":
            res = requests.post(f"{BASE_URL}/create_account")
            data = res.json()
            api_key = data.get("api_key")
            if api_key:
                save_api_key(api_key)
                print("✅ Account created and API key saved.")
            else:
                print("❌ Failed to create account.")
            print(json.dumps(data, indent=2))

        elif choice == "2":
            coin = input("Filter by coin (optional): ").strip()
            params = {"coin": coin} if coin else None
            call_api("/balance", "GET", params)

        elif choice == "3":
            coin = input("Coin symbol (e.g. DGB): ").strip()
            call_api("/generate_address", "POST", {"coin": coin})

        elif choice == "4":
            coin = input("Coin: ").strip()
            amount = float(input("Amount: "))
            address = input("To address: ").strip()
            call_api("/withdraw", "POST", {
                "coin": coin,
                "amount": amount,
                "to_address": address
            })

        elif choice == "5":
            market_id = int(input("Market ID: "))
            side = input("Side (buy/sell): ").strip()
            price = float(input("Price: "))
            amount = float(input("Amount: "))
            call_api("/order", "POST", {
                "market_id": market_id,
                "side": side,
                "price": price,
                "amount": amount
            })

        elif choice == "6":
            base = input("Base coin (e.g. DGB): ").strip()
            quote = input("Quote coin (e.g. DOGE): ").strip()
            call_api("/admin/create_market", "POST", {
                "base_coin": base,
                "quote_coin": quote
            })

        elif choice == "7":
            print("Goodbye!")
            break

        elif choice == "8":
            coin = input("Filter by coin (optional): ").strip()
            limit = input("Limit (default 50): ").strip()

            params = {}
            if coin:
                params["coin"] = coin.upper()
            if limit:
                params["limit"] = limit

            call_api("/trades", "GET", params)

        elif choice == "9":
            order_id = input("Order ID to cancel: ").strip()
            if not order_id:
                print("❌ Order ID is required.")
            else:
                call_api("/cancel_order", "POST", {"order_id": order_id})

        elif choice == "10":
            market_id = input("Market ID: ").strip()
            depth = input("Depth (default 10): ").strip()
            params = {"market_id": market_id}
            if depth:
                params["depth"] = depth
            call_api("/orderbook", "GET", params)
        
        elif choice == "11":
            coin = input("Filter by coin (optional): ").strip().upper()
            market_id = input("Filter by market ID (optional): ").strip()
            params = {}
            if coin:
                params["coin"] = coin
            if market_id:
                params["market_id"] = market_id
            call_api("/orders", "GET", params)

        elif choice == "12":
            # View fee balances
            call_api("/admin/fees", "GET")

        elif choice == "13":
            # Withdraw fee balance
            coin = input("Coin symbol: ").strip().upper()
            amount = input("Amount to withdraw: ").strip()
            if not coin or not amount:
                print("❌ Coin and amount are required.")
            else:
                try:
                    amount_value = float(amount)
                except ValueError:
                    print("❌ Amount must be a number.")
                else:
                    call_api("/admin/fees", "POST", {"coin": coin, "amount": amount_value})



        else:
            print("❌ Invalid option")

if __name__ == "__main__":
    main()
