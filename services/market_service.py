"""
MarketService - Handles market data, orderbook, and trade history operations.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
import os
from typing import Dict, List, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Market, Order, OrderSide, OrderStatus, Trade, Transaction
from security import SecurityValidator

logger = logging.getLogger(__name__)


class MarketService:
    """Service class for market-related operations."""
    
    @staticmethod
    def get_orderbook(db: Session, market_id: int, depth: int = 10) -> Dict:
        """
        Get the order book for a specific market.
        
        Args:
            db: Database session
            market_id: Market ID
            depth: Number of price levels to return (default 10, max 100)
            
        Returns:
            Dictionary with bids and asks
            
        Raises:
            ValueError: If market not found or invalid depth
        """
        if depth <= 0 or depth > 100:
            raise ValueError("Depth must be between 1 and 100")

        market = db.query(Market).filter_by(id=market_id, active=True).first()
        if not market:
            raise ValueError("Market not found")

        # Bids (buys): highest price first
        bids = db.query(Order).filter_by(
            market_id=market_id,
            side=OrderSide.buy
        ).filter(Order.status.in_([OrderStatus.open, OrderStatus.partially_filled])
        ).order_by(Order.price.desc()).limit(depth * 10).all()

        # Asks (sells): lowest price first
        asks = db.query(Order).filter_by(
            market_id=market_id,
            side=OrderSide.sell
        ).filter(Order.status.in_([OrderStatus.open, OrderStatus.partially_filled])
        ).order_by(Order.price.asc()).limit(depth * 10).all()

        # Aggregate by price
        def aggregate(orders, reverse=False):
            price_levels = {}
            for order in orders:
                p = str(order.price)
                a = float(order.remaining)
                price_levels[p] = price_levels.get(p, 0.0) + a
            sorted_levels = sorted(price_levels.items(), key=lambda x: float(x[0]), reverse=reverse)
            return [{"price": p, "amount": round(a, 8)} for p, a in sorted_levels[:depth]]

        return {
            "market": f"{market.base_coin}/{market.quote_coin}",
            "bids": aggregate(bids, reverse=True),
            "asks": aggregate(asks, reverse=False)
        }
    
    @staticmethod
    def get_markets(db: Session) -> List[Dict]:
        """
        Get all active markets with statistics.
        
        Args:
            db: Database session
            
        Returns:
            List of market dictionaries with statistics
        """
        markets = db.query(Market).filter_by(active=True).all()
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=24)

        result = []

        for m in markets:
            # Last trade
            last_trade = db.query(Trade).filter_by(
                market_id=m.id
            ).order_by(Trade.timestamp.desc()).first()

            # 24h volume and trade count
            trade_stats = db.query(
                func.coalesce(func.sum(Trade.amount), 0),
                func.count(Trade.id)
            ).filter(
                Trade.market_id == m.id,
                Trade.timestamp >= since
            ).first()
            volume_24h, trade_count_24h = trade_stats

            # Best bid and ask
            best_bid = db.query(Order).filter_by(
                market_id=m.id,
                side=OrderSide.buy
            ).filter(Order.status.in_([OrderStatus.open, OrderStatus.partially_filled])
            ).order_by(Order.price.desc()).first()

            best_ask = db.query(Order).filter_by(
                market_id=m.id,
                side=OrderSide.sell
            ).filter(Order.status.in_([OrderStatus.open, OrderStatus.partially_filled])
            ).order_by(Order.price.asc()).first()

            # 24h price change %
            open_trade = db.query(Trade).filter(
                Trade.market_id == m.id,
                Trade.timestamp >= since
            ).order_by(Trade.timestamp.asc()).first()

            last_price = float(last_trade.price) if last_trade else None
            open_price = float(open_trade.price) if open_trade else None

            change_24h = None
            if last_price is not None and open_price and open_price != 0:
                change_24h = round(((last_price - open_price) / open_price) * 100, 2)

            result.append({
                "market_id": m.id,
                "base_coin": m.base_coin,
                "quote_coin": m.quote_coin,
                "fee_rate": str(m.fee_rate),
                "label": f"{m.base_coin}/{m.quote_coin}",
                "last_price": last_price,
                "volume_24h": str(volume_24h),
                "trade_count_24h": trade_count_24h,
                "best_bid": str(best_bid.price) if best_bid else None,
                "best_ask": str(best_ask.price) if best_ask else None,
                "change_24h": change_24h
            })

        return result
    
    @staticmethod
    def get_trade_history(
        db: Session,
        user_id: int,
        coin_filter: Optional[str] = None,
        market_id: Optional[int] = None,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get trade history for a user.
        
        Args:
            db: Database session
            user_id: User ID
            coin_filter: Optional coin symbol to filter by
            market_id: Optional market ID to filter by
            limit: Maximum number of trades to return (max 200)
            
        Returns:
            List of trade dictionaries
            
        Raises:
            ValueError: If filters are invalid
        """
        if coin_filter and not SecurityValidator.validate_coin_symbol(coin_filter):
            raise ValueError("Invalid coin symbol")

        if limit <= 0 or limit > 200:
            raise ValueError("Limit must be between 1 and 200")

        q = db.query(Trade).join(Market).filter(
            (Trade.buy_order.has(user_id=user_id)) |
            (Trade.sell_order.has(user_id=user_id))
        )

        if market_id:
            q = q.filter(Trade.market_id == market_id)
        elif coin_filter:
            q = q.filter(
                (Market.base_coin == coin_filter) | (Market.quote_coin == coin_filter)
            )

        trades = q.order_by(Trade.timestamp.desc()).limit(limit).all()

        return [
            {
                "market": f"{t.market.base_coin}/{t.market.quote_coin}",
                "price": str(t.price),
                "amount": str(t.amount),
                "side": (
                    "buy" if t.buy_order.user_id == user_id else "sell"
                ),
                "order_status": (
                    t.buy_order.status.value if t.buy_order.user_id == user_id
                    else t.sell_order.status.value
                ),
                "timestamp": t.timestamp.isoformat()
            } for t in trades
        ]
    
    @staticmethod
    def get_supported_coins(db: Session) -> Dict:
        """
        Get list of supported cryptocurrencies and their network information.
        Queries the database for coin node configurations.
        
        Args:
            db: Database session
            
        Returns:
            Dictionary with supported coins information
        """
        from models import CoinNode
        
        supported_coins = {}
        
        # Get all enabled coin nodes from database
        coin_nodes = db.query(CoinNode).filter_by(enabled=True).all()
        
        for coin_config in coin_nodes:
            coin_symbol = coin_config.coin_symbol
            node_type = coin_config.node_type
            
            # Calculate average fee
            avg_fee = MarketService._calculate_average_fee(db, coin_symbol, node_type)
            
            # Try to test node connectivity
            try:
                from coinNodes import get_node
                node = get_node(coin_symbol)
                
                node_info = {
                    "symbol": coin_symbol,
                    "name": coin_config.coin_name,
                    "node_type": node_type,
                    "network_info": {
                        "network": coin_config.network_name or coin_config.coin_name,
                        "confirmations": str(coin_config.confirmations),
                        "typical_fee": avg_fee,
                        "block_time": coin_config.block_time or "Variable",
                        "address_format": coin_config.address_format or f"{coin_symbol} address format"
                    },
                    "status": "online"
                }
                
                # Test basic connectivity
                if hasattr(node, 'get_info'):
                    try:
                        node.get_info()
                    except:
                        node_info["status"] = "connection_error"
                
                supported_coins[coin_symbol] = node_info
                
            except Exception as e:
                # Add coin even if node connection fails
                supported_coins[coin_symbol] = {
                    "symbol": coin_symbol,
                    "name": coin_config.coin_name,
                    "node_type": node_type,
                    "network_info": {
                        "network": coin_config.network_name or coin_config.coin_name,
                        "confirmations": str(coin_config.confirmations),
                        "typical_fee": avg_fee,
                        "block_time": coin_config.block_time or "Variable",
                        "address_format": coin_config.address_format or f"{coin_symbol} address format"
                    },
                    "status": "configuration_error",
                    "error": str(e)
                }
        
        # Fallback: Also check environment variables for any coins not in database
        env_coins = MarketService._get_env_coins(db, supported_coins)
        supported_coins.update(env_coins)
        
        return {
            "supported_coins": supported_coins,
            "total_count": len(supported_coins),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    @staticmethod
    def _get_env_coins(db: Session, existing_coins: Dict) -> Dict:
        """Get coin configurations from environment variables (fallback)."""
        env_coins = {}
        
        for key in os.environ:
            if key.endswith('_NODE_HOST'):
                coin_symbol = key.replace('_NODE_HOST', '')
                
                # Skip if already in database
                if coin_symbol in existing_coins:
                    continue
                
                # Check if all required environment variables exist for this coin
                host = os.environ.get(f"{coin_symbol}_NODE_HOST")
                port = os.environ.get(f"{coin_symbol}_NODE_PORT")
                username = os.environ.get(f"{coin_symbol}_NODE_USER")
                password = os.environ.get(f"{coin_symbol}_NODE_PASS")
                node_type = os.environ.get(f"{coin_symbol}_NODE_TYPE", "btc").lower()
                
                if not all([host, port, username, password]):
                    continue
                
                # Get metadata from environment variables
                coin_name = os.environ.get(f"{coin_symbol}_NAME", coin_symbol)
                block_time = os.environ.get(f"{coin_symbol}_BLOCK_TIME", "Variable")
                confirmations = os.environ.get(f"{coin_symbol}_CONFIRMATIONS", "6")
                address_format = os.environ.get(f"{coin_symbol}_ADDRESS_FORMAT", f"{coin_symbol} address format")
                network_name = os.environ.get(f"{coin_symbol}_NETWORK", coin_name)
                
                # Calculate average fee
                avg_fee = MarketService._calculate_average_fee(db, coin_symbol, node_type)
                
                # Try to get additional info by testing the node connection
                try:
                    from coinNodes import get_node
                    node = get_node(coin_symbol)
                    
                    node_info = {
                        "symbol": coin_symbol,
                        "name": coin_name,
                        "node_type": node_type,
                        "network_info": {
                            "network": network_name,
                            "confirmations": confirmations,
                            "typical_fee": avg_fee,
                            "block_time": block_time,
                            "address_format": address_format
                        },
                        "status": "online",
                        "source": "environment"
                    }
                    
                    # Test basic connectivity
                    if hasattr(node, 'get_info'):
                        try:
                            node.get_info()
                        except:
                            node_info["status"] = "connection_error"
                    
                    env_coins[coin_symbol] = node_info
                    
                except Exception as e:
                    # Add coin even if node connection fails
                    env_coins[coin_symbol] = {
                        "symbol": coin_symbol,
                        "name": coin_name,
                        "node_type": node_type,
                        "network_info": {
                            "network": network_name,
                            "confirmations": confirmations,
                            "typical_fee": avg_fee,
                            "block_time": block_time,
                            "address_format": address_format
                        },
                        "status": "configuration_error",
                        "source": "environment",
                        "error": str(e)
                    }
        
        return env_coins
    
    @staticmethod
    def _calculate_average_fee(db: Session, coin_symbol: str, node_type: str) -> str:
        """Calculate average transaction fee from actual transactions and node estimates."""
        try:
            # First, try to get real-time fee estimates from the node
            try:
                from coinNodes import get_node
                node = get_node(coin_symbol)
                
                if node_type == "monero":
                    return f"~0.0001 {coin_symbol} (dynamic)"
                else:
                    # For Bitcoin-like coins, try to get network fee estimate
                    try:
                        fee_per_kb = node._rpc_request("estimatesmartfee", [6])
                        if fee_per_kb and 'feerate' in fee_per_kb:
                            fee_rate = float(fee_per_kb['feerate'])
                            if fee_rate > 0:
                                typical_fee = fee_rate * 0.25
                                return f"~{typical_fee:.6f} {coin_symbol} (network estimate)"
                    except Exception as e:
                        logger.debug(f"Network fee estimate failed for {coin_symbol}: {e}")
                        
                        try:
                            network_info = node._rpc_request("getnetworkinfo")
                            if network_info:
                                return f"~0.0001 {coin_symbol} (connected)"
                        except:
                            pass
                            
            except Exception as e:
                logger.debug(f"Node fee estimation failed for {coin_symbol}: {e}")
            
            # Fallback: Calculate from recent transaction history
            recent_withdrawals = db.query(Transaction).filter(
                Transaction.coin_symbol == coin_symbol,
                Transaction.direction == 'sent',
                Transaction.created_at >= datetime.now(timezone.utc) - timedelta(days=30)
            ).limit(100).all()
            
            if recent_withdrawals:
                activity_level = len(recent_withdrawals)
                if activity_level > 50:
                    activity_desc = "high activity"
                elif activity_level > 20:
                    activity_desc = "medium activity"
                elif activity_level > 5:
                    activity_desc = "low activity"
                else:
                    activity_desc = "minimal activity"
                    
                base_fee = MarketService._get_default_fee_estimate(coin_symbol, node_type)
                return f"{base_fee} ({activity_desc})"
            
            return MarketService._get_default_fee_estimate(coin_symbol, node_type)
            
        except Exception as e:
            logger.error(f"Error calculating average fee for {coin_symbol}: {e}")
            return MarketService._get_default_fee_estimate(coin_symbol, node_type)
    
    @staticmethod
    def _get_default_fee_estimate(coin_symbol: str, node_type: str) -> str:
        """Get default fee estimate when dynamic calculation isn't available."""
        if node_type == "monero":
            return f"~0.0001 {coin_symbol}"
        else:
            default_fee = os.environ.get(f"{coin_symbol}_DEFAULT_FEE", "0.0001")
            return f"~{default_fee} {coin_symbol}"
