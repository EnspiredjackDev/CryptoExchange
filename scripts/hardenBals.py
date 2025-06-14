from sqlalchemy import create_engine, text

# Replace this with your actual DB connection string
engine = create_engine("postgresql://exchange:password@localhost/myexchange")

with engine.connect() as conn:
    conn.execute(text("""
        ALTER TABLE exchange.balances
        ADD CONSTRAINT check_non_negative_balances
        CHECK (total >= 0 AND available >= 0 AND locked >= 0);
    """))
    print("✅ CHECK constraint applied to balances table.")
