from decimal import Decimal
from models import Balance, FeeBalance


def get_or_create_balance(db, user_id, coin):
    balance = db.query(Balance).filter_by(user_id=user_id, coin_symbol=coin).first()
    if not balance:
        balance = Balance(
            user_id=user_id,
            coin_symbol=coin,
            total=0,
            available=0,
            locked=0
        )
        db.add(balance)
        db.flush()
    return balance

def add_fee_to_balance(db, coin_symbol, amount):
    balance = db.query(FeeBalance).filter_by(coin_symbol=coin_symbol).first()
    if not balance:
        balance = FeeBalance(coin_symbol=coin_symbol, amount=Decimal("0.0"))
        db.add(balance)
        db.flush()
    balance.amount += amount