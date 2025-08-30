# CryptoExchange UI

A dark mode, JavaScript-free web interface for the CryptoExchange trading platform, designed to work with Tor Browser's safest settings.

## Features

- **🌑 Dark Mode Interface**: TradeOgre-inspired dark theme
- **🚫 No JavaScript**: Pure HTML/CSS for maximum compatibility with Tor Browser
- **🔒 Security First**: Secure headers, CSRF protection, input validation
- **📱 Responsive Design**: Works on desktop and mobile devices
- **👤 User Management**: Account creation, login, balance management
- **💹 Full Trading**: Order placement, cancellation, order book viewing
- **💰 Wallet Features**: Address generation, withdrawals, balance tracking
- **🔧 Admin Panel**: Hidden admin interface for exchange management

## Quick Start

1. **Install Dependencies**:
   ```bash
   cd ui
   pip install -r requirements.txt
   ```

2. **Start the Exchange API** (in another terminal):
   ```bash
   cd /home/Jack/CryptoExchange
   python3 app.py
   ```

3. **Start the UI**:
   ```bash
   cd ui
   ./start_ui.sh
   ```

4. **Access the Interface**:
   - Main Exchange: http://127.0.0.1:5001
   - Admin Panel: http://127.0.0.1:5001/admin

## Configuration

Set these environment variables before starting:

```bash
export UI_SECRET_KEY="your-secret-key-here"
export EXCHANGE_API_URL="http://127.0.0.1:5000"
export UI_PORT="5001"
export ADMIN_ACCESS_KEY="your-admin-key-here"
export FLASK_ENV="production"  # or "development"
```

## Admin Access

The admin panel is intentionally hidden and only accessible via direct URL:
- URL: `/admin`
- Default access key: `admin-secret-key` (change this!)
- Features: Market creation, fee management, system overview

## Security Features

- **No JavaScript**: Compatible with Tor Browser's safest settings
- **Secure Headers**: CSP, HSTS, X-Frame-Options, etc.
- **Input Validation**: All user inputs are validated
- **Session Security**: Secure session management
- **API Integration**: Secure communication with exchange backend
- **Admin Protection**: Hidden admin interface with separate authentication

## Tor Browser Compatibility

This interface is specifically designed to work with Tor Browser's highest security settings:
- No JavaScript required
- Pure CSS styling
- HTML forms for all interactions
- Compatible with safest security slider setting

## User Workflow

1. **Registration**: Create account → Get API key → Save securely
2. **Login**: Enter API key to access account
3. **Deposits**: Generate addresses → Send cryptocurrencies
4. **Trading**: View markets → Place orders → Monitor executions
5. **Withdrawals**: Verify addresses → Send funds securely

## File Structure

```
ui/
├── ui_app.py              # Main Flask application
├── start_ui.sh            # Startup script
├── requirements.txt       # Python dependencies
├── templates/
│   ├── base.html          # Base template with dark theme
│   ├── index.html         # Main markets page
│   ├── market.html        # Individual market view
│   ├── login.html         # User login
│   ├── register.html      # Account creation
│   ├── account.html       # Account overview
│   ├── withdraw.html      # Withdrawal interface
│   └── admin/
│       ├── login.html     # Admin login
│       └── dashboard.html # Admin dashboard
└── static/css/            # Additional CSS (if needed)
```

## API Integration

The UI communicates with the exchange API at these endpoints:
- `POST /create_account` - Account creation
- `GET /auth_test` - Authentication validation
- `GET /markets` - Market data
- `GET /orderbook` - Order book data
- `POST /order` - Order placement
- `POST /cancel_order` - Order cancellation
- `GET /balance` - User balances
- `POST /generate_address` - Address generation
- `POST /withdraw` - Withdrawals
- `GET /trades` - Trade history
- `GET /orders` - Open orders
- Admin endpoints for management

## Security Considerations

1. **Change Default Keys**: Update `UI_SECRET_KEY` and `ADMIN_ACCESS_KEY`
2. **Use HTTPS**: Enable HTTPS in production
3. **Network Security**: Use behind reverse proxy or VPN
4. **Monitor Access**: Check logs for suspicious activity
5. **Regular Updates**: Keep dependencies updated

## Development

For development with auto-reload:

```bash
export FLASK_ENV=development
python3 ui_app.py
```

## Production Deployment

1. Set secure environment variables
2. Use a proper WSGI server (gunicorn, uWSGI)
3. Enable HTTPS
4. Set up reverse proxy (nginx)
5. Configure firewall rules
6. Enable logging and monitoring

## Troubleshooting

## Security Disclosure

Report security issues to the exchange administrator. Do not disclose publicly until patched.
