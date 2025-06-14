from sqlalchemy import UniqueConstraint, create_engine, Column, Integer, String, Text, ForeignKey, Numeric, TIMESTAMP
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    __table_args__ = {'schema': 'exchange'}

    id = Column(Integer, primary_key=True)
    api_key_hash = Column(Text, unique=True, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))

    addresses = relationship("Address", back_populates="user")
    transactions = relationship("Transaction", back_populates="user")


class Address(Base):
    __tablename__ = 'addresses'
    __table_args__ = {'schema': 'exchange'}

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('exchange.users.id'), nullable=False)
    address = Column(Text, unique=True, nullable=False)
    coin_symbol = Column(String(10), nullable=False)  # e.g., BTC, LTC, etc.
    created_at = Column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="addresses")


class Transaction(Base):
    __tablename__ = 'transactions'
    __table_args__ = (
        {'schema': 'exchange'},
        UniqueConstraint("tx_id", name="uix_txid")
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('exchange.users.id'), nullable=False)
    tx_id = Column(Text, nullable=False)  # actual transaction ID
    amount = Column(Numeric(18, 8))
    direction = Column(String(10))  # 'received' or 'sent'
    coin_symbol = Column(String(10), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="transactions")


# DB connection
engine = create_engine("postgresql://exchange:password@localhost/myexchange")
Base.metadata.create_all(engine)

print("ORM tables created successfully.")
