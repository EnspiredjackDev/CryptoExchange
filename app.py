from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal
from flask import Flask, request, jsonify
from sqlalchemy import func
from db import SessionLocal
from models import Balance, FeeBalance, Market, Order, OrderSide, OrderStatus, Trade, User, Base, Address, Transaction
from utils import generate_api_key, hash_api_key, start_money_transaction, xmr_to_atomic
from coinNodes import get_node
from matcher import match_orders

app = Flask(__name__)

@app.route('/create_account', methods=['POST'])
def create_account():
    db = SessionLocal()
    try:
        raw_key = generate_api_key()
        hashed_key = hash_api_key(raw_key)

        user = User(api_key_hash=hashed_key)
        db.add(user)
        db.commit()

        return jsonify({"api_key": raw_key}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()
    
@app.route('/generate_address', methods=['POST'])
def generate_address():
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not api_key:
        return jsonify({"error": "Missing API key"}), 401

    data = request.get_json()
    coin = data.get("coin")

    if not coin:
        return jsonify({"error": "Missing coin symbol"}), 400

    db = SessionLocal()
    try:
        # Auth user
        hashed_key = hash_api_key(api_key)
        user = db.query(User).filter_by(api_key_hash=hashed_key).first()
        if not user:
            return jsonify({"error": "Invalid API key"}), 403
        
        if coin == "XMR":
            node = get_node(coin)
            label = f"user_{user.id}"
            result = node.create_subaddress(account_index=0, label=label)

            # Check for duplicates
            exists = db.query(Address).filter_by(address=result["address"], coin_symbol="XMR").first()
            if exists:
                return jsonify({"error": "Generated address already exists. Please retry."}), 500

            addr = Address(
                user_id=user.id,
                address=result["address"],
                coin_symbol="XMR",
                extra_info={"address_index": result["address_index"]}
            )
            db.add(addr)
            db.commit()
            return jsonify({"address": addr.address})
        else:
            attempts = 0
            max_attempts = 5
            new_address = None

            while attempts < max_attempts:
                candidate_address = node.get_new_address()
                exists = db.query(Address).filter_by(address=candidate_address, coin_symbol=coin.upper()).first()
                if not exists:
                    new_address = candidate_address
                    break
                attempts += 1

            if not new_address:
                return jsonify({"error": "Failed to generate a unique address after several attempts"}), 500

            addr = Address(
                user_id=user.id,
                address=new_address,
                coin_symbol=coin.upper()
            )
            db.add(addr)
            db.commit()

        return jsonify({
            "coin": coin.upper(),
            "address": new_address
        }), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.route('/addresses', methods=['GET'])
def list_addresses():
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not api_key:
        return jsonify({"error": "Missing API key"}), 401

    coin_filter = request.args.get("coin", None)

    db = SessionLocal()
    try:
        hashed_key = hash_api_key(api_key)
        user = db.query(User).filter_by(api_key_hash=hashed_key).first()
        if not user:
            return jsonify({"error": "Invalid API key"}), 403

        query = db.query(Address).filter_by(user_id=user.id)
        if coin_filter:
            query = query.filter(Address.coin_symbol == coin_filter.upper())

        addresses = query.order_by(Address.created_at.desc()).all()

        return jsonify([{
            "address": a.address,
            "coin": a.coin_symbol,
            "created_at": a.created_at.isoformat()
        } for a in addresses]), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.route('/balance', methods=['GET'])
def get_user_balances():
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not api_key:
        return jsonify({"error": "Missing API key"}), 401

    coin_filter = request.args.get("coin", None)

    db = SessionLocal()
    try:
        hashed_key = hash_api_key(api_key)
        user = db.query(User).filter_by(api_key_hash=hashed_key).first()
        if not user:
            return jsonify({"error": "Invalid API key"}), 403

        balances_query = db.query(Balance).filter_by(user_id=user.id)
        if coin_filter:
            balances_query = balances_query.filter(Balance.coin_symbol == coin_filter.upper())

        result = {}
        for b in balances_query.all():
            result[b.coin_symbol] = {
                "available": str(b.available),
                "locked": str(b.locked),
                "total": str(b.total)
            }

        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.route('/withdraw', methods=['POST'])
def withdraw_funds():
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not api_key:
        return jsonify({"error": "Missing API key"}), 401

    data = request.get_json()
    coin = data.get("coin", "").upper()
    to_address = data.get("to_address")
    amount = data.get("amount")

    if not all([coin, to_address, amount]):
        return jsonify({"error": "Missing required fields: coin, to_address, amount"}), 400

    try:
        amount = Decimal(str(amount))
        amount = amount.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        if amount <= 0:
            return jsonify({"error": "Invalid amount"}), 400
    except ValueError:
        return jsonify({"error": "Amount must be numeric"}), 400

    db = SessionLocal()
    start_money_transaction(db)
    try:
        # Authenticate user
        hashed_key = hash_api_key(api_key)
        user = db.query(User).filter_by(api_key_hash=hashed_key).first()
        if not user:
            return jsonify({"error": "Invalid API key"}), 403

        # Fetch balance
        balance = db.query(Balance).with_for_update().filter_by(user_id=user.id, coin_symbol=coin).first()
        if not balance or balance.available < amount:
            return jsonify({"error": "Insufficient available balance"}), 400

        # Deduct funds BEFORE sending
        balance.available -= amount
        balance.total -= amount
        db.flush()

        node = get_node(coin)
        is_monero = node.__class__.__name__.lower() == "moneronode"

        if is_monero:
            # Convert to atomic
            amount_atomic = int(amount * Decimal("1e12"))

            # Optional: use known subaddr_index if you want to track send source
            tx_result = node.send_to_address(to_address, amount_atomic)

            txid = tx_result.get("tx_hash")
            if not txid:
                raise Exception("Monero node did not return tx_hash")

        else:
            # BTC-like coins
            txid = node.send_to_address(to_address, format(amount, "f"))
            if not txid:
                raise Exception("Node did not return txid")

        # Log the withdrawal
        new_tx = Transaction(
            user_id=user.id,
            tx_id=txid,
            amount=amount,
            direction='sent',
            coin_symbol=coin,
            created_at=datetime.now(timezone.utc)
        )
        db.add(new_tx)

        db.commit()

        return jsonify({
            "status": "success",
            "txid": txid,
            "amount": str(amount),
            "coin": coin
        }), 200

    except Exception as e:
        db.rollback()
        return jsonify({"error": f"Withdrawal failed: {str(e)}"}), 500
    finally:
        db.close()

@app.route('/order', methods=['POST'])
def place_order():
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not api_key:
        return jsonify({"error": "Missing API key"}), 401

    data = request.get_json()
    market_id = data.get("market_id")
    side = data.get("side")
    price = data.get("price")
    amount = data.get("amount")

    if not all([market_id, side, price, amount]):
        return jsonify({"error": "Missing required fields"}), 400

    try:
        price = Decimal(str(price)).quantize(Decimal("0.00000001"))
        amount = Decimal(str(amount)).quantize(Decimal("0.00000001"))
        if price <= 0 or amount <= 0:
            return jsonify({"error": "Invalid price or amount"}), 400
    except:
        return jsonify({"error": "Invalid number format"}), 400

    db = SessionLocal()
    # start_money_transaction(db)
    try:
        with db.begin():  # ensures atomic transaction
            hashed_key = hash_api_key(api_key)
            user = db.query(User).filter_by(api_key_hash=hashed_key).first()
            if not user:
                return jsonify({"error": "Invalid API key"}), 403

            market = db.query(Market).filter_by(id=market_id, active=True).first()
            if not market:
                return jsonify({"error": "Market not found"}), 404

            base_coin = market.base_coin
            quote_coin = market.quote_coin
            side_enum = OrderSide(side)
            total_quote = price * amount

            if side_enum == OrderSide.buy:
                balance = db.query(Balance).with_for_update().filter_by(
                    user_id=user.id, coin_symbol=quote_coin
                ).first()
                if not balance or balance.available < total_quote:
                    return jsonify({"error": "Insufficient quote balance"}), 400
                balance.available -= total_quote
                balance.locked += total_quote

            elif side_enum == OrderSide.sell:
                balance = db.query(Balance).with_for_update().filter_by(
                    user_id=user.id, coin_symbol=base_coin
                ).first()
                if not balance or balance.available < amount:
                    return jsonify({"error": "Insufficient base balance"}), 400
                balance.available -= amount
                balance.locked += amount

            # Create and flush order
            new_order = Order(
                user_id=user.id,
                market_id=market_id,
                side=side_enum,
                price=price,
                amount=amount,
                remaining=amount
            )
            db.add(new_order)
            db.flush()

            # Match engine works in this transaction
            trades = match_orders(db, market_id)

        # Return response outside the transaction
        return jsonify({
            "order_id": new_order.id,
            "status": new_order.status.value,
            "filled": str(amount - new_order.remaining),
            "remaining": str(new_order.remaining),
            "trades": [{
                "amount": str(t.amount),
                "price": str(t.price),
                "timestamp": t.timestamp.isoformat()
            } for t in trades if t.buy_order_id == new_order.id or t.sell_order_id == new_order.id]
        }), 201

    except Exception as e:
        db.rollback()
        return jsonify({"error": f"Order failed: {str(e)}"}), 500
    finally:
        db.close()

@app.route('/trades', methods=['GET'])
def get_trade_history():
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not api_key:
        return jsonify({"error": "Missing API key"}), 401

    coin = request.args.get("coin", "").upper()
    market_id = request.args.get("market_id")
    limit = request.args.get("limit", 50)

    try:
        limit = int(limit)
        if limit <= 0 or limit > 200:
            return jsonify({"error": "Limit must be between 1 and 200"}), 400
    except ValueError:
        return jsonify({"error": "Invalid limit"}), 400

    db = SessionLocal()
    try:
        hashed_key = hash_api_key(api_key)
        user = db.query(User).filter_by(api_key_hash=hashed_key).first()
        if not user:
            return jsonify({"error": "Invalid API key"}), 403

        q = db.query(Trade).join(Market).filter(
            (Trade.buy_order.has(user_id=user.id)) |
            (Trade.sell_order.has(user_id=user.id))
        )

        if market_id:
            q = q.filter(Trade.market_id == market_id)
        elif coin:
            q = q.filter(
                (Market.base_coin == coin) | (Market.quote_coin == coin)
            )

        trades = q.order_by(Trade.timestamp.desc()).limit(limit).all()

        return jsonify([
            {
                "market": f"{t.market.base_coin}/{t.market.quote_coin}",
                "price": str(t.price),
                "amount": str(t.amount),
                "side": (
                    "buy" if t.buy_order.user_id == user.id else "sell"
                ),
                "order_status": (
                    t.buy_order.status.value if t.buy_order.user_id == user.id
                    else t.sell_order.status.value
                ),
                "timestamp": t.timestamp.isoformat()
            } for t in trades
        ])


    except Exception as e:
        return jsonify({"error": f"Failed to fetch trades: {str(e)}"}), 500
    finally:
        db.close()

@app.route('/cancel_order', methods=['POST'])
def cancel_order():
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not api_key:
        return jsonify({"error": "Missing API key"}), 401

    data = request.get_json()
    order_id = data.get("order_id")
    if not order_id:
        return jsonify({"error": "Missing order_id"}), 400

    db = SessionLocal()
    # start_money_transaction(db)
    try:
        with db.begin():
            user = db.query(User).filter_by(api_key_hash=hash_api_key(api_key)).first()
            if not user:
                return jsonify({"error": "Invalid API key"}), 403

            order = db.query(Order).with_for_update().filter_by(
                id=order_id, user_id=user.id
            ).first()

            if not order:
                return jsonify({"error": "Order not found"}), 404

            if order.status not in [OrderStatus.open, OrderStatus.partially_filled]:
                return jsonify({"error": f"Order already {order.status.value}"}), 400

            remaining = order.remaining
            market = order.market

            if order.side == OrderSide.buy:
                refund = Decimal(remaining) * Decimal(order.price)
                bal = db.query(Balance).with_for_update().filter_by(
                    user_id=user.id, coin_symbol=market.quote_coin
                ).first()
                bal.locked -= refund
                bal.available += refund

            else:
                bal = db.query(Balance).with_for_update().filter_by(
                    user_id=user.id, coin_symbol=market.base_coin
                ).first()
                bal.locked -= Decimal(remaining)
                bal.available += Decimal(remaining)

            order.status = OrderStatus.cancelled

        return jsonify({"status": "cancelled", "order_id": order.id}), 200

    except Exception as e:
        db.rollback()
        return jsonify({"error": f"Cancellation failed: {str(e)}"}), 500
    finally:
        db.close()

@app.route('/orderbook', methods=['GET'])
def get_orderbook():
    market_id = request.args.get("market_id")
    depth = request.args.get("depth", 10)

    if not market_id:
        return jsonify({"error": "Missing market_id"}), 400

    try:
        market_id = int(market_id)
        depth = int(depth)
    except ValueError:
        return jsonify({"error": "market_id and depth must be integers"}), 400

    if depth <= 0 or depth > 100:
        return jsonify({"error": "Depth must be between 1 and 100"}), 400

    db = SessionLocal()
    try:
        market = db.query(Market).filter_by(id=market_id).first()
        if not market:
            return jsonify({"error": "Market not found"}), 404

        # Bids (buys): highest price first
        bids = db.query(Order).filter_by(
            market_id=market_id,
            side=OrderSide.buy,
            status=OrderStatus.open
        ).order_by(Order.price.desc()).all()

        # Asks (sells): lowest price first
        asks = db.query(Order).filter_by(
            market_id=market_id,
            side=OrderSide.sell,
            status=OrderStatus.open
        ).order_by(Order.price.asc()).all()

        # Aggregate by price
        def aggregate(orders, reverse=False):
            price_levels = {}
            for order in orders:
                p = str(order.price)
                a = str(order.remaining)
                price_levels[p] = price_levels.get(p, 0.0) + a
            sorted_levels = sorted(price_levels.items(), reverse=reverse)
            return [{"price": p, "amount": round(a, 8)} for p, a in sorted_levels[:depth]]


        return jsonify({
            "market": f"{market.base_coin}/{market.quote_coin}",
            "bids": aggregate(bids),
            "asks": aggregate(asks)
        })

    except Exception as e:
        return jsonify({"error": f"Failed to fetch order book: {str(e)}"}), 500
    finally:
        db.close()

@app.route('/orders', methods=['GET'])
def get_open_orders():
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not api_key:
        return jsonify({"error": "Missing API key"}), 401

    coin = request.args.get("coin", "").upper()
    market_id = request.args.get("market_id")

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(api_key_hash=hash_api_key(api_key)).first()
        if not user:
            return jsonify({"error": "Invalid API key"}), 403

        query = db.query(Order).join(Market).filter(
            Order.user_id == user.id,
            Order.status.in_([OrderStatus.open, OrderStatus.partially_filled])
        )

        if market_id:
            try:
                market_id = int(market_id)
                query = query.filter(Order.market_id == market_id)
            except ValueError:
                return jsonify({"error": "Invalid market_id"}), 400
        elif coin:
            query = query.filter(
                (Market.base_coin == coin) | (Market.quote_coin == coin)
            )

        query = query.order_by(Order.created_at.desc())
        orders = query.all()

        return jsonify([
            {
                "order_id": o.id,
                "market": f"{o.market.base_coin}/{o.market.quote_coin}",
                "side": o.side.value,
                "price": str(o.price),
                "amount": str(o.amount),
                "remaining": str(o.remaining),
                "status": o.status.value,
            } for o in orders
        ])
    except Exception as e:
        return jsonify({"error": f"Failed to fetch orders: {str(e)}"}), 500
    finally:
        db.close()

@app.route("/markets", methods=["GET"])
def get_markets():
    db = SessionLocal()
    try:
        markets = db.query(Market).all()
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=24)

        result = []

        for m in markets:
            # Last trade
            last_trade = db.query(Trade).filter_by(
                market_id=m.id
            ).order_by(Trade.timestamp.desc()).first()

            # 24h volume and trade count
            trade_stats = db.query(
                func.coalesce(func.sum(Trade.amount), 0),
                func.count(Trade.id)
            ).filter(
                Trade.market_id == m.id,
                Trade.timestamp >= since
            ).first()
            volume_24h, trade_count_24h = trade_stats

            # Best bid and ask
            best_bid = db.query(Order).filter_by(
                market_id=m.id,
                side=OrderSide.buy,
                status=OrderStatus.open
            ).order_by(Order.price.desc()).first()

            best_ask = db.query(Order).filter_by(
                market_id=m.id,
                side=OrderSide.sell,
                status=OrderStatus.open
            ).order_by(Order.price.asc()).first()

            # 24h price change %
            open_trade = db.query(Trade).filter(
                Trade.market_id == m.id,
                Trade.timestamp >= since
            ).order_by(Trade.timestamp.asc()).first()

            last_price = float(last_trade.price) if last_trade else None
            open_price = float(open_trade.price) if open_trade else None

            change_24h = None
            if last_price is not None and open_price and open_price != 0:
                change_24h = round(((last_price - open_price) / open_price) * 100, 2)

            result.append({
                "market_id": m.id,
                "base_coin": m.base_coin,
                "quote_coin": m.quote_coin,
                "fee_rate": str(m.fee_rate),
                "label": f"{m.base_coin}/{m.quote_coin}",
                "last_price": last_price,
                "volume_24h": str(volume_24h),
                "trade_count_24h": trade_count_24h,
                "best_bid": str(best_bid.price) if best_bid else None,
                "best_ask": str(best_ask.price) if best_ask else None,
                "change_24h": change_24h
            })

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()








### ADMIN ONLY ZONE  (ADD SECURITY LATER) ####################################
@app.route('/admin/create_market', methods=['POST'])
def create_market():
    data = request.get_json()
    base_coin = data.get("base_coin", "").upper()
    quote_coin = data.get("quote_coin", "").upper()

    if not base_coin or not quote_coin:
        return jsonify({"error": "Missing base_coin or quote_coin"}), 400

    if base_coin == quote_coin:
        return jsonify({"error": "Base and quote cannot be the same"}), 400

    db = SessionLocal()
    try:
        # Check if market already exists
        existing = db.query(Market).filter_by(base_coin=base_coin, quote_coin=quote_coin).first()
        if existing:
            return jsonify({"error": "Market already exists", "market_id": existing.id}), 409

        new_market = Market(
            base_coin=base_coin,
            quote_coin=quote_coin,
            active=True
        )
        db.add(new_market)
        db.commit()

        return jsonify({
            "market_id": new_market.id,
            "base_coin": base_coin,
            "quote_coin": quote_coin,
            "status": "created"
        }), 201

    except Exception as e:
        db.rollback()
        return jsonify({"error": f"Could not create market: {str(e)}"}), 500
    finally:
        db.close()

@app.route("/admin/fees", methods=["GET", "POST"])
def manage_fees():
    # Add real auth checks later — for now this is open
    db = SessionLocal()
    try:
        if request.method == "GET":
            fees = db.query(FeeBalance).all()
            return jsonify({
                f.coin_symbol: str(f.amount)
                for f in fees
            })

        elif request.method == "POST":
            data = request.json
            coin = data.get("coin")
            amount = Decimal(str(data.get("amount", 0)))

            fb = db.query(FeeBalance).filter_by(coin_symbol=coin).first()
            if not fb or fb.amount < amount:
                return jsonify({"error": "Insufficient fee balance"}), 400

            fb.amount -= amount
            db.commit()
            return jsonify({
                "coin": coin,
                "withdrawn": str(amount),
                "remaining": str(fb.amount)
            })

    except Exception as e:
        db.rollback()
        return jsonify({"error": f"Fee handling error: {str(e)}"}), 500
    finally:
        db.close()


@app.route('/auth_test', methods=['GET'])
def auth_test():
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not api_key:
        return jsonify({"error": "Missing API key"}), 401

    hashed_key = hash_api_key(api_key)
    db = SessionLocal()
    user = db.query(User).filter_by(api_key_hash=hashed_key).first()
    db.close()

    if user:
        return jsonify({"message": "Authenticated", "user_id": user.id})
    else:
        return jsonify({"error": "Invalid API key"}), 403


####################################################################

if __name__ == '__main__':
    app.run(debug=True)
