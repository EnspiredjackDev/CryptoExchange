"""
Security middleware and utilities for the crypto exchange.
Provides rate limiting, input validation, admin authentication, and security logging.
"""

import time
import hashlib
import hmac
import functools
import logging
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from flask import request, jsonify, g
from threading import Lock
from typing import Dict, Optional, Tuple, Any

# Configure security logging
security_logger = logging.getLogger('security')
security_logger.setLevel(logging.INFO)
if not security_logger.handlers:
    handler = logging.FileHandler('./logs/security.log')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    security_logger.addHandler(handler)

class SecurityConfig:
    """Security configuration constants."""
    
    # Import production config if available
    try:
        from security_config import ProductionSecurityConfig
        
        # Rate limiting
        RATE_LIMIT_REQUESTS = ProductionSecurityConfig.RATE_LIMIT_AUTHENTICATED
        RATE_LIMIT_WINDOW = 60   # window in seconds
        RATE_LIMIT_PUBLIC = ProductionSecurityConfig.RATE_LIMIT_PUBLIC
        RATE_LIMIT_EXEMPT_LOCALHOST = ProductionSecurityConfig.RATE_LIMIT_EXEMPT_LOCALHOST
        
        # Request limits
        MAX_REQUEST_SIZE = ProductionSecurityConfig.MAX_REQUEST_SIZE
        MAX_JSON_KEYS = 20
        MAX_STRING_LENGTH = 1000
        
        # Security
        MIN_PASSWORD_LENGTH = 12
        MAX_LOGIN_ATTEMPTS = ProductionSecurityConfig.MAX_LOGIN_ATTEMPTS
        LOCKOUT_DURATION = ProductionSecurityConfig.LOCKOUT_DURATION
        
        # Admin authentication
        ADMIN_API_KEY_HASH = ProductionSecurityConfig.ADMIN_API_KEY_HASH
        
    except ImportError:
        # Fallback to default values if production config not available
        RATE_LIMIT_REQUESTS = 60
        RATE_LIMIT_WINDOW = 60
        RATE_LIMIT_PUBLIC = 10
        RATE_LIMIT_EXEMPT_LOCALHOST = True
        MAX_REQUEST_SIZE = 1024 * 1024
        MAX_JSON_KEYS = 20
        MAX_STRING_LENGTH = 1000
        MIN_PASSWORD_LENGTH = 12
        MAX_LOGIN_ATTEMPTS = 5
        LOCKOUT_DURATION = 300
        ADMIN_API_KEY_HASH = None
    
    # Timing attack protection
    CONSTANT_TIME_COMPARE_LENGTH = 64

class RateLimiter:
    """Thread-safe rate limiter using sliding window."""
    
    def __init__(self):
        self._requests: Dict[str, deque] = defaultdict(deque)
        self._lock = Lock()
    
    def is_allowed(self, identifier: str, limit: int, window: int) -> Tuple[bool, int]:
        """Check if request is allowed and return remaining quota."""
        with self._lock:
            now = time.time()
            window_start = now - window
            
            # Clean old requests
            while (self._requests[identifier] and 
                   self._requests[identifier][0] < window_start):
                self._requests[identifier].popleft()
            
            current_count = len(self._requests[identifier])
            
            if current_count >= limit:
                return False, 0
            
            # Add current request
            self._requests[identifier].append(now)
            return True, limit - current_count - 1
    
    def reset(self, identifier: str):
        """Reset rate limit for identifier."""
        with self._lock:
            if identifier in self._requests:
                del self._requests[identifier]

class SecurityValidator:
    """Input validation and sanitization."""
    
    @staticmethod
    def validate_api_key(api_key: str) -> bool:
        """Validate API key format."""
        if not api_key or not isinstance(api_key, str):
            return False
        
        # API keys should be 64 hex characters
        return len(api_key) == 64 and all(c in '0123456789abcdef' for c in api_key.lower())
    
    @staticmethod
    def validate_coin_symbol(coin: str) -> bool:
        """Validate cryptocurrency symbol."""
        if not coin or not isinstance(coin, str):
            return False
        
        # 1-10 alphanumeric characters
        return 1 <= len(coin) <= 10 and coin.isalnum() and coin.isupper()
    
    @staticmethod
    def validate_address(address: str, coin: str) -> bool:
        """Basic address validation."""
        if not address or not isinstance(address, str):
            return False
        
        # Basic length and character validation
        if not (20 <= len(address) <= 100):
            return False
        
        # Only alphanumeric and some special chars
        if not re.match(r'^[a-zA-Z0-9+/=_-]+$', address):
            return False
        
        return True
    
    @staticmethod
    def validate_decimal(value: Any, min_val: Decimal = Decimal('0'), 
                        max_val: Optional[Decimal] = None) -> Optional[Decimal]:
        """Validate and convert to Decimal."""
        try:
            if isinstance(value, str):
                # Remove whitespace and validate format
                value = value.strip()
                if not re.match(r'^[0-9]+\.?[0-9]*$', value):
                    return None
            
            decimal_value = Decimal(str(value))
            
            if decimal_value < min_val:
                return None
            
            if max_val is not None and decimal_value > max_val:
                return None
            
            # Quantize to 8 decimal places
            return decimal_value.quantize(Decimal('0.00000001'))
            
        except (InvalidOperation, ValueError, OverflowError):
            return None
    
    @staticmethod
    def validate_request_size(request) -> bool:
        """Validate request size."""
        content_length = request.content_length
        return content_length is None or content_length <= SecurityConfig.MAX_REQUEST_SIZE
    
    @staticmethod
    def validate_json_structure(data: dict) -> bool:
        """Validate JSON structure complexity."""
        if not isinstance(data, dict):
            return False
        
        if len(data) > SecurityConfig.MAX_JSON_KEYS:
            return False
        
        for key, value in data.items():
            if not isinstance(key, str) or len(key) > 100:
                return False
            
            if isinstance(value, str) and len(value) > SecurityConfig.MAX_STRING_LENGTH:
                return False
        
        return True

class SecurityMonitor:
    """Security event monitoring and alerting."""
    
    def __init__(self):
        self._failed_attempts: Dict[str, deque] = defaultdict(deque)
        self._locked_ips: Dict[str, datetime] = {}
        self._lock = Lock()
    
    def record_failed_auth(self, ip_address: str, user_id: Optional[str] = None):
        """Record failed authentication attempt."""
        with self._lock:
            now = datetime.now(timezone.utc)
            self._failed_attempts[ip_address].append(now)
            
            # Keep only recent attempts (last hour)
            cutoff = now - timedelta(hours=1)
            while (self._failed_attempts[ip_address] and 
                   self._failed_attempts[ip_address][0] < cutoff):
                self._failed_attempts[ip_address].popleft()
            
            # Check if should lock IP
            if len(self._failed_attempts[ip_address]) >= SecurityConfig.MAX_LOGIN_ATTEMPTS:
                self._locked_ips[ip_address] = now + timedelta(seconds=SecurityConfig.LOCKOUT_DURATION)
                security_logger.warning(f"IP locked due to failed attempts: {ip_address}")
        
        security_logger.warning(f"Failed auth attempt from {ip_address}, user: {user_id}")
    
    def is_ip_locked(self, ip_address: str) -> bool:
        """Check if IP is currently locked."""
        with self._lock:
            if ip_address not in self._locked_ips:
                return False
            
            if datetime.now(timezone.utc) > self._locked_ips[ip_address]:
                del self._locked_ips[ip_address]
                return False
            
            return True
    
    def record_suspicious_activity(self, ip_address: str, activity: str, details: dict):
        """Record suspicious activity."""
        security_logger.warning(f"Suspicious activity from {ip_address}: {activity}, details: {details}")

# Global instances
rate_limiter = RateLimiter()
security_monitor = SecurityMonitor()

def get_client_ip() -> str:
    """Get real client IP address."""
    # Check various headers for real IP (behind reverse proxy)
    real_ip = (request.headers.get('X-Real-IP') or
              request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or
              request.remote_addr or
              'unknown')
    
    return real_ip

def constant_time_compare(a: str, b: str) -> bool:
    """Constant time string comparison to prevent timing attacks."""
    if len(a) != len(b):
        # Pad shorter string to prevent length-based timing attacks
        if len(a) < len(b):
            a += '0' * (len(b) - len(a))
        else:
            b += '0' * (len(a) - len(b))
    
    return hmac.compare_digest(a.encode(), b.encode())

def require_rate_limit(limit_type: str = 'authenticated'):
    """Decorator for rate limiting endpoints."""
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            client_ip = get_client_ip()
            
            # Skip rate limiting for localhost requests (UI proxy) if enabled
            if (SecurityConfig.RATE_LIMIT_EXEMPT_LOCALHOST and 
                client_ip in ['127.0.0.1', '::1', 'localhost']):
                security_logger.debug(f"Skipping rate limit for localhost request from {client_ip}")
                return f(*args, **kwargs)
            
            # Check if IP is locked
            if security_monitor.is_ip_locked(client_ip):
                security_logger.warning(f"Request from locked IP: {client_ip}")
                return jsonify({"error": "IP temporarily locked due to suspicious activity"}), 429
            
            # Determine rate limit
            if limit_type == 'public':
                limit = SecurityConfig.RATE_LIMIT_PUBLIC
                identifier = f"ip:{client_ip}"
            else:
                limit = SecurityConfig.RATE_LIMIT_REQUESTS
                # Use API key if available, otherwise IP
                api_key = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
                identifier = f"key:{api_key}" if api_key else f"ip:{client_ip}"
            
            allowed, remaining = rate_limiter.is_allowed(
                identifier, limit, SecurityConfig.RATE_LIMIT_WINDOW
            )
            
            if not allowed:
                security_logger.warning(f"Rate limit exceeded for {identifier}")
                return jsonify({
                    "error": "Rate limit exceeded",
                    "retry_after": SecurityConfig.RATE_LIMIT_WINDOW
                }), 429
            
            # Add rate limit headers
            response = f(*args, **kwargs)
            if hasattr(response, 'headers'):
                response.headers['X-RateLimit-Limit'] = str(limit)
                response.headers['X-RateLimit-Remaining'] = str(remaining)
                response.headers['X-RateLimit-Reset'] = str(int(time.time() + SecurityConfig.RATE_LIMIT_WINDOW))
            
            return response
        return wrapper
    return decorator

def require_admin():
    """Decorator for admin-only endpoints."""
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            client_ip = get_client_ip()
            
            # Get admin API key from header
            admin_key = request.headers.get("X-Admin-Key", "").strip()
            
            if not admin_key:
                security_monitor.record_failed_auth(client_ip)
                return jsonify({"error": "Admin authentication required"}), 401
            
            # Validate admin key (you should set ADMIN_API_KEY_HASH in production)
            if not SecurityConfig.ADMIN_API_KEY_HASH:
                security_logger.error("Admin API key hash not configured!")
                return jsonify({"error": "Admin access not configured"}), 500
            
            admin_key_hash = hashlib.sha256(admin_key.encode()).hexdigest()
            
            if not constant_time_compare(admin_key_hash, SecurityConfig.ADMIN_API_KEY_HASH):
                security_monitor.record_failed_auth(client_ip, "admin")
                security_logger.warning(f"Invalid admin key attempt from {client_ip}")
                return jsonify({"error": "Invalid admin key"}), 403
            
            security_logger.info(f"Admin access granted to {client_ip}")
            return f(*args, **kwargs)
        return wrapper
    return decorator

def validate_request():
    """Middleware for request validation."""
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            client_ip = get_client_ip()
            
            # Validate request size
            if not SecurityValidator.validate_request_size(request):
                security_monitor.record_suspicious_activity(
                    client_ip, "oversized_request", 
                    {"content_length": request.content_length}
                )
                return jsonify({"error": "Request too large"}), 413
            
            # Validate JSON structure for POST requests
            if request.method == 'POST' and request.is_json:
                try:
                    data = request.get_json()
                    if data and not SecurityValidator.validate_json_structure(data):
                        security_monitor.record_suspicious_activity(
                            client_ip, "malformed_json", 
                            {"keys_count": len(data) if isinstance(data, dict) else "not_dict"}
                        )
                        return jsonify({"error": "Invalid request structure"}), 400
                except Exception as e:
                    return jsonify({"error": "Invalid JSON"}), 400
            
            return f(*args, **kwargs)
        return wrapper
    return decorator

def secure_endpoint(rate_limit_type: str = 'authenticated'):
    """Combined security decorator."""
    def decorator(f):
        @validate_request()
        @require_rate_limit(rate_limit_type)
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            return f(*args, **kwargs)
        return wrapper
    return decorator

def authenticate_user(db, log_failures: bool = True):
    """Authenticate user from API key and return user object."""
    client_ip = get_client_ip()
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    
    if not api_key:
        if log_failures:
            security_monitor.record_failed_auth(client_ip)
        return None, jsonify({"error": "Missing API key"}), 401
    
    if not SecurityValidator.validate_api_key(api_key):
        if log_failures:
            security_monitor.record_failed_auth(client_ip)
            security_monitor.record_suspicious_activity(
                client_ip, "invalid_api_key_format", 
                {"key_length": len(api_key)}
            )
        return None, jsonify({"error": "Invalid API key format"}), 400
    
    try:
        from utils import hash_api_key
        from models import User
        
        hashed_key = hash_api_key(api_key)
        user = db.query(User).filter_by(api_key_hash=hashed_key).first()
        
        if not user:
            if log_failures:
                security_monitor.record_failed_auth(client_ip, f"key:{api_key[:8]}...")
            return None, jsonify({"error": "Invalid API key"}), 403
        
        # Store user in request context for later use
        g.current_user = user
        g.client_ip = client_ip
        
        return user, None, None
        
    except Exception as e:
        security_logger.error(f"Authentication error: {str(e)}")
        return None, jsonify({"error": "Authentication failed"}), 500

def log_security_event(event_type: str, details: dict):
    """Log security event."""
    client_ip = get_client_ip()
    user_id = getattr(g, 'current_user', {}).id if hasattr(g, 'current_user') else None
    
    security_logger.info(f"Security event: {event_type}, IP: {client_ip}, User: {user_id}, Details: {details}")
