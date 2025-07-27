#!/bin/bash

# CONFIGURE THESE:
DB_NAME="myexchange"
DB_USER="exchange"
DB_PASSWORD="exchangepassword"
SCHEMA_NAME="exchange"

echo "Creating PostgreSQL user and database..."

# Execute SQL as postgres superuser
sudo -u postgres psql <<EOF

-- Create the user if it doesn't exist
DO \$\$
BEGIN
   IF NOT EXISTS (
      SELECT FROM pg_catalog.pg_roles WHERE rolname = '${DB_USER}'
   ) THEN
      CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';
   END IF;
END
\$\$;

-- Create the database if it doesn't exist
DO \$\$
BEGIN
   IF NOT EXISTS (
      SELECT FROM pg_database WHERE datname = '${DB_NAME}'
   ) THEN
      CREATE DATABASE ${DB_NAME};
   END IF;
END
\$\$;

-- Grant access to the new user
GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};

EOF

echo "Creating schema in ${DB_NAME}..."

# Create the schema inside the target database
sudo -u postgres psql -d "$DB_NAME" <<EOF

-- Create schema only if it doesn't exist
DO \$\$
BEGIN
   IF NOT EXISTS (
      SELECT 1 FROM information_schema.schemata WHERE schema_name = '${SCHEMA_NAME}'
   ) THEN
      CREATE SCHEMA ${SCHEMA_NAME} AUTHORIZATION ${DB_USER};
   END IF;
END
\$\$;

-- Grant usage and create privileges just to be safe
GRANT USAGE ON SCHEMA ${SCHEMA_NAME} TO ${DB_USER};
GRANT CREATE ON SCHEMA ${SCHEMA_NAME} TO ${DB_USER};
ALTER SCHEMA ${SCHEMA_NAME} OWNER TO ${DB_USER};

EOF

echo "✅ PostgreSQL setup complete for user '$DB_USER', DB '$DB_NAME', schema '$SCHEMA_NAME'"

echo "Creating tables using SQLAlchemy..."
python3 createTables.py
echo "✅ Tables created."
