import os
import re@
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps

import barcode
from barcode.writer import ImageWriter

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for
)

from werkzeug.security import (
    check_password_hash,
    generate_password_hash
)


# =========================================================
# FLASK APPLICATION
# =========================================================

app = Flask(__name__)

app.secret_key = (
    "PT-ALDIGENS-PUTERA-PERSADA-"
    "INVENTORY-SECRET-2026"
)

app.permanent_session_lifetime = timedelta(
    hours=8
)


# =========================================================
# CONFIGURATION
# =========================================================

DATABASE_NAME = "inventory.db"

BARCODE_FOLDER = os.path.join(
    "static",
    "barcodes"
)

os.makedirs(
    BARCODE_FOLDER,
    exist_ok=True
)


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_database_connection():

    connection = sqlite3.connect(
        DATABASE_NAME
    )

    connection.row_factory = sqlite3.Row

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    return connection


# =========================================================
# DATABASE SCHEMA
# =========================================================

def ensure_database_schema():

    connection = get_database_connection()

    try:

        # -------------------------------------------------
        # PRODUCTS
        # -------------------------------------------------

        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(products)"
            ).fetchall()
        }

        required_columns = {
            "product_code",
            "barcode",
            "name",
            "category",
            "unit",
            "stock"
        }

        missing_columns = (
            required_columns
            - columns
        )

        if missing_columns:

            raise RuntimeError(
                "Kolom products yang hilang: "
                + ", ".join(
                    sorted(missing_columns)
                )
            )

        if "part_number" not in columns:

            connection.execute(
                """
                ALTER TABLE products
                ADD COLUMN part_number TEXT
                """
            )

        if "source_excel_no" not in columns:

            connection.execute(
                """
                ALTER TABLE products
                ADD COLUMN source_excel_no TEXT
                """
            )

        # -------------------------------------------------
        # USERS
        # -------------------------------------------------

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users
            (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                username TEXT NOT NULL UNIQUE,

                password_hash TEXT NOT NULL,

                full_name TEXT NOT NULL,

                role TEXT NOT NULL
                    DEFAULT 'Staff Gudang',

                created_at DATETIME
                    DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # -------------------------------------------------
        # DEFAULT ADMIN
        # -------------------------------------------------

        admin = connection.execute(
            """
            SELECT id
            FROM users
            WHERE username = ?
            LIMIT 1
            """,
            ("admin",)
        ).fetchone()

        if admin is None:

            connection.execute(
                """
                INSERT INTO users
                (
                    username,
                    password_hash,
                    full_name,
                    role
                )
                VALUES
                (
                    ?,
                    ?,
                    ?,
                    ?
                )
                """,
                (
                    "admin",
                    generate_password_hash(
                        "admin123"
                    ),
                    "Administrator",
                    "Administrator"
                )
            )

        connection.commit()

    finally:

        connection.close()


ensure_database_schema()


# =========================================================
# AUTHENTICATION
# =========================================================

def login_required(function):

    @wraps(function)
    def decorated_function(
        *args,
        **kwargs
    ):

        if not session.get(
            "logged_in"
        ):

            if request.path.startswith(
                "/api/"
            ):

                return jsonify({
                    "success": False,
                    "message":
                        "Sesi login sudah berakhir."
                }), 401

            return redirect(
                url_for(
                    "login",
                    next=request.path
                )
            )

        return function(
            *args,
            **kwargs
        )

    return decorated_function


def admin_required(function):

    @wraps(function)
    def decorated_function(
        *args,
        **kwargs
    ):

        if not session.get(
            "logged_in"
        ):

            return redirect(
                url_for(
                    "login",
                    next=request.path
                )
            )

        if session.get(
            "role"
        ) != "Administrator":

            return redirect(
                url_for(
                    "home"
                )
            )

        return function(
            *args,
            **kwargs
        )

    return decorated_function


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if session.get(
        "logged_in"
    ):

        return redirect(
            url_for("home")
        )

    error_message = ""

    if request.method == "POST":

        username = (
            request.form.get(
                "username",
                ""
            )
            .strip()
            .lower()
        )

        password = request.form.get(
            "password",
            ""
        )

        connection = (
            get_database_connection()
        )

        user = connection.execute(
            """
            SELECT *
            FROM users
            WHERE username = ?
            LIMIT 1
            """,
            (
                username,
            )
        ).fetchone()

        connection.close()

        if (
            user is not None
            and check_password_hash(
                user["password_hash"],
                password
            )
        ):

            session.clear()

            session.permanent = True

            session["logged_in"] = True

            session["user_id"] = (
                user["id"]
            )

            session["username"] = (
                user["username"]
            )

            session["full_name"] = (
                user["full_name"]
            )

            session["role"] = (
                user["role"]
            )

            next_page = request.args.get(
                "next",
                ""
            )

            if (
                next_page
                and next_page.startswith("/")
                and not next_page.startswith("//")
            ):

                return redirect(
                    next_page
                )

            return redirect(
                url_for("home")
            )

        error_message = (
            "Username atau password salah."
        )

    return render_template(
        "login.html",
        error_message=error_message
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# =========================================================
# PROFILE
# =========================================================

@app.route(
    "/profile",
    methods=["GET", "POST"]
)
@login_required
def profile():

    connection = (
        get_database_connection()
    )

    user = connection.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        LIMIT 1
        """,
        (
            session["user_id"],
        )
    ).fetchone()

    if user is None:

        connection.close()

        session.clear()

        return redirect(
            url_for("login")
        )

    message = ""
    error_message = ""

    if request.method == "POST":

        action = request.form.get(
            "action",
            ""
        )

        if action == "update_profile":

            full_name = (
                request.form.get(
                    "full_name",
                    ""
                )
                .strip()
            )

            if not full_name:

                error_message = (
                    "Nama lengkap tidak boleh kosong."
                )

            else:

                connection.execute(
                    """
                    UPDATE users
                    SET full_name = ?
                    WHERE id = ?
                    """,
                    (
                        full_name,
                        session["user_id"]
                    )
                )

                connection.commit()

                session["full_name"] = (
                    full_name
                )

                message = (
                    "Profil berhasil diperbarui."
                )

        elif action == "change_password":

            current_password = request.form.get(
                "current_password",
                ""
            )

            new_password = request.form.get(
                "new_password",
                ""
            )

            confirm_password = request.form.get(
                "confirm_password",
                ""
            )

            if not check_password_hash(
                user["password_hash"],
                current_password
            ):

                error_message = (
                    "Password lama salah."
                )

            elif len(new_password) < 6:

                error_message = (
                    "Password baru minimal 6 karakter."
                )

            elif new_password != confirm_password:

                error_message = (
                    "Konfirmasi password tidak cocok."
                )

            else:

                connection.execute(
                    """
                    UPDATE users
                    SET password_hash = ?
                    WHERE id = ?
                    """,
                    (
                        generate_password_hash(
                            new_password
                        ),
                        session["user_id"]
                    )
                )

                connection.commit()

                message = (
                    "Password berhasil diubah."
                )

    user = connection.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        LIMIT 1
        """,
        (
            session["user_id"],
        )
    ).fetchone()

    connection.close()

    return render_template(
        "profile.html",
        user=user,
        message=message,
        error_message=error_message
    )


# =========================================================
# USER MANAGEMENT
# =========================================================

@app.route("/users")
@admin_required
def users():

    connection = (
        get_database_connection()
    )

    users_data = connection.execute(
        """
        SELECT
            id,
            username,
            full_name,
            role,
            created_at
        FROM users
        ORDER BY id ASC
        """
    ).fetchall()

    connection.close()

    return render_template(
        "users.html",
        users=users_data
    )


@app.route(
    "/users/add",
    methods=["POST"]
)
@admin_required
def add_user():

    username = (
        request.form.get(
            "username",
            ""
        )
        .strip()
        .lower()
    )

    full_name = (
        request.form.get(
            "full_name",
            ""
        )
        .strip()
    )

    password = request.form.get(
        "password",
        ""
    )

    role = (
        request.form.get(
            "role",
            "Staff Gudang"
        )
        .strip()
    )

    if role not in [
        "Administrator",
        "Staff Gudang"
    ]:

        role = "Staff Gudang"

    if (
        not username
        or not full_name
        or not password
    ):

        return redirect(
            url_for("users")
        )

    if len(password) < 6:

        return redirect(
            url_for("users")
        )

    connection = (
        get_database_connection()
    )

    try:

        connection.execute(
            """
            INSERT INTO users
            (
                username,
                password_hash,
                full_name,
                role
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                username,
                generate_password_hash(
                    password
                ),
                full_name,
                role
            )
        )

        connection.commit()

    except sqlite3.IntegrityError:

        pass

    finally:

        connection.close()

    return redirect(
        url_for("users")
    )


@app.route(
    "/users/delete/<int:user_id>",
    methods=["POST"]
)
@admin_required
def delete_user(user_id):

    # Administrator tidak boleh menghapus
    # akun yang sedang digunakan.

    if (
        user_id
        == session.get("user_id")
    ):

        return redirect(
            url_for("users")
        )

    connection = (
        get_database_connection()
    )

    connection.execute(
        """
        DELETE FROM users
        WHERE id = ?
        """,
        (
            user_id,
        )
    )

    connection.commit()

    connection.close()

    return redirect(
        url_for("users")
    )


# =========================================================
# NORMALIZE CODE
# =========================================================

def normalize_code(value):

    if value is None:

        return ""

    value = str(value)

    value = re.sub(
        r"[\s\-]+",
        "",
        value
    )

    return value.upper().strip()


# =========================================================
# BARCODE GENERATOR
# =========================================================

def generate_barcode_image(
    barcode_value
):

    if not barcode_value:

        return

    barcode_filename = os.path.join(
        BARCODE_FOLDER,
        barcode_value
    )

    barcode_class = (
        barcode.get_barcode_class(
            "code128"
        )
    )

    barcode_instance = barcode_class(
        barcode_value,
        writer=ImageWriter()
    )

    barcode_instance.save(
        barcode_filename
    )


# =========================================================
# INTERNAL CODE GENERATOR
# =========================================================

def generate_internal_code(
    connection
):

    rows = connection.execute(
        """
        SELECT product_code
        FROM products
        WHERE product_code LIKE 'INT-%'
        """
    ).fetchall()

    highest = 0

    for row in rows:

        code = str(
            row["product_code"]
            or ""
        )

        match = re.fullmatch(
            r"INT-(\d+)",
            code
        )

        if match:

            highest = max(
                highest,
                int(match.group(1))
            )

    while True:

        highest += 1

        candidate = (
            f"INT-{highest:04d}"
        )

        existing = connection.execute(
            """
            SELECT id
            FROM products
            WHERE
                product_code = ?
                OR barcode = ?
            LIMIT 1
            """,
            (
                candidate,
                candidate
            )
        ).fetchone()

        if existing is None:

            return candidate


# =========================================================
# FIND PRODUCT
# =========================================================

def find_product(
    connection,
    value
):

    original_value = str(
        value or ""
    ).strip()

    normalized_value = normalize_code(
        original_value
    )

    return connection.execute(
        """
        SELECT *
        FROM products
        WHERE
            barcode = ?
            OR product_code = ?
            OR UPPER(barcode) = ?
            OR UPPER(product_code) = ?
            OR REPLACE(
                REPLACE(
                    UPPER(barcode),
                    '-',
                    ''
                ),
                ' ',
                ''
            ) = ?
            OR REPLACE(
                REPLACE(
                    UPPER(product_code),
                    '-',
                    ''
                ),
                ' ',
                ''
            ) = ?
        LIMIT 1
        """,
        (
            original_value,
            original_value,
            normalized_value,
            normalized_value,
            normalized_value,
            normalized_value
        )
    ).fetchone()


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/")
@login_required
def home():

    connection = (
        get_database_connection()
    )

    total_products = connection.execute(
        """
        SELECT COUNT(*) AS total
        FROM products
        """
    ).fetchone()["total"]

    total_stock = connection.execute(
        """
        SELECT COALESCE(
            SUM(stock),
            0
        ) AS total
        FROM products
        """
    ).fetchone()["total"]

    total_in = connection.execute(
        """
        SELECT COALESCE(
            SUM(quantity),
            0
        ) AS total
        FROM transactions
        WHERE transaction_type = 'MASUK'
        """
    ).fetchone()["total"]

    total_out = connection.execute(
        """
        SELECT COALESCE(
            SUM(quantity),
            0
        ) AS total
        FROM transactions
        WHERE transaction_type = 'KELUAR'
        """
    ).fetchone()["total"]

    recent_transactions = connection.execute(
        """
        SELECT
            transactions.*,
            products.name,
            products.product_code,
            products.barcode,
            products.part_number
        FROM transactions
        JOIN products
            ON transactions.product_id =
               products.id
        ORDER BY transactions.id DESC
        LIMIT 5
        """
    ).fetchall()

    connection.close()

    return render_template(
        "index.html",
        total_products=total_products,
        total_stock=total_stock,
        total_in=total_in,
        total_out=total_out,
        recent_transactions=
            recent_transactions
    )


# =========================================================
# DATA PRODUK
# =========================================================

@app.route("/products")
@login_required
def products():

    connection = (
        get_database_connection()
    )

    products_data = connection.execute(
        """
        SELECT *
        FROM products
        ORDER BY id DESC
        """
    ).fetchall()

    connection.close()

    return render_template(
        "products.html",
        products=products_data
    )


# =========================================================
# TAMBAH PRODUK
# =========================================================

@app.route(
    "/products/add",
    methods=["GET", "POST"]
)
@login_required
def add_product():

    if request.method == "POST":

        connection = (
            get_database_connection()
        )

        product_code = (
            request.form.get(
                "product_code",
                ""
            )
            .strip()
        )

        if not product_code:

            product_code = (
                generate_internal_code(
                    connection
                )
            )

        part_number = (
            request.form.get(
                "part_number",
                ""
            )
            .strip()
        )

        if not part_number:

            part_number = None

        name = (
            request.form.get(
                "name",
                ""
            )
            .strip()
        )

        category = (
            request.form.get(
                "category",
                ""
            )
            .strip()
        )

        unit = (
            request.form.get(
                "unit",
                ""
            )
            .strip()
        )

        if not unit:

            unit = "Unit"

        try:

            stock = int(
                request.form.get(
                    "stock",
                    0
                )
            )

        except ValueError:

            stock = 0

        barcode_value = product_code

        existing_product = connection.execute(
            """
            SELECT id
            FROM products
            WHERE
                product_code = ?
                OR barcode = ?
            LIMIT 1
            """,
            (
                product_code,
                barcode_value
            )
        ).fetchone()

        if existing_product is None:

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
                    part_number,
                    name,
                    category,
                    unit,
                    stock,
                    None
                )
            )

            connection.commit()

            connection.close()

            generate_barcode_image(
                barcode_value
            )

        else:

            connection.close()

        return redirect(
            url_for("products")
        )

    return render_template(
        "add_product.html"
    )


# =========================================================
# EDIT PRODUK
# =========================================================

@app.route(
    "/products/edit/<int:product_id>",
    methods=["GET", "POST"]
)
@login_required
def edit_product(
    product_id
):

    connection = (
        get_database_connection()
    )

    product = connection.execute(
        """
        SELECT *
        FROM products
        WHERE id = ?
        """,
        (
            product_id,
        )
    ).fetchone()

    if product is None:

        connection.close()

        return redirect(
            url_for("products")
        )

    if request.method == "POST":

        product_code = (
            request.form.get(
                "product_code",
                product["product_code"]
            )
            .strip()
        )

        part_number = (
            request.form.get(
                "part_number",
                product["part_number"] or ""
            )
            .strip()
        )

        if not part_number:

            part_number = None

        name = (
            request.form.get(
                "name",
                product["name"]
            )
            .strip()
        )

        category = (
            request.form.get(
                "category",
                product["category"] or ""
            )
            .strip()
        )

        unit = (
            request.form.get(
                "unit",
                product["unit"]
            )
            .strip()
        )

        if not unit:

            unit = "Unit"

        try:

            stock = int(
                request.form.get(
                    "stock",
                    product["stock"]
                )
            )

        except ValueError:

            stock = product["stock"]

        barcode_value = product_code

        duplicate = connection.execute(
            """
            SELECT id
            FROM products
            WHERE
                (
                    product_code = ?
                    OR barcode = ?
                )
                AND id != ?
            LIMIT 1
            """,
            (
                product_code,
                barcode_value,
                product_id
            )
        ).fetchone()

        if duplicate is None:

            connection.execute(
                """
                UPDATE products
                SET
                    product_code = ?,
                    barcode = ?,
                    part_number = ?,
                    name = ?,
                    category = ?,
                    unit = ?,
                    stock = ?
                WHERE id = ?
                """,
                (
                    product_code,
                    barcode_value,
                    part_number,
                    name,
                    category,
                    unit,
                    stock,
                    product_id
                )
            )

            connection.commit()

        connection.close()

        old_barcode = product["barcode"]

        if (
            old_barcode
            and old_barcode != barcode_value
        ):

            old_path = os.path.join(
                BARCODE_FOLDER,
                old_barcode + ".png"
            )

            if os.path.exists(
                old_path
            ):

                try:

                    os.remove(
                        old_path
                    )

                except OSError:

                    pass

        generate_barcode_image(
            barcode_value
        )

        return redirect(
            url_for("products")
        )

    connection.close()

    return render_template(
        "edit_product.html",
        product=product
    )


# =========================================================
# BARCODE PRODUCT
# =========================================================

@app.route(
    "/products/<int:product_id>/barcode",
    endpoint="barcode"
)
@login_required
def barcode_view(
    product_id
):

    connection = (
        get_database_connection()
    )

    product = connection.execute(
        """
        SELECT *
        FROM products
        WHERE id = ?
        """,
        (
            product_id,
        )
    ).fetchone()

    connection.close()

    if product is None:

        return redirect(
            url_for("products")
        )

    barcode_filename = (
        product["barcode"]
        + ".png"
    )

    barcode_path = os.path.join(
        BARCODE_FOLDER,
        barcode_filename
    )

    if not os.path.exists(
        barcode_path
    ):

        generate_barcode_image(
            product["barcode"]
        )

    barcode_url = url_for(
        "static",
        filename=(
            "barcodes/"
            + barcode_filename
        )
    )

    return render_template(
        "barcode.html",
        product=product,
        barcode_url=barcode_url
    )


# =========================================================
# SCAN BARCODE
# =========================================================

@app.route("/scan")
@login_required
def scan():

    return render_template(
        "scan.html"
    )


# =========================================================
# API FIND PRODUCT
# =========================================================

@app.route(
    "/api/product/<path:barcode_value>",
    methods=["GET"]
)
@login_required
def api_product_by_barcode(
    barcode_value
):

    original_value = str(
        barcode_value
    )

    normalized_value = normalize_code(
        original_value
    )

    connection = (
        get_database_connection()
    )

    product = find_product(
        connection,
        original_value
    )

    connection.close()

    if product is None:

        return jsonify({
            "success": False,

            "message": (
                "Barcode terbaca, "
                "tetapi produk tidak ditemukan."
            ),

            "scanned_code":
                original_value,

            "normalized_code":
                normalized_value
        }), 404

    return jsonify({

        "success": True,

        "scanned_code":
            original_value,

        "normalized_code":
            normalized_value,

        "product": {

            "id":
                product["id"],

            "product_code":
                product["product_code"],

            "barcode":
                product["barcode"],

            "part_number":
                product["part_number"]
                or "",

            "name":
                product["name"],

            "category":
                product["category"]
                or "-",

            "unit":
                product["unit"],

            "stock":
                product["stock"]

        }

    })


# =========================================================
# TRANSAKSI SINGLE
# =========================================================

@app.route(
    "/transactions/add",
    methods=["GET", "POST"]
)
@login_required
def add_transaction():

    if request.method == "POST":

        barcode_input = (
            request.form.get(
                "barcode",
                ""
            )
            .strip()
        )

        transaction_type = (
            request.form.get(
                "transaction_type",
                ""
            )
            .strip()
            .upper()
        )

        try:

            quantity = int(
                request.form.get(
                    "quantity",
                    0
                )
            )

        except ValueError:

            quantity = 0

        user_name = (
            request.form.get(
                "user_name",
                ""
            )
            .strip()
            or session.get(
                "full_name",
                "Admin"
            )
        )

        client_pc = (
            request.form.get(
                "client_pc",
                ""
            )
            .strip()
        )

        connection = (
            get_database_connection()
        )

        product = find_product(
            connection,
            barcode_input
        )

        if product is None:

            connection.close()

            return redirect(
                url_for(
                    "add_transaction"
                )
            )

        stock_before = product["stock"]

        if transaction_type == "MASUK":

            stock_after = (
                stock_before
                + quantity
            )

        elif transaction_type == "KELUAR":

            if quantity > stock_before:

                connection.close()

                return redirect(
                    url_for(
                        "add_transaction"
                    )
                )

            stock_after = (
                stock_before
                - quantity
            )

        else:

            connection.close()

            return redirect(
                url_for(
                    "add_transaction"
                )
            )

        connection.execute(
            """
            UPDATE products
            SET stock = ?
            WHERE id = ?
            """,
            (
                stock_after,
                product["id"]
            )
        )

        connection.execute(
            """
            INSERT INTO transactions
            (
                product_id,
                transaction_type,
                quantity,
                user_name,
                stock_before,
                stock_after,
                client_pc
            )
            VALUES
            (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product["id"],
                transaction_type,
                quantity,
                user_name,
                stock_before,
                stock_after,
                client_pc
            )
        )

        connection.commit()

        connection.close()

        return redirect(
            url_for(
                "transactions"
            )
        )

    scanned_barcode = (
        request.args.get(
            "barcode",
            ""
        )
        .strip()
    )

    scanned_type = (
        request.args.get(
            "type",
            ""
        )
        .strip()
        .upper()
    )

    scanned_product = None

    if scanned_barcode:

        connection = (
            get_database_connection()
        )

        scanned_product = find_product(
            connection,
            scanned_barcode
        )

        connection.close()

    return render_template(
        "add_transaction.html",
        scanned_product=scanned_product,
        scanned_type=scanned_type
    )


# =========================================================
# BATCH TRANSACTIONS
# =========================================================

@app.route(
    "/transactions/batch",
    methods=["POST"]
)
@login_required
def batch_transactions():

    data = request.get_json(
        silent=True
    )

    if not data:

        return jsonify({
            "success": False,
            "message":
                "Data transaksi tidak ditemukan."
        }), 400

    transaction_type = str(
        data.get(
            "transaction_type",
            ""
        )
    ).strip().upper()

    user_name = str(
        data.get(
            "user_name",
            ""
        )
    ).strip()

    if not user_name:

        user_name = session.get(
            "full_name",
            "Admin"
        )

    client_pc = str(
        data.get(
            "client_pc",
            ""
        )
    ).strip()

    items = data.get(
        "items",
        []
    )

    if transaction_type not in [
        "MASUK",
        "KELUAR"
    ]:

        return jsonify({
            "success": False,
            "message":
                "Jenis transaksi tidak valid."
        }), 400

    if (
        not isinstance(
            items,
            list
        )
        or len(items) == 0
    ):

        return jsonify({
            "success": False,
            "message":
                "Belum ada barang dalam transaksi."
        }), 400

    connection = (
        get_database_connection()
    )

    try:

        validated_items = []

        for item in items:

            barcode_value = str(
                item.get(
                    "barcode",
                    ""
                )
            ).strip()

            try:

                quantity = int(
                    item.get(
                        "quantity",
                        0
                    )
                )

            except ValueError:

                quantity = 0

            if not barcode_value:

                raise ValueError(
                    "Barcode produk tidak boleh kosong."
                )

            if quantity <= 0:

                raise ValueError(
                    "Jumlah transaksi harus lebih dari 0."
                )

            product = find_product(
                connection,
                barcode_value
            )

            if product is None:

                raise ValueError(
                    "Produk "
                    + barcode_value
                    + " tidak ditemukan."
                )

            validated_items.append({
                "product": product,
                "quantity": quantity
            })

        if transaction_type == "KELUAR":

            outgoing_totals = {}

            for item in validated_items:

                product_id = item[
                    "product"
                ]["id"]

                quantity = item[
                    "quantity"
                ]

                outgoing_totals[
                    product_id
                ] = (
                    outgoing_totals.get(
                        product_id,
                        0
                    )
                    + quantity
                )

            for item in validated_items:

                product = item[
                    "product"
                ]

                requested = outgoing_totals[
                    product["id"]
                ]

                if requested > product["stock"]:

                    raise ValueError(
                        "Stok "
                        + product["name"]
                        + " tidak mencukupi. "
                        + "Stok tersedia: "
                        + str(product["stock"])
                        + ", yang diminta: "
                        + str(requested)
                    )

        for item in validated_items:

            product = item[
                "product"
            ]

            quantity = item[
                "quantity"
            ]

            stock_before = product[
                "stock"
            ]

            if transaction_type == "MASUK":

                stock_after = (
                    stock_before
                    + quantity
                )

            else:

                stock_after = (
                    stock_before
                    - quantity
                )

            connection.execute(
                """
                UPDATE products
                SET stock = ?
                WHERE id = ?
                """,
                (
                    stock_after,
                    product["id"]
                )
            )

            connection.execute(
                """
                INSERT INTO transactions
                (
                    product_id,
                    transaction_type,
                    quantity,
                    user_name,
                    stock_before,
                    stock_after,
                    client_pc
                )
                VALUES
                (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product["id"],
                    transaction_type,
                    quantity,
                    user_name,
                    stock_before,
                    stock_after,
                    client_pc
                )
            )

        connection.commit()

        return jsonify({
            "success": True,
            "message":
                "Transaksi berhasil disimpan."
        })

    except ValueError as error:

        connection.rollback()

        return jsonify({
            "success": False,
            "message":
                str(error)
        }), 400

    except Exception as error:

        connection.rollback()

        print(
            "Batch transaction error:",
            error
        )

        return jsonify({
            "success": False,
            "message":
                "Terjadi kesalahan saat menyimpan transaksi."
        }), 500

    finally:

        connection.close()


# =========================================================
# RIWAYAT
# =========================================================

@app.route("/transactions")
@login_required
def transactions():

    connection = (
        get_database_connection()
    )

    transactions_data = connection.execute(
        """
        SELECT
            transactions.*,
            products.name,
            products.barcode,
            products.product_code,
            products.part_number,
            products.category,
            products.unit
        FROM transactions
        JOIN products
            ON transactions.product_id =
               products.id
        ORDER BY
            transactions.id DESC
        """
    ).fetchall()

    connection.close()

    return render_template(
        "transactions.html",
        transactions=transactions_data
    )


# =========================================================
# WEEK RANGE
# =========================================================

def get_week_range(
    selected_date=None
):

    if selected_date is None:

        selected_date = date.today()

    monday = (
        selected_date
        - timedelta(
            days=selected_date.weekday()
        )
    )

    sunday = (
        monday
        + timedelta(
            days=6
        )
    )

    return monday, sunday


# =========================================================
# REPORT
# =========================================================

@app.route("/reports")
@login_required
def reports():

    selected_date_string = (
        request.args.get(
            "week",
            ""
        )
        .strip()
    )

    selected_date = None

    if selected_date_string:

        try:

            selected_date = datetime.strptime(
                selected_date_string,
                "%Y-%m-%d"
            ).date()

        except ValueError:

            selected_date = None

    if selected_date is None:

        selected_date = date.today()

    monday, sunday = get_week_range(
        selected_date
    )

    start_date = monday.strftime(
        "%Y-%m-%d"
    )

    end_date = sunday.strftime(
        "%Y-%m-%d"
    )

    connection = (
        get_database_connection()
    )

    weekly_transactions = connection.execute(
        """
        SELECT
            transactions.*,
            products.name,
            products.product_code,
            products.part_number,
            products.barcode,
            products.category,
            products.unit
        FROM transactions
        JOIN products
            ON transactions.product_id =
               products.id
        WHERE
            date(
                transactions.transaction_time
            )
            BETWEEN ? AND ?
        ORDER BY
            transactions.transaction_time ASC,
            transactions.id ASC
        """,
        (
            start_date,
            end_date
        )
    ).fetchall()

    total_in = connection.execute(
        """
        SELECT
            COALESCE(
                SUM(quantity),
                0
            ) AS total
        FROM transactions
        WHERE
            transaction_type = 'MASUK'
            AND date(transaction_time)
                BETWEEN ? AND ?
        """,
        (
            start_date,
            end_date
        )
    ).fetchone()["total"]

    total_out = connection.execute(
        """
        SELECT
            COALESCE(
                SUM(quantity),
                0
            ) AS total
        FROM transactions
        WHERE
            transaction_type = 'KELUAR'
            AND date(transaction_time)
                BETWEEN ? AND ?
        """,
        (
            start_date,
            end_date
        )
    ).fetchone()["total"]

    total_transactions = connection.execute(
        """
        SELECT COUNT(*) AS total
        FROM transactions
        WHERE
            date(transaction_time)
            BETWEEN ? AND ?
        """,
        (
            start_date,
            end_date
        )
    ).fetchone()["total"]

    product_summary = connection.execute(
        """
        SELECT
            products.product_code,
            products.part_number,
            products.name,
            products.category,
            products.unit,

            COALESCE(
                SUM(
                    CASE
                        WHEN
                            transactions.transaction_type
                            = 'MASUK'
                        THEN
                            transactions.quantity
                        ELSE
                            0
                    END
                ),
                0
            ) AS total_in,

            COALESCE(
                SUM(
                    CASE
                        WHEN
                            transactions.transaction_type
                            = 'KELUAR'
                        THEN
                            transactions.quantity
                        ELSE
                            0
                    END
                ),
                0
            ) AS total_out

        FROM transactions

        JOIN products
            ON transactions.product_id =
               products.id

        WHERE
            date(
                transactions.transaction_time
            )
            BETWEEN ? AND ?

        GROUP BY
            products.id,
            products.product_code,
            products.part_number,
            products.name,
            products.category,
            products.unit

        ORDER BY
            products.name ASC
        """,
        (
            start_date,
            end_date
        )
    ).fetchall()

    current_products = connection.execute(
        """
        SELECT
            product_code,
            part_number,
            name,
            category,
            unit,
            stock
        FROM products
        ORDER BY
            name ASC
        """
    ).fetchall()

    connection.close()

    return render_template(
        "reports.html",

        selected_date=
            selected_date.strftime(
                "%Y-%m-%d"
            ),

        week_start=
            monday.strftime(
                "%d/%m/%Y"
            ),

        week_end=
            sunday.strftime(
                "%d/%m/%Y"
            ),

        total_transactions=
            total_transactions,

        total_in=
            total_in,

        total_out=
            total_out,

        weekly_transactions=
            weekly_transactions,

        product_summary=
            product_summary,

        current_products=
            current_products
    )


# =========================================================
# RUN SERVER
# =========================================================

if __name__ == "__main__":

    print()
    print("=" * 65)
    print("PT ALDIGENS PUTERA PERSADA")
    print("INVENTORY MANAGEMENT SYSTEM")
    print("=" * 65)
    print(
        "Login : http://127.0.0.1:5000/login"
    )
    print(
        "Local : http://127.0.0.1:5000"
    )
    print(
        "LAN   : http://192.168.2.10:5000"
    )
    print("=" * 65)
    print()

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )