"""
CoinNodeService - Handles coin node configuration management.
"""

from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from models import CoinNode
from security import log_security_event, SecurityValidator
from coinNodes import clear_node_cache, reload_node

logger = logging.getLogger(__name__)


class CoinNodeService:
    """Service class for coin node configuration operations."""
    
    @staticmethod
    def add_coin_node(
        db: Session,
        coin_symbol: str,
        coin_name: str,
        node_host: str,
        node_port: int,
        node_user: str,
        node_pass: str,
        node_type: str = 'btc',
        network_name: Optional[str] = None,
        block_time: Optional[str] = None,
        confirmations: int = 6,
        address_format: Optional[str] = None,
        default_fee: Optional[str] = None
    ) -> Dict:
        """
        Add a new coin node configuration.
        
        Args:
            db: Database session
            coin_symbol: Coin symbol (e.g., 'BTC')
            coin_name: Full coin name (e.g., 'Bitcoin')
            node_host: Node RPC host
            node_port: Node RPC port
            node_user: Node RPC username
            node_pass: Node RPC password
            node_type: Node type ('btc' or 'monero')
            network_name: Network name
            block_time: Average block time
            confirmations: Required confirmations
            address_format: Address format description
            default_fee: Default fee estimate
            
        Returns:
            Dictionary with node information
            
        Raises:
            ValueError: If inputs are invalid or node already exists
        """
        # Validate inputs
        coin_symbol = coin_symbol.upper()
        
        if not SecurityValidator.validate_coin_symbol(coin_symbol):
            raise ValueError("Invalid coin symbol")
        
        if node_type.lower() not in ['btc', 'monero']:
            raise ValueError("node_type must be 'btc' or 'monero'")
        
        if not all([coin_name, node_host, node_user, node_pass]):
            raise ValueError("Missing required fields")
        
        if node_port < 1 or node_port > 65535:
            raise ValueError("Invalid port number")
        
        # Start transaction
        if not db.in_transaction():
            transaction = db.begin()
        else:
            transaction = None
        
        try:
            # Check if already exists
            existing = db.query(CoinNode).filter_by(coin_symbol=coin_symbol).first()
            if existing:
                raise ValueError(f"Coin node for {coin_symbol} already exists")
            
            # Create new node configuration
            new_node = CoinNode(
                coin_symbol=coin_symbol,
                coin_name=coin_name,
                node_host=node_host,
                node_port=node_port,
                node_user=node_user,
                node_pass=node_pass,
                node_type=node_type.lower(),
                network_name=network_name or coin_name,
                block_time=block_time or "Variable",
                confirmations=confirmations,
                address_format=address_format,
                default_fee=default_fee or "0.0001",
                enabled=True
            )
            
            db.add(new_node)
            db.flush()
            
            # Commit if we started the transaction
            if transaction:
                transaction.commit()
            else:
                db.commit()
            
            # Clear cache to force reload
            clear_node_cache(coin_symbol)
            
            log_security_event("coin_node_added", {
                "coin_symbol": coin_symbol,
                "coin_name": coin_name,
                "node_type": node_type
            })
            
            return CoinNodeService._node_to_dict(new_node)
            
        except Exception as tx_error:
            if transaction:
                transaction.rollback()
            else:
                db.rollback()
            raise tx_error
    
    @staticmethod
    def update_coin_node(
        db: Session,
        coin_symbol: str,
        **updates
    ) -> Dict:
        """
        Update an existing coin node configuration.
        
        Args:
            db: Database session
            coin_symbol: Coin symbol to update
            **updates: Fields to update
            
        Returns:
            Dictionary with updated node information
            
        Raises:
            ValueError: If node not found or invalid updates
        """
        coin_symbol = coin_symbol.upper()
        
        if not db.in_transaction():
            transaction = db.begin()
        else:
            transaction = None
        
        try:
            node = db.query(CoinNode).filter_by(coin_symbol=coin_symbol).first()
            if not node:
                raise ValueError(f"Coin node for {coin_symbol} not found")
            
            # Update allowed fields
            allowed_fields = [
                'coin_name', 'node_host', 'node_port', 'node_user', 'node_pass',
                'node_type', 'network_name', 'block_time', 'confirmations',
                'address_format', 'default_fee', 'enabled'
            ]
            
            for field, value in updates.items():
                if field in allowed_fields and value is not None:
                    setattr(node, field, value)
            
            node.updated_at = datetime.now(timezone.utc)
            db.flush()
            
            if transaction:
                transaction.commit()
            else:
                db.commit()
            
            # Clear cache to force reload
            clear_node_cache(coin_symbol)
            
            log_security_event("coin_node_updated", {
                "coin_symbol": coin_symbol,
                "updated_fields": list(updates.keys())
            })
            
            return CoinNodeService._node_to_dict(node)
            
        except Exception as tx_error:
            if transaction:
                transaction.rollback()
            else:
                db.rollback()
            raise tx_error
    
    @staticmethod
    def get_coin_node(db: Session, coin_symbol: str) -> Dict:
        """
        Get a single coin node configuration.
        
        Args:
            db: Database session
            coin_symbol: Coin symbol
            
        Returns:
            Dictionary with node information
            
        Raises:
            ValueError: If node not found
        """
        coin_symbol = coin_symbol.upper()
        node = db.query(CoinNode).filter_by(coin_symbol=coin_symbol).first()
        
        if not node:
            raise ValueError(f"Coin node for {coin_symbol} not found")
        
        return CoinNodeService._node_to_dict(node, include_sensitive=False)
    
    @staticmethod
    def list_coin_nodes(db: Session, include_disabled: bool = False) -> List[Dict]:
        """
        List all coin node configurations.
        
        Args:
            db: Database session
            include_disabled: Whether to include disabled nodes
            
        Returns:
            List of node dictionaries
        """
        query = db.query(CoinNode)
        
        if not include_disabled:
            query = query.filter_by(enabled=True)
        
        nodes = query.order_by(CoinNode.coin_symbol).all()
        
        return [CoinNodeService._node_to_dict(node, include_sensitive=False) for node in nodes]
    
    @staticmethod
    def delete_coin_node(db: Session, coin_symbol: str) -> Dict:
        """
        Delete a coin node configuration.
        
        Args:
            db: Database session
            coin_symbol: Coin symbol to delete
            
        Returns:
            Dictionary with deletion confirmation
            
        Raises:
            ValueError: If node not found
        """
        coin_symbol = coin_symbol.upper()
        
        if not db.in_transaction():
            transaction = db.begin()
        else:
            transaction = None
        
        try:
            node = db.query(CoinNode).filter_by(coin_symbol=coin_symbol).first()
            if not node:
                raise ValueError(f"Coin node for {coin_symbol} not found")
            
            db.delete(node)
            db.flush()
            
            if transaction:
                transaction.commit()
            else:
                db.commit()
            
            # Clear cache
            clear_node_cache(coin_symbol)
            
            log_security_event("coin_node_deleted", {
                "coin_symbol": coin_symbol
            })
            
            return {
                "coin_symbol": coin_symbol,
                "status": "deleted"
            }
            
        except Exception as tx_error:
            if transaction:
                transaction.rollback()
            else:
                db.rollback()
            raise tx_error
    
    @staticmethod
    def enable_coin_node(db: Session, coin_symbol: str) -> Dict:
        """Enable a coin node."""
        return CoinNodeService.update_coin_node(db, coin_symbol, enabled=True)
    
    @staticmethod
    def disable_coin_node(db: Session, coin_symbol: str) -> Dict:
        """Disable a coin node."""
        return CoinNodeService.update_coin_node(db, coin_symbol, enabled=False)
    
    @staticmethod
    def test_coin_node(db: Session, coin_symbol: str) -> Dict:
        """
        Test connection to a coin node.
        
        Args:
            db: Database session
            coin_symbol: Coin symbol to test
            
        Returns:
            Dictionary with test results
        """
        coin_symbol = coin_symbol.upper()
        
        try:
            # Try to get/reload the node
            node = reload_node(coin_symbol)
            
            # Test basic connectivity
            if hasattr(node, 'get_info'):
                info = node.get_info()
                return {
                    "coin_symbol": coin_symbol,
                    "status": "connected",
                    "node_info": info
                }
            else:
                return {
                    "coin_symbol": coin_symbol,
                    "status": "connected",
                    "message": "Node loaded successfully"
                }
                
        except Exception as e:
            logger.error(f"Failed to test {coin_symbol} node: {e}")
            return {
                "coin_symbol": coin_symbol,
                "status": "error",
                "error": str(e)
            }
    
    @staticmethod
    def _node_to_dict(node: CoinNode, include_sensitive: bool = False) -> Dict:
        """Convert a CoinNode model to a dictionary."""
        result = {
            "id": node.id,
            "coin_symbol": node.coin_symbol,
            "coin_name": node.coin_name,
            "node_host": node.node_host,
            "node_port": node.node_port,
            "node_user": node.node_user,
            "node_type": node.node_type,
            "network_name": node.network_name,
            "block_time": node.block_time,
            "confirmations": node.confirmations,
            "address_format": node.address_format,
            "default_fee": node.default_fee,
            "enabled": node.enabled,
            "created_at": node.created_at.isoformat() if node.created_at else None,
            "updated_at": node.updated_at.isoformat() if node.updated_at else None
        }
        
        if include_sensitive:
            result["node_pass"] = node.node_pass
        else:
            result["node_pass"] = "***HIDDEN***"
        
        return result
