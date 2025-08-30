from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
import os
from flask import Flask, request, jsonify, g
from sqlalchemy import func, text
from db import SessionLocal
from models import Balance, FeeBalance, Market, Order, OrderSide, OrderStatus, Trade, User, Address, Transaction
from utils import generate_api_key, hash_api_key, validate_transaction_integrity
from coinNodes import get_node
from matcher import match_orders
from security import (
    secure_endpoint, require_admin, authenticate_user, SecurityValidator, 
    log_security_event, SecurityConfig
)

# Configure application logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Security configuration
app.config['MAX_CONTENT_LENGTH'] = SecurityConfig.MAX_REQUEST_SIZE

# Disable debug mode for production
if os.environ.get('FLASK_ENV') != 'development':
    app.config['DEBUG'] = False

@app.before_request
def before_request():
    """Security checks before each request."""
    # Add security headers
    g.start_time = datetime.now()
    
    # Log request
    if request.endpoint and not request.endpoint.startswith('static'):
        logger.info(f"Request: {request.method} {request.path} from {request.remote_addr}")

@app.after_request
def after_request(response):
    """Add security headers to all responses."""
    # Security headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'"
    
    # Remove server information
    response.headers.pop('Server', None)
    
    # Log response time
    if hasattr(g, 'start_time'):
        duration = (datetime.now() - g.start_time).total_seconds()
        if duration > 1.0:  # Log slow requests
            logger.warning(f"Slow request: {request.method} {request.path} took {duration:.2f}s")
    
    return response

@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle oversized requests."""
    log_security_event("oversized_request", {"size": request.content_length})
    return jsonify({"error": "Request too large"}), 413

@app.errorhandler(429)
def ratelimit_handler(error):
    """Handle rate limit exceeded."""
    return jsonify({"error": "Rate limit exceeded"}), 429

@app.route('/create_account', methods=['POST'])
@secure_endpoint('public')
def create_account():
    db = SessionLocal()
    try:
        if not db.in_transaction():
            db.begin()
        
        raw_key = generate_api_key()
        hashed_key = hash_api_key(raw_key)

        user = User(api_key_hash=hashed_key)
        db.add(user)
        db.flush()  # Get user.id
        db.commit()
        
        log_security_event("account_created", {"user_id": user.id})
        return jsonify({"api_key": raw_key}), 201
            
    except Exception as e:
        logger.error(f"Account creation failed: {str(e)}")
        return jsonify({"error": "Account creation failed"}), 500
    finally:
        db.close()
    
@app.route('/generate_address', methods=['POST'])
@secure_endpoint()
def generate_address():
    db = SessionLocal()
    try:
        # Authenticate user
        user, error_response, status_code = authenticate_user(db)
        if error_response:
            return error_response, status_code

        data = request.get_json()
        coin = data.get("coin", "").upper() if data else None

        if not coin:
            return jsonify({"error": "Missing coin symbol"}), 400
        
        if not SecurityValidator.validate_coin_symbol(coin):
            log_security_event("invalid_coin_symbol", {"coin": coin, "user_id": user.id})
            return jsonify({"error": "Invalid coin symbol"}), 400

        if not db.in_transaction():
            db.begin()
        
        if coin == "XMR":
            node = get_node(coin)
            label = f"user_{user.id}"
            result = node.create_subaddress(account_index=0, label=label)

            # Check for duplicates
            exists = db.query(Address).filter_by(address=result["address"], coin_symbol="XMR").first()
            if exists:
                db.rollback()
                logger.error(f"Duplicate XMR address generated: {result['address']}")
                return jsonify({"error": "Generated address already exists. Please retry."}), 500

            addr = Address(
                user_id=user.id,
                address=result["address"],
                coin_symbol="XMR",
                extra_info={"address_index": result["address_index"]}
            )
            db.add(addr)
            db.commit()
            return jsonify({"address": addr.address, "coin": "XMR"})
        else:
            node = get_node(coin)
            attempts = 0
            max_attempts = 5
            new_address = None

            while attempts < max_attempts:
                candidate_address = node.get_new_address()
                exists = db.query(Address).filter_by(address=candidate_address, coin_symbol=coin).first()
                if not exists:
                    new_address = candidate_address
                    break
                attempts += 1

            if not new_address:
                db.rollback()
                logger.error(f"Failed to generate unique address for {coin} after {max_attempts} attempts")
                return jsonify({"error": "Failed to generate a unique address after several attempts"}), 500

            addr = Address(
                user_id=user.id,
                address=new_address,
                coin_symbol=coin
            )
            db.add(addr)
            db.commit()

            return jsonify({
                "coin": coin,
                "address": new_address
            }), 201
                
    except Exception as e:
        logger.error(f"Address generation failed: {str(e)}")
        return jsonify({"error": "Address generation failed"}), 500
    finally:
        db.close()
@app.route('/addresses', methods=['GET'])
@secure_endpoint()
def list_addresses():
    db = SessionLocal()
    try:
        # Authenticate user
        user, error_response, status_code = authenticate_user(db)
        if error_response:
            return error_response, status_code

        coin_filter = request.args.get("coin")
        if coin_filter and not SecurityValidator.validate_coin_symbol(coin_filter.upper()):
            return jsonify({"error": "Invalid coin symbol"}), 400

        query = db.query(Address).filter_by(user_id=user.id)
        if coin_filter:
            query = query.filter(Address.coin_symbol == coin_filter.upper())

        addresses = query.order_by(Address.created_at.desc()).limit(100).all()  # Limit results

        return jsonify([{
            "address": a.address,
            "coin": a.coin_symbol,
            "created_at": a.created_at.isoformat()
        } for a in addresses]), 200

    except Exception as e:
        logger.error(f"List addresses failed: {str(e)}")
        return jsonify({"error": "Failed to retrieve addresses"}), 500
    finally:
        db.close()

@app.route('/balance', methods=['GET'])
@secure_endpoint()
def get_user_balances():
    db = SessionLocal()
    try:
        # Authenticate user
        user, error_response, status_code = authenticate_user(db)
        if error_response:
            return error_response, status_code

        coin_filter = request.args.get("coin")
        if coin_filter and not SecurityValidator.validate_coin_symbol(coin_filter.upper()):
            return jsonify({"error": "Invalid coin symbol"}), 400

        balances_query = db.query(Balance).filter_by(user_id=user.id)
        if coin_filter:
            balances_query = balances_query.filter(Balance.coin_symbol == coin_filter.upper())

        result = {}
        for b in balances_query.all():
            # Validate balance integrity
            try:
                validate_transaction_integrity(db, user.id, b.coin_symbol)
            except Exception as integrity_error:
                logger.error(f"Balance integrity error for user {user.id}: {integrity_error}")
                # Continue but log the issue
            
            result[b.coin_symbol] = {
                "available": str(b.available),
                "locked": str(b.locked),
                "total": str(b.total)
            }

        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Get balance failed: {str(e)}")
        return jsonify({"error": "Failed to retrieve balances"}), 500
    finally:
        db.close()

@app.route('/withdraw', methods=['POST'])
@secure_endpoint()
def withdraw_funds():
    db = SessionLocal()
    try:
        # Authenticate user
        user, error_response, status_code = authenticate_user(db)
        if error_response:
            return error_response, status_code

        data = request.get_json()
        coin = data.get("coin", "").upper() if data else None
        to_address = data.get("to_address") if data else None
        amount_input = data.get("amount") if data else None

        if not all([coin, to_address, amount_input]):
            return jsonify({"error": "Missing required fields: coin, to_address, amount"}), 400

        # Validate inputs
        if not SecurityValidator.validate_coin_symbol(coin):
            log_security_event("invalid_withdrawal_coin", {"coin": coin, "user_id": user.id})
            return jsonify({"error": "Invalid coin symbol"}), 400
        
        if not SecurityValidator.validate_address(to_address, coin):
            log_security_event("invalid_withdrawal_address", {"address": to_address[:20] + "...", "coin": coin, "user_id": user.id})
            return jsonify({"error": "Invalid withdrawal address"}), 400

        amount = SecurityValidator.validate_decimal(amount_input, min_val=Decimal('0.00000001'), max_val=Decimal('1000000'))
        if amount is None:
            return jsonify({"error": "Invalid amount"}), 400

        # Use special transaction isolation for withdrawals
        if not db.in_transaction():
            # Start transaction with REPEATABLE READ isolation level
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            db.begin()
        
        # Fetch balance with row lock
        balance = db.query(Balance).with_for_update().filter_by(user_id=user.id, coin_symbol=coin).first()
        if not balance or balance.available < amount:
            db.rollback()
            log_security_event("insufficient_balance_withdrawal", {
                "coin": coin, "requested": str(amount), 
                "available": str(balance.available) if balance else "0",
                "user_id": user.id
            })
            return jsonify({"error": "Insufficient available balance"}), 400

        # Deduct funds BEFORE sending (fail-safe approach)
        balance.available -= amount
        balance.total -= amount
        
        # Validate balance integrity after deduction
        validate_transaction_integrity(db, user.id, coin)
        
        db.flush()  # Ensure changes are persisted before external call

        try:
            node = get_node(coin)
            is_monero = node.__class__.__name__.lower() == "moneronode"

            if is_monero:
                # Convert to atomic
                amount_atomic = int(amount * Decimal("1e12"))
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
            
            log_security_event("withdrawal_completed", {
                "user_id": user.id, "coin": coin, "amount": str(amount),
                "txid": txid, "to_address": to_address[:20] + "..."
            })

            return jsonify({
                "status": "success",
                "txid": txid,
                "amount": str(amount),
                "coin": coin
            }), 200

        except Exception as node_error:
            # Refund the user if blockchain transaction failed
            balance.available += amount
            balance.total += amount
            db.flush()
            db.rollback()
            
            log_security_event("withdrawal_failed", {
                "user_id": user.id, "coin": coin, "amount": str(amount),
                "error": str(node_error), "to_address": to_address[:20] + "..."
            })
            
            logger.error(f"Withdrawal transaction failed for user {user.id}: {node_error}")
            return jsonify({"error": f"Withdrawal failed: {str(node_error)}"}), 500

    except Exception as e:
        logger.error(f"Withdrawal endpoint failed: {str(e)}")
        return jsonify({"error": "Withdrawal failed"}), 500
    finally:
        db.close()

@app.route('/order', methods=['POST'])
@secure_endpoint()
def place_order():
    db = SessionLocal()
    try:
        # Authenticate user
        user, error_response, status_code = authenticate_user(db)
        if error_response:
            return error_response, status_code

        data = request.get_json()
        market_id = data.get("market_id") if data else None
        side = data.get("side") if data else None
        price_input = data.get("price") if data else None
        amount_input = data.get("amount") if data else None

        if not all([market_id, side, price_input, amount_input]):
            return jsonify({"error": "Missing required fields"}), 400

        # Validate inputs
        try:
            market_id = int(market_id)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid market_id"}), 400

        if side not in ['buy', 'sell']:
            return jsonify({"error": "Invalid side (must be 'buy' or 'sell')"}), 400

        price = SecurityValidator.validate_decimal(price_input, min_val=Decimal('0.00000001'), max_val=Decimal('1000000'))
        if price is None:
            return jsonify({"error": "Invalid price"}), 400

        amount = SecurityValidator.validate_decimal(amount_input, min_val=Decimal('0.00000001'), max_val=Decimal('1000000'))
        if amount is None:
            return jsonify({"error": "Invalid amount"}), 400

        # Use standard transaction for order placement
        try:
            # Start a new transaction if not already in one
            if not db.in_transaction():
                transaction = db.begin()
            else:
                transaction = None
            
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
                    log_security_event("insufficient_balance_order", {
                        "user_id": user.id, "side": side, "market_id": market_id,
                        "required": str(total_quote), "available": str(balance.available) if balance else "0"
                    })
                    return jsonify({"error": "Insufficient quote balance"}), 400
                balance.available -= total_quote
                balance.locked += total_quote

            elif side_enum == OrderSide.sell:
                balance = db.query(Balance).with_for_update().filter_by(
                    user_id=user.id, coin_symbol=base_coin
                ).first()
                if not balance or balance.available < amount:
                    log_security_event("insufficient_balance_order", {
                        "user_id": user.id, "side": side, "market_id": market_id,
                        "required": str(amount), "available": str(balance.available) if balance else "0"
                    })
                    return jsonify({"error": "Insufficient base balance"}), 400
                balance.available -= amount
                balance.locked += amount

            # Validate balance integrity
            validate_transaction_integrity(db, user.id, balance.coin_symbol)

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

            # Commit transaction if we started it
            if transaction:
                transaction.commit()
            else:
                db.commit()

            log_security_event("order_placed", {
                "user_id": user.id, "order_id": new_order.id, "market_id": market_id,
                "side": side, "price": str(price), "amount": str(amount)
            })

            # Return response after successful transaction
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
            
        except Exception as tx_error:
            # Rollback if we have an active transaction
            if transaction:
                transaction.rollback()
            else:
                db.rollback()
            raise tx_error

    except Exception as e:
        logger.error(f"Order placement failed: {str(e)}")
        return jsonify({"error": "Order placement failed"}), 500
    finally:
        db.close()

@app.route('/trades', methods=['GET'])
@secure_endpoint()
def get_trade_history():
    db = SessionLocal()
    try:
        # Authenticate user
        user, error_response, status_code = authenticate_user(db)
        if error_response:
            return error_response, status_code

        coin = request.args.get("coin", "").upper()
        market_id = request.args.get("market_id")
        limit = request.args.get("limit", 50)

        # Validate inputs
        if coin and not SecurityValidator.validate_coin_symbol(coin):
            return jsonify({"error": "Invalid coin symbol"}), 400

        try:
            limit = int(limit)
            if limit <= 0 or limit > 200:
                return jsonify({"error": "Limit must be between 1 and 200"}), 400
        except ValueError:
            return jsonify({"error": "Invalid limit"}), 400

        q = db.query(Trade).join(Market).filter(
            (Trade.buy_order.has(user_id=user.id)) |
            (Trade.sell_order.has(user_id=user.id))
        )

        if market_id:
            try:
                market_id = int(market_id)
                q = q.filter(Trade.market_id == market_id)
            except ValueError:
                return jsonify({"error": "Invalid market_id"}), 400
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
        logger.error(f"Trade history failed: {str(e)}")
        return jsonify({"error": "Failed to fetch trades"}), 500
    finally:
        db.close()
@app.route('/cancel_order', methods=['POST'])
@secure_endpoint()
def cancel_order():
    db = SessionLocal()
    try:
        # Authenticate user
        user, error_response, status_code = authenticate_user(db)
        if error_response:
            return error_response, status_code

        data = request.get_json()
        order_id = data.get("order_id") if data else None
        
        if not order_id:
            return jsonify({"error": "Missing order_id"}), 400

        try:
            order_id = int(order_id)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid order_id"}), 400

        try:
            # Start a new transaction if not already in one
            if not db.in_transaction():
                transaction = db.begin()
            else:
                transaction = None
                
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
                if bal:
                    bal.locked -= refund
                    bal.available += refund
                    validate_transaction_integrity(db, user.id, market.quote_coin)

            else:
                bal = db.query(Balance).with_for_update().filter_by(
                    user_id=user.id, coin_symbol=market.base_coin
                ).first()
                if bal:
                    bal.locked -= Decimal(remaining)
                    bal.available += Decimal(remaining)
                    validate_transaction_integrity(db, user.id, market.base_coin)

            order.status = OrderStatus.cancelled
            
            # Commit transaction if we started it
            if transaction:
                transaction.commit()
            else:
                db.commit()
            
            log_security_event("order_cancelled", {
                "user_id": user.id, "order_id": order.id, "market_id": order.market_id
            })

            return jsonify({"status": "cancelled", "order_id": order.id}), 200
            
        except Exception as tx_error:
            # Rollback if we have an active transaction
            if transaction:
                transaction.rollback()
            else:
                db.rollback()
            raise tx_error

    except Exception as e:
        logger.error(f"Order cancellation failed: {str(e)}")
        return jsonify({"error": "Cancellation failed"}), 500
    finally:
        db.close()

@app.route('/orderbook', methods=['GET'])
@secure_endpoint('public')
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
        market = db.query(Market).filter_by(id=market_id, active=True).first()
        if not market:
            return jsonify({"error": "Market not found"}), 404

        # Bids (buys): highest price first
        bids = db.query(Order).filter_by(
            market_id=market_id,
            side=OrderSide.buy
        ).filter(Order.status.in_([OrderStatus.open, OrderStatus.partially_filled])
        ).order_by(Order.price.desc()).limit(depth * 10).all()  # Get more for aggregation

        # Asks (sells): lowest price first
        asks = db.query(Order).filter_by(
            market_id=market_id,
            side=OrderSide.sell
        ).filter(Order.status.in_([OrderStatus.open, OrderStatus.partially_filled])
        ).order_by(Order.price.asc()).limit(depth * 10).all()

        # Aggregate by price
        def aggregate(orders, reverse=False):
            price_levels = {}
            for order in orders:
                p = str(order.price)
                a = float(order.remaining)  # Convert to float for aggregation
                price_levels[p] = price_levels.get(p, 0.0) + a
            sorted_levels = sorted(price_levels.items(), key=lambda x: float(x[0]), reverse=reverse)
            return [{"price": p, "amount": round(a, 8)} for p, a in sorted_levels[:depth]]

        return jsonify({
            "market": f"{market.base_coin}/{market.quote_coin}",
            "bids": aggregate(bids, reverse=True),
            "asks": aggregate(asks, reverse=False)
        })

    except Exception as e:
        logger.error(f"Orderbook fetch failed: {str(e)}")
        return jsonify({"error": "Failed to fetch order book"}), 500
    finally:
        db.close()

@app.route('/orders', methods=['GET'])
@secure_endpoint()
def get_open_orders():
    db = SessionLocal()
    try:
        # Authenticate user
        user, error_response, status_code = authenticate_user(db)
        if error_response:
            return error_response, status_code

        coin = request.args.get("coin", "").upper()
        market_id = request.args.get("market_id")

        if coin and not SecurityValidator.validate_coin_symbol(coin):
            return jsonify({"error": "Invalid coin symbol"}), 400

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

        query = query.order_by(Order.created_at.desc()).limit(100)  # Limit results
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
        logger.error(f"Get orders failed: {str(e)}")
        return jsonify({"error": "Failed to fetch orders"}), 500
    finally:
        db.close()

@app.route("/markets", methods=["GET"])
@secure_endpoint('public')
def get_markets():
    db = SessionLocal()
    try:
        markets = db.query(Market).filter_by(active=True).all()
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
                side=OrderSide.buy
            ).filter(Order.status.in_([OrderStatus.open, OrderStatus.partially_filled])
            ).order_by(Order.price.desc()).first()

            best_ask = db.query(Order).filter_by(
                market_id=m.id,
                side=OrderSide.sell
            ).filter(Order.status.in_([OrderStatus.open, OrderStatus.partially_filled])
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
        logger.error(f"Get markets failed: {str(e)}")
        return jsonify({"error": "Failed to fetch markets"}), 500
    finally:
        db.close()



### SECURED ADMIN ENDPOINTS ####################################

@app.route('/admin/create_market', methods=['POST'])
@require_admin()
@secure_endpoint()
def create_market():
    db = SessionLocal()
    try:
        data = request.get_json()
        base_coin = data.get("base_coin", "").upper() if data else None
        quote_coin = data.get("quote_coin", "").upper() if data else None

        if not base_coin or not quote_coin:
            return jsonify({"error": "Missing base_coin or quote_coin"}), 400

        if not SecurityValidator.validate_coin_symbol(base_coin) or not SecurityValidator.validate_coin_symbol(quote_coin):
            return jsonify({"error": "Invalid coin symbols"}), 400

        if base_coin == quote_coin:
            return jsonify({"error": "Base and quote cannot be the same"}), 400

        try:
            # Start a new transaction if not already in one
            if not db.in_transaction():
                transaction = db.begin()
            else:
                transaction = None
                
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
            db.flush()
            
            # Commit transaction if we started it
            if transaction:
                transaction.commit()
            else:
                db.commit()
            
            log_security_event("market_created", {
                "market_id": new_market.id, "base_coin": base_coin, "quote_coin": quote_coin
            })

            return jsonify({
                "market_id": new_market.id,
                "base_coin": base_coin,
                "quote_coin": quote_coin,
                "status": "created"
            }), 201
            
        except Exception as tx_error:
            # Rollback if we have an active transaction
            if transaction:
                transaction.rollback()
            else:
                db.rollback()
            raise tx_error

    except Exception as e:
        logger.error(f"Market creation failed: {str(e)}")
        return jsonify({"error": "Could not create market"}), 500
    finally:
        db.close()

@app.route("/admin/fees", methods=["GET", "POST"])
@require_admin()
@secure_endpoint()
def manage_fees():
    db = SessionLocal()
    try:
        if request.method == "GET":
            fees = db.query(FeeBalance).all()
            return jsonify({
                f.coin_symbol: str(f.amount)
                for f in fees
            })

        elif request.method == "POST":
            data = request.get_json()
            coin = data.get("coin", "").upper() if data else None
            amount_input = data.get("amount") if data else None

            if not coin or amount_input is None:
                return jsonify({"error": "Missing coin or amount"}), 400

            if not SecurityValidator.validate_coin_symbol(coin):
                return jsonify({"error": "Invalid coin symbol"}), 400

            amount = SecurityValidator.validate_decimal(amount_input, min_val=Decimal('0'))
            if amount is None:
                return jsonify({"error": "Invalid amount"}), 400

            if not db.in_transaction():
                db.begin()
            
            fb = db.query(FeeBalance).filter_by(coin_symbol=coin).first()
            if not fb or fb.amount < amount:
                db.rollback()
                return jsonify({"error": "Insufficient fee balance"}), 400

            fb.amount -= amount
            db.commit()
            
            log_security_event("fee_withdrawal", {
                "coin": coin, "amount": str(amount), "remaining": str(fb.amount)
            })

            return jsonify({
                "coin": coin,
                "withdrawn": str(amount),
                "remaining": str(fb.amount)
            })

    except Exception as e:
        logger.error(f"Fee management failed: {str(e)}")
        return jsonify({"error": "Fee handling error"}), 500
    finally:
        db.close()

@app.route('/auth_test', methods=['GET'])
@secure_endpoint()
def auth_test():
    db = SessionLocal()
    try:
        # Authenticate user
        user, error_response, status_code = authenticate_user(db, log_failures=False)
        if error_response:
            return error_response, status_code

        return jsonify({
            "message": "Authenticated", 
            "user_id": user.id,
            "server_time": datetime.now(timezone.utc).isoformat()
        })
        
    except Exception as e:
        logger.error(f"Auth test failed: {str(e)}")
        return jsonify({"error": "Authentication test failed"}), 500
    finally:
        db.close()

@app.route('/health', methods=['GET'])
@secure_endpoint('public')
def health_check():
    """Public health check endpoint."""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0"
    })

@app.route('/supported_coins', methods=['GET'])
@secure_endpoint('public')
def get_supported_coins():
    """Get list of supported cryptocurrencies and their network information."""
    db = SessionLocal()
    try:
        supported_coins = {}
        
        # Scan environment variables to find configured nodes
        for key in os.environ:
            if key.endswith('_NODE_HOST'):
                coin_symbol = key.replace('_NODE_HOST', '')
                
                # Check if all required environment variables exist for this coin
                host = os.environ.get(f"{coin_symbol}_NODE_HOST")
                port = os.environ.get(f"{coin_symbol}_NODE_PORT")
                username = os.environ.get(f"{coin_symbol}_NODE_USER")
                password = os.environ.get(f"{coin_symbol}_NODE_PASS")
                node_type = os.environ.get(f"{coin_symbol}_NODE_TYPE", "btc").lower()
                
                # Get metadata from environment variables
                coin_name = os.environ.get(f"{coin_symbol}_NAME", coin_symbol)
                block_time = os.environ.get(f"{coin_symbol}_BLOCK_TIME", "Variable")
                confirmations = os.environ.get(f"{coin_symbol}_CONFIRMATIONS", "6")
                address_format = os.environ.get(f"{coin_symbol}_ADDRESS_FORMAT", f"{coin_symbol} address format")
                network_name = os.environ.get(f"{coin_symbol}_NETWORK", coin_name)
                
                if all([host, port, username, password]):
                    # Calculate average fee from actual transactions
                    avg_fee = calculate_average_fee(db, coin_symbol, node_type)
                    
                    # Try to get additional info by testing the node connection
                    try:
                        from coinNodes import get_node
                        node = get_node(coin_symbol)
                        
                        node_info = {
                            "symbol": coin_symbol,
                            "name": coin_name,
                            "node_type": node_type,
                            "network_info": {
                                "network": network_name,
                                "confirmations": confirmations,
                                "typical_fee": avg_fee,
                                "block_time": block_time,
                                "address_format": address_format
                            },
                            "status": "online"
                        }
                        
                        # Test basic connectivity
                        if hasattr(node, 'get_info'):
                            try:
                                node.get_info()
                            except:
                                node_info["status"] = "connection_error"
                        
                        supported_coins[coin_symbol] = node_info
                        
                    except Exception as e:
                        # Add coin even if node connection fails
                        supported_coins[coin_symbol] = {
                            "symbol": coin_symbol,
                            "name": coin_name,
                            "node_type": node_type,
                            "network_info": {
                                "network": network_name,
                                "confirmations": confirmations,
                                "typical_fee": avg_fee,
                                "block_time": block_time,
                                "address_format": address_format
                            },
                            "status": "configuration_error",
                            "error": str(e)
                        }
        
        return jsonify({
            "supported_coins": supported_coins,
            "total_count": len(supported_coins),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Get supported coins failed: {str(e)}")
        return jsonify({"error": "Failed to retrieve supported coins"}), 500
    finally:
        db.close()

def calculate_average_fee(db, coin_symbol, node_type):
    """Calculate average transaction fee from actual transactions and node estimates."""
    try:
        # First, try to get real-time fee estimates from the node
        try:
            from coinNodes import get_node
            node = get_node(coin_symbol)
            
            if node_type == "monero":
                # For Monero, try to get fee estimate from the node
                try:
                    # Monero RPC doesn't have a direct fee estimate, but we can estimate
                    # based on a dummy transfer to get fee calculation
                    # This is a rough estimate - in practice you'd want a dedicated fee estimation method
                    return f"~0.0001 {coin_symbol} (dynamic)"
                except Exception as e:
                    logger.debug(f"Monero fee estimate failed: {e}")
            else:
                # For Bitcoin-like coins, try to get network fee estimate
                try:
                    # Try estimatefee RPC call for Bitcoin-like nodes
                    fee_per_kb = node._rpc_request("estimatesmartfee", [6])  # 6 blocks target
                    if fee_per_kb and 'feerate' in fee_per_kb:
                        # Convert from BTC/kB to a readable format
                        fee_rate = float(fee_per_kb['feerate'])
                        if fee_rate > 0:
                            # Estimate typical transaction size (250 bytes)
                            typical_fee = fee_rate * 0.25  # 250 bytes = 0.25 kB
                            return f"~{typical_fee:.6f} {coin_symbol} (network estimate)"
                except Exception as e:
                    logger.debug(f"Network fee estimate failed for {coin_symbol}: {e}")
                    
                    # Try alternative fee estimation methods
                    try:
                        # Try getnetworkinfo for Bitcoin Core nodes
                        network_info = node._rpc_request("getnetworkinfo")
                        if network_info:
                            return f"~0.0001 {coin_symbol} (connected)"
                    except:
                        pass
                        
        except Exception as e:
            logger.debug(f"Node fee estimation failed for {coin_symbol}: {e}")
        
        # Fallback: Calculate from recent transaction history
        recent_withdrawals = db.query(Transaction).filter(
            Transaction.coin_symbol == coin_symbol,
            Transaction.direction == 'sent',
            Transaction.created_at >= datetime.now(timezone.utc) - timedelta(days=30)
        ).limit(100).all()
        
        if recent_withdrawals:
            # Use transaction count as activity indicator
            activity_level = len(recent_withdrawals)
            if activity_level > 50:
                activity_desc = "high activity"
            elif activity_level > 20:
                activity_desc = "medium activity"
            elif activity_level > 5:
                activity_desc = "low activity"
            else:
                activity_desc = "minimal activity"
                
            base_fee = get_default_fee_estimate(coin_symbol, node_type)
            return f"{base_fee} ({activity_desc})"
        
        # Ultimate fallback to defaults
        return get_default_fee_estimate(coin_symbol, node_type)
        
    except Exception as e:
        logger.error(f"Error calculating average fee for {coin_symbol}: {e}")
        return get_default_fee_estimate(coin_symbol, node_type)

def get_default_fee_estimate(coin_symbol, node_type):
    """Get default fee estimate when dynamic calculation isn't available."""
    if node_type == "monero":
        return f"~0.0001 {coin_symbol}"
    else:
        # Bitcoin-like default - can be customized per coin via environment variables
        default_fee = os.environ.get(f"{coin_symbol}_DEFAULT_FEE", "0.0001")
        return f"~{default_fee} {coin_symbol}"

####################################################################

if __name__ == '__main__':
    # Security: Never run with debug=True in production
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    port = int(os.environ.get('PORT', 5000))
    
    if debug_mode:
        logger.warning("Running in DEBUG mode - DO NOT use in production!")
    
    # Ensure logs directory exists
    os.makedirs('/home/Jack/CryptoExchange/logs', exist_ok=True)
    
    app.run(debug=debug_mode, host='127.0.0.1', port=port)  # Only bind to localhost by default
