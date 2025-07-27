# 🪙 Crypto Exchange App – Database Setup

This guide will walk you through setting up the PostgreSQL database for the exchange backend.

---

## 📦 Prerequisites

Before proceeding, ensure you have:

- **PostgreSQL** installed  
  → [Download PostgreSQL](https://www.postgresql.org/download/)

- Access to the `postgres` user (e.g., via `sudo`)
- Python 3 installed, with pip
- Your project dependencies installed (`pip install -r requirements.txt`)

---

## ⚙️ Step 1: Configure the Database Setup Script

Open `setupDatabase.sh` and modify the variables at the top if needed:

```bash
DB_NAME="myexchange"
DB_USER="exchange"
DB_PASSWORD="exchangepassword"
SCHEMA_NAME="exchange"
````

* Make sure the `SCHEMA_NAME` matches your SQLAlchemy models (`exchange` by default)

---

## 🏗 Step 2: Run the Setup Script

The script will:

* Create the PostgreSQL user (if it doesn't exist)
* Create the database
* Create the schema inside the database
* Grant appropriate privileges to the new user

Run it like this:

```bash
chmod +x setupDatabase.sh
./setupDatabase.sh
```

You should see confirmation messages once complete.

---

## 🧱 Step 3: Initialise the Database Tables

After the schema is created, use SQLAlchemy to create the necessary tables:

```bash
python createTables.py
```

This script safely creates any missing tables, without deleting data.

---

### 🔑 Step 4: Add Database Credentials to `.env`

Once the database and user have been created, you need to add the correct connection string to your `.env` file so the app knows how to connect.

#### 🔧 Example `.env` entry:

```env
DATABASE_URL=postgresql://exchange:yourpassword@localhost/myexchange
```

* `exchange`: your DB username (set in `setupDatabase.sh`)
* `yourpassword`: the password you provided (or left blank if using `trust` auth)
* `localhost`: the database host (change if hosted remotely)
* `myexchange`: the database name

> 💡 **Note:** The app will not work without a valid `DATABASE_URL` set in `.env`.

---

## ✅ All Done

At this point, your database is ready to use with the exchange backend.

You can now:

* Run the Flask app
* Generate API keys
* Start building or interacting with the exchange via the API

---

## ⚠️ Notes

* Never run `resetTables.py` (or any destructive script) in production unless you **intend to delete all user data**.
* PostgreSQL must be running before executing the setup.

---

## 📎 Optional: Other Setup Docs

* [PostgreSQL official install guide](https://www.postgresql.org/download/)
* [SQLAlchemy docs](https://docs.sqlalchemy.org/)
* [Alembic for migrations](https://alembic.sqlalchemy.org/)

