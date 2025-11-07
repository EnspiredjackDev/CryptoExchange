"""
AdminService - Handles admin-only operations like market creation and fee management.
"""

from decimal import Decimal
import logging
from typing import Dict
from sqlalchemy.orm import Session

from models import Market, FeeBalance
from security import log_security_event, SecurityValidator

logger = logging.getLogger(__name__)


class AdminService:
    """Service class for admin-only operations."""
    
    @staticmethod
    def create_market(db: Session, base_coin: str, quote_coin: str) -> Dict:
        """
        Create a new trading market.
        
        Args:
            db: Database session
            base_coin: Base coin symbol (e.g., BTC)
            quote_coin: Quote coin symbol (e.g., USD)
            
        Returns:
            Dictionary with market information
            
        Raises:
            ValueError: If inputs are invalid or market already exists
        """
        if not SecurityValidator.validate_coin_symbol(base_coin) or \
           not SecurityValidator.validate_coin_symbol(quote_coin):
            raise ValueError("Invalid coin symbols")

        if base_coin == quote_coin:
            raise ValueError("Base and quote cannot be the same")

        # Start a new transaction if not already in one
        if not db.in_transaction():
            transaction = db.begin()
        else:
            transaction = None
        
        try:
            # Check if market already exists
            existing = db.query(Market).filter_by(
                base_coin=base_coin, 
                quote_coin=quote_coin
            ).first()
            
            if existing:
                raise ValueError(f"Market already exists (ID: {existing.id})")

            new_market = Market(
                base_coin=base_coin,
                quote_coin=quote_coin,
                active=True
            )
            db.add(new_market)
            db.flush()
            
            # Commit transaction if we started it
            if transaction:
                transaction.commit()
            else:
                db.commit()
            
            log_security_event("market_created", {
                "market_id": new_market.id, 
                "base_coin": base_coin, 
                "quote_coin": quote_coin
            })

            return {
                "market_id": new_market.id,
                "base_coin": base_coin,
                "quote_coin": quote_coin,
                "status": "created"
            }
            
        except Exception as tx_error:
            # Rollback if we have an active transaction
            if transaction:
                transaction.rollback()
            else:
                db.rollback()
            raise tx_error
    
    @staticmethod
    def get_fee_balances(db: Session) -> Dict[str, str]:
        """
        Get all fee balances.
        
        Args:
            db: Database session
            
        Returns:
            Dictionary mapping coin symbols to fee amounts
        """
        fees = db.query(FeeBalance).all()
        return {f.coin_symbol: str(f.amount) for f in fees}
    
    @staticmethod
    def withdraw_fees(db: Session, coin: str, amount: Decimal) -> Dict:
        """
        Withdraw accumulated fees.
        
        Args:
            db: Database session
            coin: Coin symbol
            amount: Amount to withdraw
            
        Returns:
            Dictionary with withdrawal information
            
        Raises:
            ValueError: If inputs are invalid or insufficient fee balance
        """
        if not SecurityValidator.validate_coin_symbol(coin):
            raise ValueError("Invalid coin symbol")

        if amount is None or amount < 0:
            raise ValueError("Invalid amount")

        if not db.in_transaction():
            db.begin()
        
        fb = db.query(FeeBalance).filter_by(coin_symbol=coin).first()
        if not fb or fb.amount < amount:
            db.rollback()
            raise ValueError("Insufficient fee balance")

        fb.amount -= amount
        db.commit()
        
        log_security_event("fee_withdrawal", {
            "coin": coin, 
            "amount": str(amount), 
            "remaining": str(fb.amount)
        })

        return {
            "coin": coin,
            "withdrawn": str(amount),
            "remaining": str(fb.amount)
        }
