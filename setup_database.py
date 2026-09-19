import sqlite3


DATABASE_NAME = "inventory.db"


connection = sqlite3.connect(DATABASE_NAME)
cursor = connection.cursor()


# ==========================================================
# TABLE PRODUCTS
# ==========================================================

cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_code TEXT NOT NULL UNIQUE,
        barcode TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        category TEXT,
        unit TEXT NOT NULL,
        stock INTEGER NOT NULL DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
""")


# ==========================================================
# TABLE TRANSACTIONS
# ==========================================================

cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        transaction_type TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        user_name TEXT,
        transaction_time DATETIME DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY (product_id)
        REFERENCES products(id)
    )
""")


connection.commit()
connection.close()


print("Database inventory berhasil dibuat.")
print("Tabel products dan transactions siap digunakan.")