from sqlalchemy import text
from models import Fee, Order, Balance, Trade, OrderSide, OrderStatus
from helpers import add_fee_to_balance, get_or_create_balance
from decimal import Decimal
from datetime import datetime, timezone

def match_orders(db, market_id):

    db.execute(text("SELECT pg_advisory_xact_lock(:mid)"), {"mid": market_id})
    
    # Get all open orders for this market
    buys = db.query(Order).filter_by(
        market_id=market_id,
        side=OrderSide.buy,
        status=OrderStatus.open
    ).order_by(Order.price.desc(), Order.created_at.asc()).all()

    sells = db.query(Order).filter_by(
        market_id=market_id,
        side=OrderSide.sell,
        status=OrderStatus.open
    ).order_by(Order.price.asc(), Order.created_at.asc()).all()

    trades = []

    for buy in buys:
        if buy.remaining <= 0:
            continue

        for sell in sells:
            if sell.remaining <= 0:
                continue

            # Price match check
            if sell.price > buy.price:
                break

            # --- Trade details ---
            trade_price = sell.price
            trade_amount = min(buy.remaining, sell.remaining)
            total_quote = trade_price * trade_amount  # quote_coin amount

            market = buy.market
            base_coin = market.base_coin
            quote_coin = market.quote_coin

            fee_rate = market.fee_rate or Decimal("0.001")
            base_fee = trade_amount * fee_rate
            quote_fee = total_quote * fee_rate

            # --- Buyer logic ---
            buyer_base = get_or_create_balance(db, buy.user_id, base_coin)
            buyer_base.available += trade_amount - base_fee  # receive base minus fee
            buyer_base.total += trade_amount - base_fee

            buyer_quote = get_or_create_balance(db, buy.user_id, quote_coin)
            buyer_quote.locked -= total_quote  # unlock the amount used for trade

            # Refund unused locked funds due to price improvement
            locked_at_order_price = buy.price * trade_amount
            unused_locked = locked_at_order_price - total_quote
            if unused_locked > 0:
                buyer_quote.available += unused_locked

            buyer_quote.total = buyer_quote.available + buyer_quote.locked

            # --- Seller logic ---
            seller_quote = get_or_create_balance(db, sell.user_id, quote_coin)
            seller_quote.available += total_quote - quote_fee  # receive quote minus fee
            seller_quote.total += total_quote - quote_fee

            seller_base = get_or_create_balance(db, sell.user_id, base_coin)
            seller_base.locked -= trade_amount  # they sold it

            seller_base.total = seller_base.available + seller_base.locked
            seller_quote.total = seller_quote.available + seller_quote.locked

            # --- Record trade ---
            trade = Trade(
                buy_order_id=buy.id,
                sell_order_id=sell.id,
                market_id=market_id,
                price=trade_price,
                amount=trade_amount,
                timestamp=datetime.now(timezone.utc)
            )
            db.add(trade)
            db.flush()  # trade.id needed for fee tracking

            # --- Fee tracking ---
            db.add(Fee(
                trade_id=trade.id,
                coin_symbol=base_coin,
                amount=base_fee,
                timestamp=datetime.now(timezone.utc)
            ))
            db.add(Fee(
                trade_id=trade.id,
                coin_symbol=quote_coin,
                amount=quote_fee,
                timestamp=datetime.now(timezone.utc)
            ))

            add_fee_to_balance(db, base_coin, base_fee)
            add_fee_to_balance(db, quote_coin, quote_fee)

            trades.append(trade)

            # --- Update order state ---
            buy.remaining -= trade_amount
            sell.remaining -= trade_amount

            if buy.remaining <= 0:
                buy.status = OrderStatus.filled
            elif buy.remaining < buy.amount:
                buy.status = OrderStatus.partially_filled

            if sell.remaining <= 0:
                sell.status = OrderStatus.filled
            elif sell.remaining < sell.amount:
                sell.status = OrderStatus.partially_filled

            # Stop matching this buy order if fully filled
            if buy.remaining <= 0:
                break

    return trades
