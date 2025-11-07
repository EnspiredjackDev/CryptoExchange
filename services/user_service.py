"""
UserService - Handles user account operations, address generation, and balance management.
"""

from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from models import User, Address, Balance
from utils import generate_api_key, hash_api_key, validate_transaction_integrity
from coinNodes import get_node
from security import log_security_event, SecurityValidator

logger = logging.getLogger(__name__)


class UserService:
    """Service class for user-related operations."""
    
    @staticmethod
    def create_account(db: Session) -> Tuple[str, int]:
        """
        Create a new user account.
        
        Args:
            db: Database session
            
        Returns:
            Tuple of (api_key, user_id)
            
        Raises:
            Exception: If account creation fails
        """
        if not db.in_transaction():
            db.begin()
        
        raw_key = generate_api_key()
        hashed_key = hash_api_key(raw_key)

        user = User(api_key_hash=hashed_key)
        db.add(user)
        db.flush()  # Get user.id
        db.commit()
        
        log_security_event("account_created", {"user_id": user.id})
        return raw_key, user.id
    
    @staticmethod
    def generate_address(db: Session, user_id: int, coin: str) -> Dict[str, str]:
        """
        Generate a new deposit address for a user.
        
        Args:
            db: Database session
            user_id: User ID
            coin: Coin symbol (uppercase)
            
        Returns:
            Dictionary with address and coin information
            
        Raises:
            ValueError: If coin symbol is invalid
            Exception: If address generation fails
        """
        if not SecurityValidator.validate_coin_symbol(coin):
            log_security_event("invalid_coin_symbol", {"coin": coin, "user_id": user_id})
            raise ValueError("Invalid coin symbol")
        
        if not db.in_transaction():
            db.begin()
        
        if coin == "XMR":
            node = get_node(coin)
            label = f"user_{user_id}"
            result = node.create_subaddress(account_index=0, label=label)

            # Check for duplicates
            exists = db.query(Address).filter_by(
                address=result["address"], 
                coin_symbol="XMR"
            ).first()
            if exists:
                db.rollback()
                logger.error(f"Duplicate XMR address generated: {result['address']}")
                raise Exception("Generated address already exists. Please retry.")

            addr = Address(
                user_id=user_id,
                address=result["address"],
                coin_symbol="XMR",
                extra_info={"address_index": result["address_index"]}
            )
            db.add(addr)
            db.commit()
            return {"address": addr.address, "coin": "XMR"}
        else:
            node = get_node(coin)
            attempts = 0
            max_attempts = 5
            new_address = None

            while attempts < max_attempts:
                candidate_address = node.get_new_address()
                exists = db.query(Address).filter_by(
                    address=candidate_address, 
                    coin_symbol=coin
                ).first()
                if not exists:
                    new_address = candidate_address
                    break
                attempts += 1

            if not new_address:
                db.rollback()
                logger.error(f"Failed to generate unique address for {coin} after {max_attempts} attempts")
                raise Exception("Failed to generate a unique address after several attempts")

            addr = Address(
                user_id=user_id,
                address=new_address,
                coin_symbol=coin
            )
            db.add(addr)
            db.commit()

            return {"coin": coin, "address": new_address}
    
    @staticmethod
    def list_addresses(db: Session, user_id: int, coin_filter: Optional[str] = None) -> List[Dict]:
        """
        List all addresses for a user.
        
        Args:
            db: Database session
            user_id: User ID
            coin_filter: Optional coin symbol to filter by
            
        Returns:
            List of address dictionaries
            
        Raises:
            ValueError: If coin filter is invalid
        """
        if coin_filter and not SecurityValidator.validate_coin_symbol(coin_filter.upper()):
            raise ValueError("Invalid coin symbol")

        query = db.query(Address).filter_by(user_id=user_id)
        if coin_filter:
            query = query.filter(Address.coin_symbol == coin_filter.upper())

        addresses = query.order_by(Address.created_at.desc()).limit(100).all()

        return [{
            "address": a.address,
            "coin": a.coin_symbol,
            "created_at": a.created_at.isoformat()
        } for a in addresses]
    
    @staticmethod
    def get_balances(db: Session, user_id: int, coin_filter: Optional[str] = None) -> Dict[str, Dict]:
        """
        Get user balances for all coins or a specific coin.
        
        Args:
            db: Database session
            user_id: User ID
            coin_filter: Optional coin symbol to filter by
            
        Returns:
            Dictionary mapping coin symbols to balance information
            
        Raises:
            ValueError: If coin filter is invalid
        """
        if coin_filter and not SecurityValidator.validate_coin_symbol(coin_filter.upper()):
            raise ValueError("Invalid coin symbol")

        balances_query = db.query(Balance).filter_by(user_id=user_id)
        if coin_filter:
            balances_query = balances_query.filter(Balance.coin_symbol == coin_filter.upper())

        result = {}
        for b in balances_query.all():
            # Validate balance integrity
            try:
                validate_transaction_integrity(db, user_id, b.coin_symbol)
            except Exception as integrity_error:
                logger.error(f"Balance integrity error for user {user_id}: {integrity_error}")
                # Continue but log the issue
            
            result[b.coin_symbol] = {
                "available": str(b.available),
                "locked": str(b.locked),
                "total": str(b.total)
            }

        return result
