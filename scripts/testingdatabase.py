from sqlalchemy import create_engine, text

engine = create_engine("postgresql://exchange:password@localhost/myexchange")

with engine.connect() as conn:
    result = conn.execute(text("SELECT version();"))
    print(result.fetchone())
