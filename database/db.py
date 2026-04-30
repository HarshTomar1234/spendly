import os
import sqlite3
from werkzeug.security import generate_password_hash

_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "spendly.db"
)


def get_db():
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():
    con = get_db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL,
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at    TEXT DEFAULT (datetime('now'))
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            amount      REAL NOT NULL,
            category    TEXT NOT NULL,
            date        TEXT NOT NULL,
            description TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    con.commit()
    con.close()


def seed_db():
    con = get_db()

    row = con.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()
    if row["cnt"] > 0:
        con.close()
        return

    pw_hash = generate_password_hash("demo123")
    con.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Demo User", "demo@spendly.com", pw_hash),
    )
    con.commit()

    user = con.execute(
        "SELECT id FROM users WHERE email = ?", ("demo@spendly.com",)
    ).fetchone()
    uid = user["id"]

    expenses = [
        (uid, 12.50,  "Food",          "2026-04-03", "Lunch at cafe"),
        (uid, 45.00,  "Transport",     "2026-04-05", "Monthly bus pass"),
        (uid, 120.00, "Bills",         "2026-04-07", "Electricity bill"),
        (uid, 30.00,  "Health",        "2026-04-10", "Pharmacy"),
        (uid, 18.75,  "Entertainment", "2026-04-13", "Streaming subscription"),
        (uid, 65.20,  "Shopping",      "2026-04-17", "Groceries"),
        (uid, 8.00,   "Other",         "2026-04-20", "Notebook"),
        (uid, 22.00,  "Food",          "2026-04-25", "Dinner with friends"),
    ]

    con.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) "
        "VALUES (?, ?, ?, ?, ?)",
        expenses,
    )
    con.commit()
    con.close()


def create_user(name, email, password):
    pw_hash = generate_password_hash(password)
    con = get_db()
    con.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, pw_hash),
    )
    con.commit()
    con.close()
