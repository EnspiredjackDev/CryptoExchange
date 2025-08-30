import os
import requests
from decimal import Decimal
from flask import Flask, render_template, request, redirect, url_for, session, flash
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('UI_SECRET_KEY', 'change-this-in-production-ui-key')

# Configuration
EXCHANGE_API_URL = os.environ.get('EXCHANGE_API_URL', 'http://127.0.0.1:5000')
UI_PORT = int(os.environ.get('UI_PORT', 5001))
ADMIN_ACCESS_KEY = os.environ.get('ADMIN_ACCESS_KEY', 'change-this-in-production-admin-key')

# Security headers
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline'"
    return response

def make_api_request(endpoint, method='GET', data=None, auth_required=True, admin_required=False):
    """Make request to exchange API with proper error handling."""
    try:
        headers = {}
        if auth_required and 'api_key' in session:
            headers['Authorization'] = f"Bearer {session['api_key']}"
        
        # Add admin key header for admin endpoints
        if admin_required and 'api_key' in session:
            headers['X-Admin-Key'] = session['admin_api_key']
        
        url = f"{EXCHANGE_API_URL}{endpoint}"
        
        if method == 'GET':
            response = requests.get(url, headers=headers, params=data, timeout=10)
        elif method == 'POST':
            headers['Content-Type'] = 'application/json'
            response = requests.post(url, headers=headers, json=data, timeout=10)
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        return response.json(), response.status_code
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        return {"error": "Connection to exchange failed"}, 500

def format_number(value, decimals=8):
    """Format number for display."""
    if value is None:
        return "0"
    try:
        # Convert to Decimal for precise arithmetic
        if isinstance(value, str):
            if not value or value.strip() == "":
                return "0"
            value = Decimal(value)
        elif isinstance(value, float):
            value = Decimal(str(value))
        elif not isinstance(value, Decimal):
            value = Decimal(str(value))
        
        # Handle zero or very small numbers
        if value == 0:
            return "0"
        
        # Format with specified decimals
        formatted = f"{value:.{decimals}f}"
        
        # Remove trailing zeros but keep at least one decimal place for small numbers
        if '.' in formatted:
            formatted = formatted.rstrip('0')
            if formatted.endswith('.'):
                formatted = formatted[:-1]
        
        return formatted if formatted and formatted != "" else "0"
    except Exception as e:
        logger.warning(f"format_number failed for value '{value}': {e}")
        return str(value) if value is not None else "0"

def calculate_total(price, amount, decimals=8):
    """Calculate total (price * amount) and format for display."""
    try:
        # Handle None or empty values
        if price is None or amount is None:
            return "0"
        
        # Convert to Decimal for precise arithmetic
        if isinstance(price, str):
            if not price or price.strip() == "":
                return "0"
            price = Decimal(price.strip())
        elif isinstance(price, (int, float)):
            price = Decimal(str(price))
        elif not isinstance(price, Decimal):
            price = Decimal(str(price))
            
        if isinstance(amount, str):
            if not amount or amount.strip() == "":
                return "0"
            amount = Decimal(amount.strip())
        elif isinstance(amount, (int, float)):
            amount = Decimal(str(amount))
        elif not isinstance(amount, Decimal):
            amount = Decimal(str(amount))
        
        # Calculate total
        total = price * amount
        result = format_number(total, decimals)
        
        # Debug logging for problematic cases
        if result == "0" and (price != 0 and amount != 0):
            logger.warning(f"calculate_total unexpected result: {price} * {amount} = {total} -> '{result}'")
        
        return result
    except Exception as e:
        logger.warning(f"calculate_total failed for price='{price}', amount='{amount}': {e}")
        return "0"

def get_supported_coins():
    """Get supported cryptocurrencies from the API."""
    try:
        response, status = make_api_request('/supported_coins', auth_required=False)
        if status == 200:
            return response.get('supported_coins', {})
        else:
            logger.warning(f"Failed to get supported coins: {response}")
            return {}
    except Exception as e:
        logger.error(f"Error getting supported coins: {e}")
        return {}

def is_admin():
    """Check if current session has admin access."""
    return session.get('admin_access') == True

# Add global template functions
app.jinja_env.globals.update(format_number=format_number)
app.jinja_env.globals.update(calculate_total=calculate_total)

@app.route('/')
def index():
    """Main exchange page."""
    # Get markets data
    markets_data, status = make_api_request('/markets', auth_required=False)
    markets = markets_data if status == 200 else []
    
    # Get orderbook for first market if available
    orderbook = {}
    if markets:
        first_market = markets[0]
        orderbook_data, status = make_api_request(f'/orderbook?market_id={first_market["market_id"]}&depth=15', auth_required=False)
        if status == 200:
            orderbook = orderbook_data
    
    return render_template('index.html', markets=markets, orderbook=orderbook, format_number=format_number, calculate_total=calculate_total)

@app.route('/market/<int:market_id>')
def market_view(market_id):
    """Individual market view."""
    # Get market orderbook
    orderbook_data, status = make_api_request(f'/orderbook?market_id={market_id}&depth=20', auth_required=False)
    orderbook = orderbook_data if status == 200 else {}
    
    # Get markets for navigation
    markets_data, status = make_api_request('/markets', auth_required=False)
    markets = markets_data if status == 200 else []
    
    # Find current market info
    current_market = None
    for market in markets:
        if market['market_id'] == market_id:
            current_market = market
            break
    
    if not current_market:
        flash('Market not found', 'error')
        return redirect(url_for('index'))
    
    # Get user orders if logged in
    user_orders = []
    if 'api_key' in session:
        orders_data, status = make_api_request(f'/orders?market_id={market_id}')
        if status == 200:
            user_orders = orders_data
    
    return render_template('market.html', 
                         current_market=current_market,
                         markets=markets, 
                         orderbook=orderbook, 
                         user_orders=user_orders,
                         format_number=format_number,
                         calculate_total=calculate_total)

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page."""
    if request.method == 'POST':
        api_key = request.form.get('api_key', '').strip()
        
        if not api_key:
            flash('Please enter your API key', 'error')
            return render_template('login.html')
        
        # Test the API key
        session['api_key'] = api_key
        test_data, status = make_api_request('/auth_test')
        
        if status == 200:
            flash('Successfully logged in', 'success')
            return redirect(url_for('account'))
        else:
            session.pop('api_key', None)
            flash('Invalid API key', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Registration page."""
    if request.method == 'POST':
        # Create new account
        data, status = make_api_request('/create_account', data={}, method='POST', auth_required=False)  # data={} required as will fail on backend if not there

        if status == 201:
            api_key = data.get('api_key')
            flash(f'Account created! Save this API key: {api_key}', 'success')
            session['api_key'] = api_key
            return redirect(url_for('account'))
        else:
            flash('Account creation failed', 'error')
    
    return render_template('register.html')

@app.route('/account')
def account():
    """Account overview page."""
    if 'api_key' not in session:
        return redirect(url_for('login'))
    
    # Get balances
    balances_data, status = make_api_request('/balance')
    balances = balances_data if status == 200 else {}
    
    # Get recent trades
    trades_data, status = make_api_request('/trades?limit=20')
    trades = trades_data if status == 200 else []
    
    # Get open orders
    orders_data, status = make_api_request('/orders')
    orders = orders_data if status == 200 else []
    
    # Get addresses
    addresses_data, status = make_api_request('/addresses')
    addresses = addresses_data if status == 200 else []
    
    # Get supported coins
    supported_coins = get_supported_coins()
    
    return render_template('account.html', 
                         balances=balances, 
                         trades=trades, 
                         orders=orders,
                         addresses=addresses,
                         supported_coins=supported_coins,
                         format_number=format_number,
                         calculate_total=calculate_total)

@app.route('/trade/<int:market_id>', methods=['GET', 'POST'])
def trade(market_id):
    """Trading page for specific market."""
    if 'api_key' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        side = request.form.get('side')
        price = request.form.get('price')
        amount = request.form.get('amount')
        
        if not all([side, price, amount]):
            flash('All fields are required', 'error')
        else:
            data = {
                'market_id': market_id,
                'side': side,
                'price': price,
                'amount': amount
            }
            
            result, status = make_api_request('/order', method='POST', data=data)
            
            if status == 201:
                flash(f'Order placed successfully! Order ID: {result.get("order_id")}', 'success')
            else:
                flash(f'Order failed: {result.get("error", "Unknown error")}', 'error')
    
    return redirect(url_for('market_view', market_id=market_id))

@app.route('/cancel_order', methods=['POST'])
def cancel_order():
    """Cancel an order."""
    if 'api_key' not in session:
        return redirect(url_for('login'))
    
    order_id = request.form.get('order_id')
    if not order_id:
        flash('Order ID required', 'error')
        return redirect(url_for('account'))
    
    data = {'order_id': int(order_id)}
    result, status = make_api_request('/cancel_order', method='POST', data=data)
    
    if status == 200:
        flash('Order cancelled successfully', 'success')
    else:
        flash(f'Cancel failed: {result.get("error", "Unknown error")}', 'error')
    
    return redirect(url_for('account'))

@app.route('/generate_address', methods=['POST'])
def generate_address():
    """Generate a new deposit address."""
    if 'api_key' not in session:
        return redirect(url_for('login'))
    
    coin = request.form.get('coin', '').upper()
    if not coin:
        flash('Coin symbol required', 'error')
        return redirect(url_for('account'))
    
    data = {'coin': coin}
    result, status = make_api_request('/generate_address', method='POST', data=data)
    
    if status == 201:
        flash(f'New {coin} address generated: {result.get("address")}', 'success')
    else:
        flash(f'Address generation failed: {result.get("error", "Unknown error")}', 'error')
    
    return redirect(url_for('account'))

@app.route('/withdraw', methods=['GET', 'POST'])
def withdraw():
    """Withdrawal page."""
    if 'api_key' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        coin = request.form.get('coin', '').upper()
        to_address = request.form.get('to_address', '').strip()
        amount = request.form.get('amount', '').strip()
        
        if not all([coin, to_address, amount]):
            flash('All fields are required', 'error')
        else:
            data = {
                'coin': coin,
                'to_address': to_address,
                'amount': amount
            }
            
            result, status = make_api_request('/withdraw', method='POST', data=data)
            
            if status == 200:
                flash(f'Withdrawal successful! TXID: {result.get("txid")}', 'success')
                return redirect(url_for('account'))
            else:
                flash(f'Withdrawal failed: {result.get("error", "Unknown error")}', 'error')
    
    # Get balances for withdrawal form
    balances_data, status = make_api_request('/balance')
    balances = balances_data if status == 200 else {}
    
    # Get supported coins
    supported_coins = get_supported_coins()
    
    return render_template('withdraw.html', 
                         balances=balances, 
                         supported_coins=supported_coins,
                         format_number=format_number)

@app.route('/logout')
def logout():
    """Logout user."""
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('index'))

@app.route('/coins')
def coins_info():
    """Supported coins information page."""
    supported_coins = get_supported_coins()
    
    # Get markets to show trading pairs
    markets_data, status = make_api_request('/markets', auth_required=False)
    markets = markets_data if status == 200 else []
    
    return render_template('coins.html', 
                         supported_coins=supported_coins,
                         markets=markets,
                         format_number=format_number)

# Admin routes (hidden, only accessible via direct URL)
@app.route('/admin')
def admin_login():
    """Admin login page."""
    return render_template('admin/login.html')

@app.route('/admin/help')
def admin_help():
    """Admin help and setup guide."""
    return render_template('admin/help.html')

@app.route('/admin/auth', methods=['POST'])
def admin_auth():
    """Admin authentication."""
    access_key = request.form.get('access_key', '').strip()
    
    if access_key == ADMIN_ACCESS_KEY:
        session['admin_access'] = True
        session['admin_api_key'] = access_key
        flash('Admin access granted', 'success')
        return redirect(url_for('admin_dashboard'))
    else:
        flash('Invalid access key', 'error')
        return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
def admin_dashboard():
    """Admin dashboard."""
    if not is_admin():
        return redirect(url_for('admin_login'))
    
    # Get markets (public endpoint)
    markets_data, status = make_api_request('/markets', auth_required=False)
    markets = markets_data if status == 200 else []
    
    # Get fee balances - only works if user has API key AND admin access
    fees_data = {}
    fee_error = None
    if 'api_key' in session:
        fees_result, status = make_api_request('/admin/fees', admin_required=True)
        if status == 200:
            fees_data = fees_result
        else:
            fee_error = fees_result.get('error', 'Unknown error')
    else:
        fee_error = "API key required for fee management"
    
    return render_template('admin/dashboard.html', 
                         markets=markets, 
                         fees=fees_data, 
                         fee_error=fee_error,
                         format_number=format_number,
                         calculate_total=calculate_total)

@app.route('/admin/create_market', methods=['POST'])
def admin_create_market():
    """Create new market."""
    if not is_admin():
        flash('Admin access required', 'error')
        return redirect(url_for('admin_dashboard'))
    
    if 'api_key' not in session:
        flash('Please login with your API key first to create markets', 'error')
        return redirect(url_for('admin_dashboard'))
    
    base_coin = request.form.get('base_coin', '').upper().strip()
    quote_coin = request.form.get('quote_coin', '').upper().strip()
    
    if not base_coin or not quote_coin:
        flash('Both base and quote coins required', 'error')
    elif base_coin == quote_coin:
        flash('Base and quote coins must be different', 'error')
    else:
        data = {
            'base_coin': base_coin,
            'quote_coin': quote_coin
        }
        
        result, status = make_api_request('/admin/create_market', method='POST', data=data, admin_required=True)
        
        if status == 201:
            flash(f'Market {base_coin}/{quote_coin} created successfully!', 'success')
        else:
            error_msg = result.get('error', 'Unknown error')
            if status == 401:
                flash('Authentication failed. Please ensure you have admin API access.', 'error')
            else:
                flash(f'Market creation failed: {error_msg}', 'error')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/withdraw_fees', methods=['POST'])
def admin_withdraw_fees():
    """Withdraw fees."""
    if not is_admin():
        flash('Admin access required', 'error')
        return redirect(url_for('admin_dashboard'))
    
    if 'api_key' not in session:
        flash('Please login with your API key first to withdraw fees', 'error')
        return redirect(url_for('admin_dashboard'))
    
    coin = request.form.get('coin', '').upper().strip()
    amount = request.form.get('amount', '').strip()
    
    if not coin or not amount:
        flash('Coin and amount required', 'error')
    else:
        data = {
            'coin': coin,
            'amount': amount
        }
        
        result, status = make_api_request('/admin/fees', method='POST', data=data, admin_required=True)
        
        if status == 200:
            flash(f'Fee withdrawal successful: {amount} {coin}', 'success')
        else:
            error_msg = result.get('error', 'Unknown error')
            if status == 401:
                flash('Authentication failed. Please ensure you have admin API access.', 'error')
            else:
                flash(f'Fee withdrawal failed: {error_msg}', 'error')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/logout')
def admin_logout():
    """Admin logout."""
    session.pop('admin_access', None)
    flash('Admin logged out', 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    # Ensure we're not in debug mode for production
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    
    if debug_mode:
        logger.warning("Running UI in DEBUG mode - DO NOT use in production!")
    
    app.run(debug=debug_mode, host='127.0.0.1', port=UI_PORT)
