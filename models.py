from decimal import Decimal
import enum
from sqlalchemy import Boolean, Column, Integer, Text, ForeignKey, String, Numeric, TIMESTAMP, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB

Base = declarative_base()

def utc_now():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = 'users'
    __table_args__ = {'schema': 'exchange'}

    id = Column(Integer, primary_key=True)
    api_key_hash = Column(Text, unique=True, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=utc_now)

    addresses = relationship("Address", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")


class Address(Base):
    __tablename__ = 'addresses'
    __table_args__ = {'schema': 'exchange'}

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('exchange.users.id'), nullable=False)
    address = Column(Text, unique=True, nullable=False)
    coin_symbol = Column(String(10), nullable=False)  # e.g., BTC, LTC, etc.
    created_at = Column(TIMESTAMP(timezone=True), default=utc_now)
    extra_info = Column(JSONB, nullable=True)

    user = relationship("User", back_populates="addresses")


class Transaction(Base):
    __tablename__ = 'transactions'
    __table_args__ = (
        UniqueConstraint("tx_id", name="uix_txid"),
        {'schema': 'exchange'}
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('exchange.users.id'), nullable=False)
    tx_id = Column(Text, nullable=False)
    amount = Column(Numeric(18, 8))
    direction = Column(String(10))  # 'received' or 'sent'
    coin_symbol = Column(String(10), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=utc_now)

    user = relationship("User", back_populates="transactions")

class OrderStatus(enum.Enum):
    open = "open"
    filled = "filled"
    cancelled = "cancelled"
    partially_filled = "partially_filled"

class OrderSide(enum.Enum):
    buy = "buy"
    sell = "sell"

class Market(Base):
    __tablename__ = 'markets'
    __table_args__ = {'schema': 'exchange'}

    id = Column(Integer, primary_key=True)
    base_coin = Column(String(10), nullable=False)  # e.g. DOGE
    quote_coin = Column(String(10), nullable=False)  # e.g. XMR
    active = Column(Boolean, default=True)
    fee_rate = Column(Numeric(5, 4), default=Decimal("0.001"))

class Order(Base):
    __tablename__ = 'orders'
    __table_args__ = {'schema': 'exchange'}

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('exchange.users.id'), nullable=False)
    market_id = Column(Integer, ForeignKey('exchange.markets.id'), nullable=False)
    side = Column(SqlEnum(OrderSide), nullable=False)
    price = Column(Numeric(18, 8), nullable=False)      # price per unit
    amount = Column(Numeric(18, 8), nullable=False)     # total requested amount
    remaining = Column(Numeric(18, 8), nullable=False)  # what's left to fill
    status = Column(SqlEnum(OrderStatus), default=OrderStatus.open)
    created_at = Column(TIMESTAMP(timezone=True), default=utc_now)

    user = relationship("User")
    market = relationship("Market")

class Trade(Base):
    __tablename__ = 'trades'
    __table_args__ = {'schema': 'exchange'}

    id = Column(Integer, primary_key=True)
    buy_order_id = Column(Integer, ForeignKey('exchange.orders.id'), nullable=False)
    sell_order_id = Column(Integer, ForeignKey('exchange.orders.id'), nullable=False)
    market_id = Column(Integer, ForeignKey('exchange.markets.id'), nullable=False)
    price = Column(Numeric(18, 8), nullable=False)
    amount = Column(Numeric(18, 8), nullable=False)
    timestamp = Column(TIMESTAMP(timezone=True), default=utc_now)

    market = relationship("Market")

    buy_order = relationship("Order", foreign_keys=[buy_order_id])
    sell_order = relationship("Order", foreign_keys=[sell_order_id])

class Balance(Base):
    __tablename__ = 'balances'
    __table_args__ = (
        UniqueConstraint('user_id', 'coin_symbol', name='uix_user_coin'),
        {'schema': 'exchange'}
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('exchange.users.id'), nullable=False)
    coin_symbol = Column(String(10), nullable=False)
    total = Column(Numeric(18, 8), default=0)
    available = Column(Numeric(18, 8), default=0)
    locked = Column(Numeric(18, 8), default=0)
    
    user = relationship("User")

class Fee(Base):
    __tablename__ = "fees"
    __table_args__ = {'schema': 'exchange'}

    id = Column(Integer, primary_key=True)
    trade_id = Column(Integer, ForeignKey('exchange.trades.id'), nullable=True)
    coin_symbol = Column(String(10), nullable=False)
    amount = Column(Numeric(18, 8), nullable=False)
    timestamp = Column(TIMESTAMP(timezone=True), default=utc_now)

    trade = relationship("Trade")

class FeeBalance(Base):
    __tablename__ = "fee_balances"
    __table_args__ = {'schema': 'exchange'}

    id = Column(Integer, primary_key=True)
    coin_symbol = Column(String(10), unique=True, nullable=False)
    amount = Column(Numeric(18, 8), default=Decimal("0.0"), nullable=False)

class SyncState(Base):
    __tablename__ = 'sync_state'
    __table_args__ = {'schema': 'exchange'}

    coin_symbol = Column(String, primary_key=True)
    last_block_hash = Column(String)
