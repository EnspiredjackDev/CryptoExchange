from decimal import Decimal
import secrets
import hashlib

from sqlalchemy import text

def generate_api_key():
    return secrets.token_hex(32)

def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()

def start_money_transaction(db):
    db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))

def xmr_to_atomic(amount: Decimal) -> int:
    return int(amount * Decimal("1e12"))
