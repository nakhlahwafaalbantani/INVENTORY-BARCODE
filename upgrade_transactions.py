import sqlite3


DATABASE_NAME = "inventory.db"


connection = sqlite3.connect(
    DATABASE_NAME
)

cursor = connection.cursor()


# Ambil daftar kolom transactions yang sudah ada
cursor.execute(
    "PRAGMA table_info(transactions)"
)

columns = {
    row[1]
    for row in cursor.fetchall()
}


new_columns = {
    "stock_before": "INTEGER",
    "stock_after": "INTEGER",
    "client_pc": "TEXT",
}


for column_name, column_type in new_columns.items():

    if column_name not in columns:

        cursor.execute(
            f"""
            ALTER TABLE transactions
            ADD COLUMN {column_name} {column_type}
            """
        )

        print(
            f"Kolom '{column_name}' berhasil ditambahkan."
        )

    else:

        print(
            f"Kolom '{column_name}' sudah ada."
        )


connection.commit()
connection.close()


print(
    "\nDatabase transaksi berhasil diperbarui."
)