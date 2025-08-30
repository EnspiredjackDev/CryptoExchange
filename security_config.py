"""
Production security configuration for the crypto exchange.
This file contains security settings that should be customized for your deployment.
"""

import os
import hashlib

class ProductionSecurityConfig:
    """Production security configuration - customize these values!"""
    
    # IMPORTANT: Generate a strong admin API key and set its hash here
    ADMIN_API_KEY_HASH = os.environ.get('ADMIN_API_KEY_HASH')
    
    # Rate limiting (requests per minute)
    RATE_LIMIT_AUTHENTICATED = int(os.environ.get('RATE_LIMIT_AUTHENTICATED', 60))
    RATE_LIMIT_PUBLIC = int(os.environ.get('RATE_LIMIT_PUBLIC', 10))
    
    # Allow localhost to bypass rate limiting (for UI proxy)
    RATE_LIMIT_EXEMPT_LOCALHOST = os.environ.get('RATE_LIMIT_EXEMPT_LOCALHOST', 'true').lower() == 'true'
    
    # Request limits
    MAX_REQUEST_SIZE = int(os.environ.get('MAX_REQUEST_SIZE', 1024 * 1024))  # 1MB
    
    # Security timeouts
    MAX_LOGIN_ATTEMPTS = int(os.environ.get('MAX_LOGIN_ATTEMPTS', 5))
    LOCKOUT_DURATION = int(os.environ.get('LOCKOUT_DURATION', 300))  # 5 minutes
    
    # Database settings
    ENABLE_BALANCE_INTEGRITY_CHECKS = os.environ.get('ENABLE_BALANCE_INTEGRITY_CHECKS', 'true').lower() == 'true'
    
    # Logging
    SECURITY_LOG_LEVEL = os.environ.get('SECURITY_LOG_LEVEL', 'INFO')
    SECURITY_LOG_FILE = os.environ.get('SECURITY_LOG_FILE', './security.log')
    
    # Development mode check
    IS_DEVELOPMENT = os.environ.get('FLASK_ENV') == 'development'

# Validation function
def validate_security_config():
    """Validate security configuration before starting the application."""
    errors = []
    
    if not ProductionSecurityConfig.IS_DEVELOPMENT:
        if not ProductionSecurityConfig.ADMIN_API_KEY_HASH:
            errors.append("ADMIN_API_KEY_HASH must be set in production")
        
        if ProductionSecurityConfig.RATE_LIMIT_AUTHENTICATED > 120:
            errors.append("Rate limit too high for production (max 120 req/min recommended)")
    
    if errors:
        raise ValueError(f"Security configuration errors: {', '.join(errors)}")
    
    return True

if __name__ == "__main__":
    # Helper script to generate admin key hash
    import getpass
    
    print("Admin Key Hash Generator")
    print("=" * 30)
    
    admin_key = getpass.getpass("Enter admin API key (minimum 32 characters): ")
    
    if len(admin_key) < 32:
        print("ERROR: Admin key must be at least 32 characters long")
        exit(1)
    
    admin_hash = hashlib.sha256(admin_key.encode()).hexdigest()
    
    print(f"\nAdmin API Key Hash: {admin_hash}")
    print("\nAdd this to your environment variables:")
    print(f"export ADMIN_API_KEY_HASH='{admin_hash}'")
    print("\nOr add to your production config file.")
