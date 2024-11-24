from functools import wraps
import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt

app = Flask(__name__)

# Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'SECUREKEYHERE' # replace this

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

# Import models
from crypto_helpers import CryptoNode
from models import DepositAddress, User, Node

with app.app_context():
        db.create_all()

@app.after_request
def add_no_cache_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or not user.is_admin:
            flash('You are not authorised to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Home route
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

# Register route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if not username or not password:
            flash('Username and password are required.', 'error')
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first():
            flash('User already exists.', 'error')
            return redirect(url_for('register'))

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(username=username, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        flash('Registration successful! Please log in.', 'success')  # Flash success message
        return redirect(url_for('login'))

    return render_template('register.html')

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if not username or not password:
            flash('Username and password are required.', 'error')
            return redirect(url_for('login'))

        # Check if user exists
        user = User.query.filter_by(username=username).first()
        if not user or not bcrypt.check_password_hash(user.password, password):
            flash('Invalid credentials.', 'error')
            return redirect(url_for('login'))

        # Log in user by storing their ID in session
        session['user_id'] = user.id
        flash('Login successful!', 'success')
        return redirect(url_for('dashboard'))

    return render_template('login.html')

# Dashboard route
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash('Please log in to access the dashboard.', 'error')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if '_flashes' in session:
        session.pop('_flashes')
    return render_template('dashboard.html', user=user)

# Logout route
@app.route('/logout')
def logout():
    if '_flashes' in session:
        session.pop('_flashes')
    session.pop('user_id', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin():
    """
    Admin page for managing cryptocurrency node configurations.
    """
    # Restrict access: Add your own admin authentication logic here
    # Example: Use Flask sessions to check for an 'is_admin' flag
    user = User.query.get(session['user_id'])
    if not user or not user.is_admin:
        flash('You are not authorised to access this page.', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        # Add a new node
        name = request.form['name']
        symbol = request.form['symbol']
        host = request.form['host']
        port = request.form['port']
        username = request.form['username']
        password = request.form['password']

        # Validation
        if not (name and symbol and host and port and username and password):
            flash('All fields are required.', 'error')
            return redirect(url_for('admin'))

        # Check if the symbol already exists
        if Node.query.filter_by(symbol=symbol).first():
            flash(f'A node with the symbol "{symbol}" already exists.', 'error')
            return redirect(url_for('admin'))

        # Add to database
        new_node = Node(
            name=name,
            symbol=symbol.upper(),
            host=host,
            port=int(port),
            username=username,
            password=password
        )

        db.session.add(new_node)
        db.session.commit()

        flash('Node added successfully!', 'success')
        return redirect(url_for('admin'))

    # Fetch all nodes for display
    nodes = Node.query.all()
    return render_template('admin.html', nodes=nodes)


@app.route('/admin/delete/<int:node_id>', methods=['POST'])
@admin_required
def delete_node(node_id):
    """
    Delete a node configuration by ID.
    """
    if not session.get('is_admin', False):
        flash('You are not authorised to perform this action.', 'error')
        return redirect(url_for('login'))

    node = Node.query.get(node_id)
    if node:
        db.session.delete(node)
        db.session.commit()
        flash('Node deleted successfully!', 'success')
    else:
        flash('Node not found.', 'error')

    return redirect(url_for('admin'))

@app.route('/promote', methods=['POST', 'GET'])
def promote_user():
    """
    Promote the current logged-in user to admin privileges.
    Requires a valid secret key passed in the POST request.
    """
    if request.method == "GET":
        return render_template('promote.html')
    if 'user_id' not in session:
        flash('You must be logged in to access this feature.', 'error')
        return redirect(url_for('login'))

    # Retrieve the secret from the environment
    promotion_secret = os.environ.get('ADMIN_PROMOTION_SECRET')

    # Verify the provided secret
    provided_secret = request.form.get('secret')
    if not provided_secret or provided_secret != promotion_secret:
        app.logger.warning('Unauthorized admin promotion attempt.')
        flash('Invalid promotion secret. Access denied.', 'error')
        return redirect(url_for('dashboard'))

    # Promote the current user to admin
    user = User.query.get(session['user_id'])
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('dashboard'))

    user.is_admin = True
    db.session.commit()

    app.logger.info(f'User {user.username} promoted to admin.')
    flash('You have been promoted to admin privileges.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/deposit', methods=['GET', 'POST'])
def deposit():
    if 'user_id' not in session:
        flash('Please log in to access the deposit page.', 'error')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])

    # Fetch supported nodes
    nodes = Node.query.all()

    # Get filter from query parameters
    filter_currency = request.args.get('currency')
    
    if filter_currency:
        # Fetch deposit addresses filtered by the selected currency
        deposit_addresses = DepositAddress.query.join(Node).filter(
            DepositAddress.user_id == user.id,
            Node.symbol == filter_currency.upper()
        ).all()
    else:
        # Fetch all deposit addresses for the user
        deposit_addresses = DepositAddress.query.filter_by(user_id=user.id).all()

    if request.method == 'POST':
        # Generate a new deposit address
        node_id = request.form.get('node_id')

        # Validate node selection
        node = Node.query.get(node_id)
        if not node:
            flash('Invalid currency selected.', 'error')
            return redirect(url_for('deposit'))

        # Generate address using CryptoNode
        crypto_node = CryptoNode(node.host, node.port, node.username, node.password)
        try:
            new_address = crypto_node.get_new_address()
        except Exception as e:
            flash(f'Error generating address: {e}', 'error')
            return redirect(url_for('deposit'))

        # Save to database
        deposit_address = DepositAddress(
            user_id=user.id,
            node_id=node.id,
            address=new_address
        )
        db.session.add(deposit_address)
        db.session.commit()

        flash(f'New deposit address created: {new_address}', 'success')
        return redirect(url_for('deposit'))

    return render_template(
        'deposit.html',
        nodes=nodes,
        deposit_addresses=deposit_addresses,
        filter_currency=filter_currency
    )

if __name__ == '__main__':
    app.run(debug=True)