"""
OrderService - Handles order placement, cancellation, and order book operations.
"""

from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from models import Balance, Market, Order, OrderSide, OrderStatus, Trade
from utils import validate_transaction_integrity
from matcher import match_orders
from security import log_security_event, SecurityValidator

logger = logging.getLogger(__name__)


class OrderService:
    """Service class for order-related operations."""
    
    @staticmethod
    def place_order(
        db: Session, 
        user_id: int, 
        market_id: int, 
        side: str, 
        price: Decimal, 
        amount: Decimal
    ) -> Dict:
        """
        Place a new order on the market.
        
        Args:
            db: Database session
            user_id: User ID
            market_id: Market ID
            side: 'buy' or 'sell'
            price: Order price
            amount: Order amount
            
        Returns:
            Dictionary with order information and matched trades
            
        Raises:
            ValueError: If inputs are invalid
            Exception: If order placement fails
        """
        # Validate inputs
        if side not in ['buy', 'sell']:
            raise ValueError("Invalid side (must be 'buy' or 'sell')")

        if price is None or amount is None:
            raise ValueError("Invalid price or amount")

        # Start a new transaction if not already in one
        if not db.in_transaction():
            transaction = db.begin()
        else:
            transaction = None
        
        try:
            market = db.query(Market).filter_by(id=market_id, active=True).first()
            if not market:
                raise ValueError("Market not found")

            base_coin = market.base_coin
            quote_coin = market.quote_coin
            side_enum = OrderSide(side)
            total_quote = price * amount

            if side_enum == OrderSide.buy:
                balance = db.query(Balance).with_for_update().filter_by(
                    user_id=user_id, coin_symbol=quote_coin
                ).first()
                if not balance or balance.available < total_quote:
                    log_security_event("insufficient_balance_order", {
                        "user_id": user_id, "side": side, "market_id": market_id,
                        "required": str(total_quote), "available": str(balance.available) if balance else "0"
                    })
                    raise ValueError("Insufficient quote balance")
                balance.available -= total_quote
                balance.locked += total_quote

            elif side_enum == OrderSide.sell:
                balance = db.query(Balance).with_for_update().filter_by(
                    user_id=user_id, coin_symbol=base_coin
                ).first()
                if not balance or balance.available < amount:
                    log_security_event("insufficient_balance_order", {
                        "user_id": user_id, "side": side, "market_id": market_id,
                        "required": str(amount), "available": str(balance.available) if balance else "0"
                    })
                    raise ValueError("Insufficient base balance")
                balance.available -= amount
                balance.locked += amount

            # Validate balance integrity
            validate_transaction_integrity(db, user_id, balance.coin_symbol)

            # Create and flush order
            new_order = Order(
                user_id=user_id,
                market_id=market_id,
                side=side_enum,
                price=price,
                amount=amount,
                remaining=amount
            )
            db.add(new_order)
            db.flush()

            # Match engine works in this transaction
            trades = match_orders(db, market_id)

            # Commit transaction if we started it
            if transaction:
                transaction.commit()
            else:
                db.commit()

            log_security_event("order_placed", {
                "user_id": user_id, "order_id": new_order.id, "market_id": market_id,
                "side": side, "price": str(price), "amount": str(amount)
            })

            # Return response after successful transaction
            return {
                "order_id": new_order.id,
                "status": new_order.status.value,
                "filled": str(amount - new_order.remaining),
                "remaining": str(new_order.remaining),
                "trades": [{
                    "amount": str(t.amount),
                    "price": str(t.price),
                    "timestamp": t.timestamp.isoformat()
                } for t in trades if t.buy_order_id == new_order.id or t.sell_order_id == new_order.id]
            }
            
        except Exception as tx_error:
            # Rollback if we have an active transaction
            if transaction:
                transaction.rollback()
            else:
                db.rollback()
            raise tx_error
    
    @staticmethod
    def cancel_order(db: Session, user_id: int, order_id: int) -> Dict:
        """
        Cancel an open order.
        
        Args:
            db: Database session
            user_id: User ID
            order_id: Order ID to cancel
            
        Returns:
            Dictionary with cancellation status
            
        Raises:
            ValueError: If order not found or cannot be cancelled
            Exception: If cancellation fails
        """
        # Start a new transaction if not already in one
        if not db.in_transaction():
            transaction = db.begin()
        else:
            transaction = None
        
        try:
            order = db.query(Order).with_for_update().filter_by(
                id=order_id, user_id=user_id
            ).first()

            if not order:
                raise ValueError("Order not found")

            if order.status not in [OrderStatus.open, OrderStatus.partially_filled]:
                raise ValueError(f"Order already {order.status.value}")

            remaining = order.remaining
            market = order.market

            if order.side == OrderSide.buy:
                refund = Decimal(remaining) * Decimal(order.price)
                bal = db.query(Balance).with_for_update().filter_by(
                    user_id=user_id, coin_symbol=market.quote_coin
                ).first()
                if bal:
                    bal.locked -= refund
                    bal.available += refund
                    validate_transaction_integrity(db, user_id, market.quote_coin)

            else:
                bal = db.query(Balance).with_for_update().filter_by(
                    user_id=user_id, coin_symbol=market.base_coin
                ).first()
                if bal:
                    bal.locked -= Decimal(remaining)
                    bal.available += Decimal(remaining)
                    validate_transaction_integrity(db, user_id, market.base_coin)

            order.status = OrderStatus.cancelled
            
            # Commit transaction if we started it
            if transaction:
                transaction.commit()
            else:
                db.commit()
            
            log_security_event("order_cancelled", {
                "user_id": user_id, "order_id": order.id, "market_id": order.market_id
            })

            return {"status": "cancelled", "order_id": order.id}
            
        except Exception as tx_error:
            # Rollback if we have an active transaction
            if transaction:
                transaction.rollback()
            else:
                db.rollback()
            raise tx_error
    
    @staticmethod
    def get_open_orders(
        db: Session, 
        user_id: int, 
        coin_filter: Optional[str] = None,
        market_id: Optional[int] = None
    ) -> List[Dict]:
        """
        Get all open orders for a user.
        
        Args:
            db: Database session
            user_id: User ID
            coin_filter: Optional coin symbol to filter by
            market_id: Optional market ID to filter by
            
        Returns:
            List of order dictionaries
            
        Raises:
            ValueError: If filters are invalid
        """
        if coin_filter and not SecurityValidator.validate_coin_symbol(coin_filter):
            raise ValueError("Invalid coin symbol")

        query = db.query(Order).join(Market).filter(
            Order.user_id == user_id,
            Order.status.in_([OrderStatus.open, OrderStatus.partially_filled])
        )

        if market_id:
            query = query.filter(Order.market_id == market_id)
        elif coin_filter:
            query = query.filter(
                (Market.base_coin == coin_filter) | (Market.quote_coin == coin_filter)
            )

        query = query.order_by(Order.created_at.desc()).limit(100)
        orders = query.all()

        return [{
            "order_id": o.id,
            "market": f"{o.market.base_coin}/{o.market.quote_coin}",
            "side": o.side.value,
            "price": str(o.price),
            "amount": str(o.amount),
            "remaining": str(o.remaining),
            "status": o.status.value,
        } for o in orders]
