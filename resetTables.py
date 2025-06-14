from models import Base
from db import engine

print("⚠️  WARNING: This will delete all tables in the 'exchange' schema!")

def wipe_tables():
    print("Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    print("Creating updated tables...")
    Base.metadata.create_all(bind=engine)
    print("✅ Tables reset successfully.")



if __name__ == "__main__":
    confirm = input("Type 'yes' to continue: ")

    if confirm.strip().lower() == 'yes':
        wipe_tables()
    else:
        print("❌ Cancelled. No changes were made.")
