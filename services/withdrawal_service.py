"""
WithdrawalService - Handles cryptocurrency withdrawal operations.
"""

from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Dict
from sqlalchemy import text
from sqlalchemy.orm import Session

from models import Balance, Transaction
from utils import validate_transaction_integrity
from coinNodes import get_node
from security import log_security_event, SecurityValidator

logger = logging.getLogger(__name__)


class WithdrawalService:
    """Service class for withdrawal operations."""
    
    @staticmethod
    def withdraw(
        db: Session,
        user_id: int,
        coin: str,
        to_address: str,
        amount: Decimal
    ) -> Dict:
        """
        Process a cryptocurrency withdrawal.
        
        Args:
            db: Database session
            user_id: User ID
            coin: Coin symbol (uppercase)
            to_address: Destination address
            amount: Amount to withdraw
            
        Returns:
            Dictionary with withdrawal information including txid
            
        Raises:
            ValueError: If inputs are invalid or insufficient balance
            Exception: If withdrawal fails
        """
        # Validate inputs
        if not SecurityValidator.validate_coin_symbol(coin):
            log_security_event("invalid_withdrawal_coin", {"coin": coin, "user_id": user_id})
            raise ValueError("Invalid coin symbol")
        
        if not SecurityValidator.validate_address(to_address, coin):
            log_security_event("invalid_withdrawal_address", {
                "address": to_address[:20] + "...", 
                "coin": coin, 
                "user_id": user_id
            })
            raise ValueError("Invalid withdrawal address")

        if amount is None:
            raise ValueError("Invalid amount")

        # Use special transaction isolation for withdrawals
        if not db.in_transaction():
            # Start transaction with REPEATABLE READ isolation level
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            db.begin()
        
        # Fetch balance with row lock
        balance = db.query(Balance).with_for_update().filter_by(
            user_id=user_id, 
            coin_symbol=coin
        ).first()
        
        if not balance or balance.available < amount:
            db.rollback()
            log_security_event("insufficient_balance_withdrawal", {
                "coin": coin, "requested": str(amount), 
                "available": str(balance.available) if balance else "0",
                "user_id": user_id
            })
            raise ValueError("Insufficient available balance")

        # Deduct funds BEFORE sending (fail-safe approach)
        balance.available -= amount
        balance.total -= amount
        
        # Validate balance integrity after deduction
        validate_transaction_integrity(db, user_id, coin)
        
        db.flush()  # Ensure changes are persisted before external call

        try:
            node = get_node(coin)
            is_monero = node.__class__.__name__.lower() == "moneronode"

            if is_monero:
                # Convert to atomic
                amount_atomic = int(amount * Decimal("1e12"))
                tx_result = node.send_to_address(to_address, amount_atomic)
                txid = tx_result.get("tx_hash")
                if not txid:
                    raise Exception("Monero node did not return tx_hash")
            else:
                # BTC-like coins
                txid = node.send_to_address(to_address, format(amount, "f"))
                if not txid:
                    raise Exception("Node did not return txid")

            # Log the withdrawal
            new_tx = Transaction(
                user_id=user_id,
                tx_id=txid,
                amount=amount,
                direction='sent',
                coin_symbol=coin,
                created_at=datetime.now(timezone.utc)
            )
            db.add(new_tx)
            db.commit()
            
            log_security_event("withdrawal_completed", {
                "user_id": user_id, "coin": coin, "amount": str(amount),
                "txid": txid, "to_address": to_address[:20] + "..."
            })

            return {
                "status": "success",
                "txid": txid,
                "amount": str(amount),
                "coin": coin
            }

        except Exception as node_error:
            # Refund the user if blockchain transaction failed
            balance.available += amount
            balance.total += amount
            db.flush()
            db.rollback()
            
            log_security_event("withdrawal_failed", {
                "user_id": user_id, "coin": coin, "amount": str(amount),
                "error": str(node_error), "to_address": to_address[:20] + "..."
            })
            
            logger.error(f"Withdrawal transaction failed for user {user_id}: {node_error}")
            raise Exception(f"Withdrawal failed: {str(node_error)}")
