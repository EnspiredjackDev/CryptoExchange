from db import SessionLocal
from models import Transaction
from sqlalchemy import delete

def clear_transactions():
    db = SessionLocal()
    try:
        num_deleted = db.query(Transaction).delete()
        db.commit()
        print(f"✅ Cleared {num_deleted} transactions from the database.")
    except Exception as e:
        db.rollback()
        print(f"❌ Failed to clear transactions: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    clear_transactions()
