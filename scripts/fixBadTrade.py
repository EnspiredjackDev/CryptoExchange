from db import SessionLocal
from models import Order, OrderStatus, OrderSide, Balance, Market
from decimal import Decimal

def fix_trade_balances():
    db = SessionLocal()
    try:
        filled_orders = db.query(Order).filter(Order.status == OrderStatus.filled).all()
        count = 0

        for order in filled_orders:
            market = order.market
            base = market.base_coin
            quote = market.quote_coin

            if order.side == OrderSide.buy:
                cost = Decimal(order.amount) * Decimal(order.price)
                bal = db.query(Balance).filter_by(user_id=order.user_id, coin_symbol=quote).first()
                if bal:
                    bal.total -= cost
                    count += 1

            elif order.side == OrderSide.sell:
                bal = db.query(Balance).filter_by(user_id=order.user_id, coin_symbol=base).first()
                if bal:
                    bal.total -= Decimal(order.amount)
                    count += 1

        db.commit()
        print(f"✅ Fixed {count} balance record(s).")

    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    fix_trade_balances()
