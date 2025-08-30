from decimal import Decimal
import secrets
import hashlib
import logging

from sqlalchemy import text
from contextlib import contextmanager

# Configure logging
logger = logging.getLogger(__name__)

def generate_api_key():
    """Generate a cryptographically secure API key."""
    return secrets.token_hex(32)

def hash_api_key(api_key: str) -> str:
    """Hash API key using SHA-256."""
    if not api_key:
        raise ValueError("API key cannot be empty")
    return hashlib.sha256(api_key.encode()).hexdigest()

@contextmanager
def safe_transaction(db, isolation_level=None):
    """
    Context manager for safe database transactions.
    
    Args:
        db: Database session
        isolation_level: Optional isolation level ('REPEATABLE READ', 'SERIALIZABLE', etc.)
    
    Usage:
        with safe_transaction(db) as session:
            # Your transaction code here
            session.add(...)
    """
    transaction = None
    try:
        if isolation_level:
            db.execute(text(f"SET TRANSACTION ISOLATION LEVEL {isolation_level}"))
        
        transaction = db.begin()
        yield db
        transaction.commit()
        logger.debug("Transaction committed successfully")
        
    except Exception as e:
        if transaction:
            transaction.rollback()
            logger.error(f"Transaction rolled back due to error: {e}")
        raise
    finally:
        if transaction and transaction.is_active:
            try:
                transaction.rollback()
            except Exception as rollback_error:
                logger.error(f"Error during transaction cleanup: {rollback_error}")

def xmr_to_atomic(amount: Decimal) -> int:
    """Convert XMR amount to atomic units (piconero)."""
    if amount < 0:
        raise ValueError("Amount cannot be negative")
    return int(amount * Decimal("1e12"))

def atomic_to_xmr(atomic_amount: int) -> Decimal:
    """Convert atomic XMR units to XMR."""
    if atomic_amount < 0:
        raise ValueError("Atomic amount cannot be negative")
    return Decimal(atomic_amount) / Decimal("1e12")

def validate_transaction_integrity(db, user_id: int, coin_symbol: str):
    """
    Validate that user's balance integrity is maintained.
    total = available + locked
    """
    from models import Balance
    
    balance = db.query(Balance).filter_by(user_id=user_id, coin_symbol=coin_symbol).first()
    if balance:
        expected_total = balance.available + balance.locked
        if abs(balance.total - expected_total) > Decimal('0.00000001'):
            logger.error(f"Balance integrity violation for user {user_id}, coin {coin_symbol}: "
                        f"total={balance.total}, available={balance.available}, locked={balance.locked}")
            raise Exception(f"Balance integrity check failed for {coin_symbol}")
    
    return True
