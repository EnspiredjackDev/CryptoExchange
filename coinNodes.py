import os
import logging
from crypto_node import CryptoNode, MoneroNode
from db import SessionLocal
from models import CoinNode as CoinNodeModel

logger = logging.getLogger(__name__)

# Cache for loaded nodes to avoid repeated database queries
_node_cache = {}


def get_node(coin_symbol: str):
    """
    Get a cryptocurrency node instance for the given coin symbol.
    Checks database first, then falls back to environment variables.
    
    Args:
        coin_symbol: The symbol of the cryptocurrency (e.g., 'BTC', 'XMR')
        
    Returns:
        CryptoNode or MoneroNode instance
        
    Raises:
        Exception: If node configuration is not found or incomplete
    """
    coin = coin_symbol.upper()
    
    # Check cache first
    if coin in _node_cache:
        return _node_cache[coin]
    
    # Try to get configuration from database
    db = SessionLocal()
    try:
        coin_config = db.query(CoinNodeModel).filter_by(
            coin_symbol=coin,
            enabled=True
        ).first()
        
        if coin_config:
            logger.info(f"Loading {coin} node from database configuration")
            node = _create_node_from_config(coin_config)
            _node_cache[coin] = node
            return node
    except Exception as e:
        logger.warning(f"Failed to load {coin} from database: {e}")
    finally:
        db.close()
    
    # Fallback to environment variables
    logger.info(f"Loading {coin} node from environment variables")
    host = os.environ.get(f"{coin}_NODE_HOST")
    port = os.environ.get(f"{coin}_NODE_PORT")
    username = os.environ.get(f"{coin}_NODE_USER")
    password = os.environ.get(f"{coin}_NODE_PASS")
    node_type = os.environ.get(f"{coin}_NODE_TYPE", "btc").lower()

    if not all([host, port, username, password]):
        raise Exception(f"Missing credentials for {coin}. Configure in database or environment variables.")

    if node_type == "monero":
        node = MoneroNode(host, int(port), username, password)
    else:
        node = CryptoNode(host, int(port), username, password)
    
    _node_cache[coin] = node
    return node


def _create_node_from_config(config: CoinNodeModel):
    """Create a node instance from database configuration."""
    if config.node_type.lower() == "monero":
        return MoneroNode(
            config.node_host,
            config.node_port,
            config.node_user,
            config.node_pass
        )
    else:
        return CryptoNode(
            config.node_host,
            config.node_port,
            config.node_user,
            config.node_pass
        )


def clear_node_cache(coin_symbol: str = None):
    """
    Clear the node cache. Used when node configuration is updated.
    
    Args:
        coin_symbol: Specific coin to clear, or None to clear all
    """
    global _node_cache
    if coin_symbol:
        coin = coin_symbol.upper()
        if coin in _node_cache:
            del _node_cache[coin]
            logger.info(f"Cleared cache for {coin} node")
    else:
        _node_cache.clear()
        logger.info("Cleared all node cache")


def reload_node(coin_symbol: str):
    """
    Reload a specific node configuration from the database.
    
    Args:
        coin_symbol: The coin symbol to reload
        
    Returns:
        The reloaded node instance
    """
    clear_node_cache(coin_symbol)
    return get_node(coin_symbol)

