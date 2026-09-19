import os
import sqlite3

import barcode
from barcode.writer import ImageWriter


DATABASE_NAME = "inventory.db"
BARCODE_FOLDER = os.path.join(
    "static",
    "barcodes"
)


# Pastikan folder barcode ada
os.makedirs(
    BARCODE_FOLDER,
    exist_ok=True
)


connection = sqlite3.connect(
    DATABASE_NAME
)

cursor = connection.cursor()


cursor.execute("""
    SELECT
        id,
        product_code,
        barcode,
        name
    FROM products
    ORDER BY id
""")


products = cursor.fetchall()

connection.close()


if not products:

    print("Tidak ada produk di database.")
    raise SystemExit


print("=== GENERATE BARCODE ===")


for product in products:

    product_id = product[0]
    product_code = product[1]
    barcode_value = str(product[2])
    product_name = product[3]

    print(
        f"Membuat barcode: "
        f"{product_code} "
        f"-> {barcode_value}"
    )

    barcode_class = barcode.get_barcode_class(
        "code128"
    )

    barcode_object = barcode_class(
        barcode_value,
        writer=ImageWriter()
    )

    filename = os.path.join(
        BARCODE_FOLDER,
        barcode_value
    )

    barcode_object.save(
        filename
    )

    print(
        f"Berhasil: {product_name}"
    )


print("\nSemua barcode berhasil dibuat.")