from __future__ import annotations

import re
import shutil
import sqlite3
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

# ============================================================
# IMPORT MASTER PRODUK PT ALDIGENS PUTERA PERSADA
#
# Struktur data:
# - part_number  = Part Number asli dari perusahaan
# - product_code = Kode Internal yang dibuat oleh sistem
# - barcode      = Barcode untuk scanning, memakai Kode Internal
# - name         = Nama barang
# - category     = Kategori barang
# - unit         = Satuan
# - stock        = Stock Akhir, jika kosong memakai Stock Awal
#
# Harga Satuan SENGAJA belum diimport.
# Histori transaksi SENGAJA belum dibuat dari Excel.
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
EXCEL_FILE = BASE_DIR / "Persediaan Aldigens 2026.xlsx"
DB_FILE = BASE_DIR / "inventory.db"
BACKUP_DIR = BASE_DIR / "backup_inventory"

NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def normalize_text(value) -> str:
    if value is None:
        return ""

    return str(value).replace("\xa0", " ").strip()


def number_from_excel(value):
    text = normalize_text(value)

    if not text:
        return None

    text = text.replace(",", "")

    try:
        return float(text)
    except ValueError:
        return None


def stock_value(value) -> int:
    number = number_from_excel(value)

    if number is None:
        return 0

    return int(round(number))


def column_index(cell_reference: str) -> int:
    match = re.match(r"([A-Z]+)", cell_reference.upper())

    if not match:
        raise ValueError(
            f"Referensi sel tidak valid: {cell_reference}"
        )

    result = 0

    for char in match.group(1):
        result = result * 26 + (ord(char) - ord("A") + 1)

    return result - 1


def parse_xlsx_sheet(file_path: Path):
    """
    Membaca worksheet pertama dari file XLSX menggunakan standard library.
    Tidak membutuhkan openpyxl atau pandas.
    """

    with zipfile.ZipFile(file_path, "r") as archive:
        shared_strings = []

        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(
                archive.read("xl/sharedStrings.xml")
            )

            for item in shared_root.findall("a:si", NS):
                text_parts = []

                for node in item.iter(
                    "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"
                ):
                    text_parts.append(node.text or "")

                shared_strings.append("".join(text_parts))

        workbook_root = ET.fromstring(
            archive.read("xl/workbook.xml")
        )

        relations_root = ET.fromstring(
            archive.read("xl/_rels/workbook.xml.rels")
        )

        relation_map = {}

        for rel in relations_root:
            relation_map[rel.attrib.get("Id")] = rel.attrib.get("Target")

        sheets = workbook_root.find("a:sheets", NS)

        if sheets is None:
            raise RuntimeError("Worksheet Excel tidak ditemukan.")

        first_sheet = sheets.find("a:sheet", NS)

        if first_sheet is None:
            raise RuntimeError("Worksheet Excel tidak ditemukan.")

        relationship_id = first_sheet.attrib.get(
            "{%s}id" % NS["r"]
        )

        target = relation_map.get(relationship_id)

        if not target:
            raise RuntimeError("Lokasi worksheet Excel tidak ditemukan.")

        target = target.lstrip("/")

        if not target.startswith("xl/"):
            target = "xl/" + target

        worksheet_root = ET.fromstring(
            archive.read(target)
        )

        rows = []

        for row_node in worksheet_root.findall(
            ".//a:sheetData/a:row",
            NS
        ):
            cells = {}

            for cell in row_node.findall("a:c", NS):
                reference = cell.attrib.get("r", "")

                if not reference:
                    continue

                index = column_index(reference)

                value_node = cell.find("a:v", NS)

                if value_node is None:
                    value = ""
                else:
                    value = value_node.text or ""

                cell_type = cell.attrib.get("t")

                if cell_type == "s" and value:
                    try:
                        value = shared_strings[int(value)]
                    except (IndexError, ValueError):
                        value = ""

                elif cell_type == "inlineStr":
                    text_parts = []

                    for node in cell.iter(
                        "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"
                    ):
                        text_parts.append(node.text or "")

                    value = "".join(text_parts)

                cells[index] = value

            if cells:
                max_index = max(cells)
                row_values = [
                    cells.get(i, "")
                    for i in range(max_index + 1)
                ]
            else:
                row_values = []

            rows.append(row_values)

        return rows


def find_header_row(rows):
    required = {
        "No.",
        "Kategori Barang",
        "Part Number",
        "Nama Barang",
        "Jenis Barang",
        "Satuan",
    }

    for index, row in enumerate(rows):
        normalized = {
            normalize_text(value)
            for value in row
        }

        if required.issubset(normalized):
            return index

    raise RuntimeError(
        "Baris header master produk tidak ditemukan."
    )


def row_to_dict(row, headers):
    result = {}

    for index, header in enumerate(headers):
        header = normalize_text(header)

        if not header:
            continue

        result[header] = (
            row[index]
            if index < len(row)
            else ""
        )

    return result


def backup_database():
    BACKUP_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    backup_file = (
        BACKUP_DIR
        / f"inventory_backup_{timestamp}.db"
    )

    shutil.copy2(
        DB_FILE,
        backup_file
    )

    return backup_file


def ensure_database_columns(connection: sqlite3.Connection):
    """
    Menambahkan kolom baru tanpa menghapus data lama.
    """

    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(products)"
        ).fetchall()
    }

    required_existing = {
        "product_code",
        "barcode",
        "name",
        "category",
        "unit",
        "stock",
    }

    missing_existing = (
        required_existing
        - columns
    )

    if missing_existing:
        raise RuntimeError(
            "Struktur tabel products belum sesuai. "
            "Kolom yang hilang: "
            + ", ".join(sorted(missing_existing))
        )

    if "part_number" not in columns:
        connection.execute(
            "ALTER TABLE products ADD COLUMN part_number TEXT"
        )

    if "source_excel_no" not in columns:
        connection.execute(
            "ALTER TABLE products ADD COLUMN source_excel_no TEXT"
        )


def load_used_internal_codes(connection):
    used = set()

    rows = connection.execute(
        "SELECT product_code FROM products"
    ).fetchall()

    for row in rows:
        if row[0]:
            used.add(
                str(row[0]).strip()
            )

    return used


def next_internal_code(used_codes: set[str], current_number: int):
    number = current_number

    while True:
        candidate = f"INT-{number:04d}"

        if candidate not in used_codes:
            used_codes.add(candidate)
            return candidate, number + 1

        number += 1


def get_start_internal_number(used_codes: set[str]) -> int:
    highest = 0

    pattern = re.compile(
        r"^INT-(\d+)$",
        re.IGNORECASE
    )

    for code in used_codes:
        match = pattern.match(code)

        if match:
            highest = max(
                highest,
                int(match.group(1))
            )

    return highest + 1


def main():
    print("=" * 70)
    print("IMPORT MASTER PRODUK - PT ALDIGENS PUTERA PERSADA")
    print("=" * 70)

    if not EXCEL_FILE.exists():
        print("ERROR: File Excel tidak ditemukan:")
        print(EXCEL_FILE)
        print()
        print(
            "Pastikan 'Persediaan Aldigens 2026.xlsx' "
            "berada satu folder dengan script ini."
        )
        return 1

    if not DB_FILE.exists():
        print("ERROR: Database tidak ditemukan:")
        print(DB_FILE)
        print()
        print(
            "Pastikan script ini dijalankan di folder project inventory."
        )
        return 1

    print(f"Excel : {EXCEL_FILE.name}")
    print(f"DB    : {DB_FILE.name}")
    print()

    backup_file = backup_database()

    print(
        f"Backup database dibuat: {backup_file.name}"
    )

    rows = parse_xlsx_sheet(
        EXCEL_FILE
    )

    header_index = find_header_row(
        rows
    )

    headers = rows[header_index]

    print(
        f"Header ditemukan pada baris: {header_index + 1}"
    )

    products = []

    for row in rows[header_index + 1:]:
        item = row_to_dict(
            row,
            headers
        )

        excel_no = normalize_text(
            item.get("No.", "")
        )

        name = normalize_text(
            item.get("Nama Barang", "")
        )

        if not excel_no.isdigit():
            continue

        if not name:
            continue

        products.append(item)

    print(
        f"Produk yang akan diproses: {len(products)}"
    )

    connection = sqlite3.connect(
        DB_FILE
    )

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    try:
        ensure_database_columns(
            connection
        )

        used_codes = load_used_internal_codes(
            connection
        )

        next_code_number = get_start_internal_number(
            used_codes
        )

        inserted = 0
        skipped = 0
        with_part_number = 0
        without_part_number = 0
        stock_zero = 0

        for item in products:
            excel_no = normalize_text(
                item.get("No.", "")
            )

            name = normalize_text(
                item.get("Nama Barang", "")
            )

            category = normalize_text(
                item.get("Kategori Barang", "")
            ) or "Tanpa Kategori"

            unit = normalize_text(
                item.get("Satuan", "")
            ) or "Unit"

            part_number = normalize_text(
                item.get("Part Number", "")
            )

            # ------------------------------------------------
            # PART NUMBER
            # Tetap merupakan data perusahaan.
            # Kosong = tetap kosong.
            # ------------------------------------------------
            if part_number:
                with_part_number += 1
                part_number_db = part_number
            else:
                without_part_number += 1
                part_number_db = None

            # ------------------------------------------------
            # CEK IMPORT ULANG
            # source_excel_no mencegah data yang sama
            # masuk berkali-kali.
            # ------------------------------------------------
            existing = connection.execute(
                """
                SELECT id
                FROM products
                WHERE source_excel_no = ?
                LIMIT 1
                """,
                (excel_no,)
            ).fetchone()

            if existing:
                skipped += 1
                continue

            # ------------------------------------------------
            # KODE INTERNAL
            # ------------------------------------------------
            product_code, next_code_number = next_internal_code(
                used_codes,
                next_code_number
            )

            # Barcode memakai Kode Internal.
            barcode_value = product_code

            # ------------------------------------------------
            # STOK
            # Prioritas: Stock Akhir
            # Bila kosong: Stock Awal
            # Bila kosong juga: 0
            # ------------------------------------------------
            stock_text = item.get(
                "Stock Akhir",
                ""
            )

            if not normalize_text(stock_text):
                stock_text = item.get(
                    "Stock Awal",
                    ""
                )

            stock = stock_value(
                stock_text
            )

            if stock == 0:
                stock_zero += 1

            connection.execute(
                """
                INSERT INTO products
                    (
                        product_code,
                        barcode,
                        part_number,
                        name,
                        category,
                        unit,
                        stock,
                        source_excel_no
                    )
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_code,
                    barcode_value,
                    part_number_db,
                    name,
                    category,
                    unit,
                    stock,
                    excel_no,
                )
            )

            inserted += 1

        connection.commit()

        print()
        print("HASIL IMPORT")
        print("-" * 70)
        print(
            f"Produk terbaca              : {len(products)}"
        )
        print(
            f"Berhasil masuk              : {inserted}"
        )
        print(
            f"Dilewati karena sudah ada   : {skipped}"
        )
        print(
            f"Memiliki Part Number        : {with_part_number}"
        )
        print(
            f"Tanpa Part Number           : {without_part_number}"
        )
        print(
            f"Stok 0/kosong               : {stock_zero}"
        )
        print(
            "Harga Satuan                : TIDAK diimport"
        )
        print(
            "Histori transaksi           : TIDAK dibuat dari Excel"
        )
        print("-" * 70)
        print("Part Number = data asli perusahaan")
        print("Kode Internal = dibuat otomatis oleh sistem")
        print("Barcode = Kode Internal")
        print()
        print("IMPORT BERHASIL.")
        print(f"Backup: {backup_file}")
        print("=" * 70)

        return 0

    except Exception as error:
        connection.rollback()

        print()
        print("IMPORT GAGAL")
        print("Perubahan database dibatalkan.")
        print()
        print(f"Detail error: {error}")
        print()
        print(
            f"Backup tetap tersedia di: {backup_file}"
        )

        return 1

    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(
        main()
    )