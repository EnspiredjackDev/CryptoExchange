from datetime import datetime, timezone
from decimal import Decimal
import logging
import os
from flask import Flask, request, jsonify, g
from db import SessionLocal
from security import (
    secure_endpoint, require_admin, authenticate_user, SecurityValidator, 
    log_security_event, SecurityConfig
)
from services import (
    UserService, OrderService, WithdrawalService, MarketService, 
    AdminService, CoinNodeService
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
        raw_key, user_id = UserService.create_account(db)
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
        
        result = UserService.generate_address(db, user.id, coin)
        return jsonify(result), 201
                
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
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
        addresses = UserService.list_addresses(db, user.id, coin_filter)
        return jsonify(addresses), 200

    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
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
        result = UserService.get_balances(db, user.id, coin_filter)
        return jsonify(result), 200

    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
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

        amount = SecurityValidator.validate_decimal(amount_input, min_val=Decimal('0.00000001'), max_val=Decimal('1000000'))
        if amount is None:
            return jsonify({"error": "Invalid amount"}), 400

        result = WithdrawalService.withdraw(db, user.id, coin, to_address, amount)
        return jsonify(result), 200

    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
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

        price = SecurityValidator.validate_decimal(price_input, min_val=Decimal('0.00000001'), max_val=Decimal('1000000'))
        if price is None:
            return jsonify({"error": "Invalid price"}), 400

        amount = SecurityValidator.validate_decimal(amount_input, min_val=Decimal('0.00000001'), max_val=Decimal('1000000'))
        if amount is None:
            return jsonify({"error": "Invalid amount"}), 400

        result = OrderService.place_order(db, user.id, market_id, side, price, amount)
        return jsonify(result), 201

    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
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

        # Validate limit
        try:
            limit = int(limit)
        except ValueError:
            return jsonify({"error": "Invalid limit"}), 400

        # Convert market_id to int if provided
        if market_id:
            try:
                market_id = int(market_id)
            except ValueError:
                return jsonify({"error": "Invalid market_id"}), 400

        trades = MarketService.get_trade_history(
            db, 
            user.id, 
            coin_filter=coin if coin else None,
            market_id=market_id,
            limit=limit
        )
        return jsonify(trades)

    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
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

        result = OrderService.cancel_order(db, user.id, order_id)
        return jsonify(result), 200

    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
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

    db = SessionLocal()
    try:
        result = MarketService.get_orderbook(db, market_id, depth)
        return jsonify(result)

    except ValueError as ve:
        return jsonify({"error": str(ve)}), 404 if "not found" in str(ve).lower() else 400
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

        # Convert market_id to int if provided
        if market_id:
            try:
                market_id = int(market_id)
            except ValueError:
                return jsonify({"error": "Invalid market_id"}), 400

        orders = OrderService.get_open_orders(
            db,
            user.id,
            coin_filter=coin if coin else None,
            market_id=market_id
        )
        return jsonify(orders)
        
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
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
        result = MarketService.get_markets(db)
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

        result = AdminService.create_market(db, base_coin, quote_coin)
        return jsonify(result), 201

    except ValueError as ve:
        # Check if it's a duplicate market error
        if "already exists" in str(ve):
            error_msg = str(ve)
            # Extract market_id if present
            import re
            match = re.search(r'ID: (\d+)', error_msg)
            if match:
                market_id = int(match.group(1))
                return jsonify({"error": "Market already exists", "market_id": market_id}), 409
        return jsonify({"error": str(ve)}), 400
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
            result = AdminService.get_fee_balances(db)
            return jsonify(result)

        elif request.method == "POST":
            data = request.get_json()
            coin = data.get("coin", "").upper() if data else None
            amount_input = data.get("amount") if data else None

            if not coin or amount_input is None:
                return jsonify({"error": "Missing coin or amount"}), 400

            amount = SecurityValidator.validate_decimal(amount_input, min_val=Decimal('0'))
            if amount is None:
                return jsonify({"error": "Invalid amount"}), 400

            result = AdminService.withdraw_fees(db, coin, amount)
            return jsonify(result)

    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Fee management failed: {str(e)}")
        return jsonify({"error": "Fee handling error"}), 500
    finally:
        db.close()

### COIN NODE MANAGEMENT ENDPOINTS ####################################

@app.route('/admin/coin_nodes', methods=['GET'])
@require_admin()
@secure_endpoint()
def list_coin_nodes():
    """List all coin node configurations."""
    db = SessionLocal()
    try:
        include_disabled = request.args.get('include_disabled', 'false').lower() == 'true'
        nodes = CoinNodeService.list_coin_nodes(db, include_disabled=include_disabled)
        return jsonify(nodes), 200
        
    except Exception as e:
        logger.error(f"List coin nodes failed: {str(e)}")
        return jsonify({"error": "Failed to list coin nodes"}), 500
    finally:
        db.close()


@app.route('/admin/coin_nodes/<coin_symbol>', methods=['GET'])
@require_admin()
@secure_endpoint()
def get_coin_node(coin_symbol):
    """Get a specific coin node configuration."""
    db = SessionLocal()
    try:
        node = CoinNodeService.get_coin_node(db, coin_symbol)
        return jsonify(node), 200
        
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 404
    except Exception as e:
        logger.error(f"Get coin node failed: {str(e)}")
        return jsonify({"error": "Failed to get coin node"}), 500
    finally:
        db.close()


@app.route('/admin/coin_nodes', methods=['POST'])
@require_admin()
@secure_endpoint()
def add_coin_node():
    """Add a new coin node configuration."""
    db = SessionLocal()
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "Missing request body"}), 400
        
        # Required fields
        required_fields = ['coin_symbol', 'coin_name', 'node_host', 'node_port', 
                          'node_user', 'node_pass', 'node_type']
        missing = [f for f in required_fields if f not in data]
        if missing:
            return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400
        
        # Validate port
        try:
            node_port = int(data['node_port'])
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid node_port"}), 400
        
        # Optional fields with defaults
        confirmations = data.get('confirmations', 6)
        try:
            confirmations = int(confirmations)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid confirmations"}), 400
        
        result = CoinNodeService.add_coin_node(
            db,
            coin_symbol=data['coin_symbol'],
            coin_name=data['coin_name'],
            node_host=data['node_host'],
            node_port=node_port,
            node_user=data['node_user'],
            node_pass=data['node_pass'],
            node_type=data['node_type'],
            network_name=data.get('network_name'),
            block_time=data.get('block_time'),
            confirmations=confirmations,
            address_format=data.get('address_format'),
            default_fee=data.get('default_fee')
        )
        
        return jsonify(result), 201
        
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Add coin node failed: {str(e)}")
        return jsonify({"error": "Failed to add coin node"}), 500
    finally:
        db.close()


@app.route('/admin/coin_nodes/<coin_symbol>', methods=['PUT', 'PATCH'])
@require_admin()
@secure_endpoint()
def update_coin_node(coin_symbol):
    """Update an existing coin node configuration."""
    db = SessionLocal()
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "Missing request body"}), 400
        
        # Validate port if provided
        if 'node_port' in data:
            try:
                data['node_port'] = int(data['node_port'])
            except (ValueError, TypeError):
                return jsonify({"error": "Invalid node_port"}), 400
        
        # Validate confirmations if provided
        if 'confirmations' in data:
            try:
                data['confirmations'] = int(data['confirmations'])
            except (ValueError, TypeError):
                return jsonify({"error": "Invalid confirmations"}), 400
        
        result = CoinNodeService.update_coin_node(db, coin_symbol, **data)
        return jsonify(result), 200
        
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 404 if "not found" in str(ve).lower() else 400
    except Exception as e:
        logger.error(f"Update coin node failed: {str(e)}")
        return jsonify({"error": "Failed to update coin node"}), 500
    finally:
        db.close()


@app.route('/admin/coin_nodes/<coin_symbol>', methods=['DELETE'])
@require_admin()
@secure_endpoint()
def delete_coin_node(coin_symbol):
    """Delete a coin node configuration."""
    db = SessionLocal()
    try:
        result = CoinNodeService.delete_coin_node(db, coin_symbol)
        return jsonify(result), 200
        
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 404
    except Exception as e:
        logger.error(f"Delete coin node failed: {str(e)}")
        return jsonify({"error": "Failed to delete coin node"}), 500
    finally:
        db.close()


@app.route('/admin/coin_nodes/<coin_symbol>/enable', methods=['POST'])
@require_admin()
@secure_endpoint()
def enable_coin_node(coin_symbol):
    """Enable a coin node."""
    db = SessionLocal()
    try:
        result = CoinNodeService.enable_coin_node(db, coin_symbol)
        return jsonify(result), 200
        
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 404
    except Exception as e:
        logger.error(f"Enable coin node failed: {str(e)}")
        return jsonify({"error": "Failed to enable coin node"}), 500
    finally:
        db.close()


@app.route('/admin/coin_nodes/<coin_symbol>/disable', methods=['POST'])
@require_admin()
@secure_endpoint()
def disable_coin_node(coin_symbol):
    """Disable a coin node."""
    db = SessionLocal()
    try:
        result = CoinNodeService.disable_coin_node(db, coin_symbol)
        return jsonify(result), 200
        
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 404
    except Exception as e:
        logger.error(f"Disable coin node failed: {str(e)}")
        return jsonify({"error": "Failed to disable coin node"}), 500
    finally:
        db.close()


@app.route('/admin/coin_nodes/<coin_symbol>/test', methods=['POST'])
@require_admin()
@secure_endpoint()
def test_coin_node(coin_symbol):
    """Test connection to a coin node."""
    db = SessionLocal()
    try:
        result = CoinNodeService.test_coin_node(db, coin_symbol)
        status_code = 200 if result.get('status') == 'connected' else 500
        return jsonify(result), status_code
        
    except Exception as e:
        logger.error(f"Test coin node failed: {str(e)}")
        return jsonify({"error": "Failed to test coin node"}), 500
    finally:
        db.close()

####################################################################

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
        result = MarketService.get_supported_coins(db)
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Get supported coins failed: {str(e)}")
        return jsonify({"error": "Failed to retrieve supported coins"}), 500
    finally:
        db.close()

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
