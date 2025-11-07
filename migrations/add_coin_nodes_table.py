"""
Migration script to add coin_nodes table to the database.
This allows dynamic coin node configuration without restarting the application.
"""

from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

def migrate():
    database_url = os.environ.get('DATABASE_URL', 'sqlite:///exchange.db')
    engine = create_engine(database_url)
    
    with engine.connect() as conn:
        print("Creating coin_nodes table...")
        
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS exchange.coin_nodes (
                id SERIAL PRIMARY KEY,
                coin_symbol VARCHAR(10) UNIQUE NOT NULL,
                coin_name VARCHAR(50) NOT NULL,
                
                node_host VARCHAR(255) NOT NULL,
                node_port INTEGER NOT NULL,
                node_user VARCHAR(255) NOT NULL,
                node_pass TEXT NOT NULL,
                node_type VARCHAR(20) NOT NULL DEFAULT 'btc',
                
                network_name VARCHAR(50),
                block_time VARCHAR(50),
                confirmations INTEGER DEFAULT 6,
                address_format VARCHAR(255),
                default_fee VARCHAR(20),
                
                enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """))
        
        conn.commit()
        print("✓ coin_nodes table created successfully")
        
        # Optionally migrate existing environment variables to database
        print("\nChecking for existing coin configurations in environment...")
        migrate_env_to_db(conn)
        
        conn.commit()


def migrate_env_to_db(conn):
    """Migrate existing coin configurations from environment variables to database."""
    coins_migrated = []
    
    # Scan for coin configurations in environment
    for key in os.environ:
        if key.endswith('_NODE_HOST'):
            coin_symbol = key.replace('_NODE_HOST', '')
            
            # Get all required fields
            host = os.environ.get(f"{coin_symbol}_NODE_HOST")
            port = os.environ.get(f"{coin_symbol}_NODE_PORT")
            user = os.environ.get(f"{coin_symbol}_NODE_USER")
            password = os.environ.get(f"{coin_symbol}_NODE_PASS")
            node_type = os.environ.get(f"{coin_symbol}_NODE_TYPE", "btc")
            
            if not all([host, port, user, password]):
                continue
            
            # Get metadata
            coin_name = os.environ.get(f"{coin_symbol}_NAME", coin_symbol)
            network_name = os.environ.get(f"{coin_symbol}_NETWORK", coin_name)
            block_time = os.environ.get(f"{coin_symbol}_BLOCK_TIME", "Variable")
            confirmations = os.environ.get(f"{coin_symbol}_CONFIRMATIONS", "6")
            address_format = os.environ.get(f"{coin_symbol}_ADDRESS_FORMAT", "")
            default_fee = os.environ.get(f"{coin_symbol}_DEFAULT_FEE", "0.0001")
            
            # Check if already exists
            result = conn.execute(
                text("SELECT coin_symbol FROM exchange.coin_nodes WHERE coin_symbol = :symbol"),
                {"symbol": coin_symbol}
            )
            
            if result.fetchone():
                print(f"  - {coin_symbol}: Already exists in database, skipping")
                continue
            
            # Insert into database
            try:
                conn.execute(text("""
                    INSERT INTO exchange.coin_nodes (
                        coin_symbol, coin_name, node_host, node_port, node_user, node_pass,
                        node_type, network_name, block_time, confirmations, address_format,
                        default_fee, enabled
                    ) VALUES (
                        :symbol, :name, :host, :port, :user, :pass,
                        :type, :network, :block_time, :confirmations, :address_format,
                        :default_fee, TRUE
                    )
                """), {
                    "symbol": coin_symbol,
                    "name": coin_name,
                    "host": host,
                    "port": int(port),
                    "user": user,
                    "pass": password,
                    "type": node_type.lower(),
                    "network": network_name,
                    "block_time": block_time,
                    "confirmations": int(confirmations),
                    "address_format": address_format,
                    "default_fee": default_fee
                })
                
                coins_migrated.append(coin_symbol)
                print(f"  ✓ {coin_symbol}: Migrated to database")
                
            except Exception as e:
                print(f"  ✗ {coin_symbol}: Failed to migrate - {str(e)}")
    
    if coins_migrated:
        print(f"\n✓ Migrated {len(coins_migrated)} coin(s) to database: {', '.join(coins_migrated)}")
    else:
        print("  No coin configurations found in environment variables")


if __name__ == '__main__':
    print("=" * 70)
    print("CoinNodes Table Migration")
    print("=" * 70)
    migrate()
    print("\n" + "=" * 70)
    print("Migration completed successfully!")
    print("=" * 70)
