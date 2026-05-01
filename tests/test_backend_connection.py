"""
Tests for Step 05 — Backend Connection for Profile Page.

Unit tests for database/queries.py functions and route tests for GET /profile.
Uses a temporary SQLite database so the real spendly.db is never touched.
"""
import sqlite3
import tempfile
import os
import pytest

import database.db as db_module
from database.queries import (
    get_user_by_id,
    get_recent_transactions,
    get_summary_stats,
    get_category_breakdown,
)
from app import app as flask_app
from werkzeug.security import generate_password_hash


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #

@pytest.fixture()
def tmp_db(monkeypatch, tmp_path):
    """
    Creates a fresh temporary SQLite database with the Spendly schema,
    seeds one user and several expenses, and monkeypatches get_db() so
    every query function uses it instead of spendly.db.
    """
    db_path = str(tmp_path / "test.db")

    def _get_db():
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    monkeypatch.setattr(db_module, "get_db", _get_db)
    # Also patch the reference imported into queries.py
    import database.queries as q_module
    monkeypatch.setattr(q_module, "get_db", _get_db)

    # Build schema
    con = _get_db()
    con.execute("""
        CREATE TABLE users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL,
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at    TEXT DEFAULT (datetime('now'))
        )
    """)
    con.execute("""
        CREATE TABLE expenses (
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

    # Seed one user
    pw = generate_password_hash("password123")
    con.execute(
        "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
        ("Test User", "test@example.com", pw, "2026-01-15 10:00:00"),
    )
    con.commit()
    user_id = con.execute("SELECT id FROM users WHERE email = ?", ("test@example.com",)).fetchone()["id"]

    # Seed expenses
    expenses = [
        (user_id, 120.00, "Bills",         "2026-04-07", "Electricity bill"),
        (user_id,  65.20, "Shopping",      "2026-04-17", "Groceries"),
        (user_id,  45.00, "Transport",     "2026-04-05", "Monthly bus pass"),
        (user_id,  22.00, "Food",          "2026-04-25", "Dinner with friends"),
        (user_id,  30.00, "Health",        "2026-04-10", "Pharmacy"),
        (user_id,  18.75, "Entertainment", "2026-04-13", "Streaming subscription"),
        (user_id,   8.00, "Other",         "2026-04-20", "Notebook"),
        (user_id,  12.50, "Food",          "2026-04-03", "Lunch at cafe"),
    ]
    con.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        expenses,
    )
    con.commit()
    con.close()

    return {"user_id": user_id, "get_db": _get_db}


@pytest.fixture()
def empty_db(monkeypatch, tmp_path):
    """A seeded user with zero expenses."""
    db_path = str(tmp_path / "empty.db")

    def _get_db():
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    monkeypatch.setattr(db_module, "get_db", _get_db)
    import database.queries as q_module
    monkeypatch.setattr(q_module, "get_db", _get_db)

    con = _get_db()
    con.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    con.execute("""
        CREATE TABLE expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            date TEXT NOT NULL,
            description TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    pw = generate_password_hash("password123")
    con.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Empty User", "empty@example.com", pw),
    )
    con.commit()
    user_id = con.execute("SELECT id FROM users WHERE email = ?", ("empty@example.com",)).fetchone()["id"]
    con.close()

    return {"user_id": user_id}


@pytest.fixture()
def client(tmp_db):
    """Flask test client with session support, patched to use tmp_db."""
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test-secret"
    with flask_app.test_client() as c:
        yield c, tmp_db["user_id"]


# ------------------------------------------------------------------ #
# Unit tests — get_user_by_id                                         #
# ------------------------------------------------------------------ #

def test_get_user_by_id_valid(tmp_db):
    result = get_user_by_id(tmp_db["user_id"])
    assert result is not None
    assert result["name"] == "Test User"
    assert result["email"] == "test@example.com"
    assert "member_since" in result


def test_get_user_by_id_missing(tmp_db):
    result = get_user_by_id(99999)
    assert result is None


# ------------------------------------------------------------------ #
# Unit tests — get_summary_stats                                      #
# ------------------------------------------------------------------ #

def test_get_summary_stats_with_expenses(tmp_db):
    result = get_summary_stats(tmp_db["user_id"])
    assert result["transaction_count"] == 8
    assert abs(result["total_spent"] - 321.45) < 0.01
    assert result["top_category"] == "Bills"


def test_get_summary_stats_no_expenses(empty_db):
    result = get_summary_stats(empty_db["user_id"])
    assert result["total_spent"] == 0.0
    assert result["transaction_count"] == 0
    assert result["top_category"] == "—"


# ------------------------------------------------------------------ #
# Unit tests — get_recent_transactions                                #
# ------------------------------------------------------------------ #

def test_get_recent_transactions_with_expenses(tmp_db):
    result = get_recent_transactions(tmp_db["user_id"])
    assert len(result) == 8
    # Each item has required keys
    for item in result:
        assert "date" in item
        assert "description" in item
        assert "category" in item
        assert "amount" in item
    # Ordered newest-first (date DESC)
    dates = [item["date"] for item in result]
    assert dates == sorted(dates, reverse=True)


def test_get_recent_transactions_no_expenses(empty_db):
    result = get_recent_transactions(empty_db["user_id"])
    assert result == []


# ------------------------------------------------------------------ #
# Unit tests — get_category_breakdown                                 #
# ------------------------------------------------------------------ #

def test_get_category_breakdown_with_expenses(tmp_db):
    result = get_category_breakdown(tmp_db["user_id"])
    assert len(result) == 7
    # Ordered by amount descending
    amounts = [item["amount"] for item in result]
    assert amounts == sorted(amounts, reverse=True)
    # Percentages sum to 100
    assert sum(item["pct"] for item in result) == 100
    # Each item has correct keys
    for item in result:
        assert "name" in item
        assert "amount" in item
        assert "pct" in item
        assert isinstance(item["pct"], int)


def test_get_category_breakdown_no_expenses(empty_db):
    result = get_category_breakdown(empty_db["user_id"])
    assert result == []


# ------------------------------------------------------------------ #
# Route tests — GET /profile                                          #
# ------------------------------------------------------------------ #

def test_profile_unauthenticated(client):
    c, _ = client
    response = c.get("/profile")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_profile_authenticated_returns_200(client):
    c, user_id = client
    with c.session_transaction() as sess:
        sess["user_id"]   = user_id
        sess["user_name"] = "Test User"
    response = c.get("/profile")
    assert response.status_code == 200


def test_profile_shows_real_user_data(client):
    c, user_id = client
    with c.session_transaction() as sess:
        sess["user_id"]   = user_id
        sess["user_name"] = "Test User"
    response = c.get("/profile")
    body = response.data.decode()
    assert "Test User" in body
    assert "test@example.com" in body


def test_profile_contains_rupee_symbol(client):
    c, user_id = client
    with c.session_transaction() as sess:
        sess["user_id"]   = user_id
        sess["user_name"] = "Test User"
    response = c.get("/profile")
    body = response.data.decode()
    assert "&#8377;" in body or "₹" in body


def test_profile_new_user_shows_empty_state(tmp_db):
    """A user with no expenses should see zeros, not an error."""
    flask_app.config["TESTING"] = True
    # Insert a second user with no expenses using the patched get_db
    con = tmp_db["get_db"]()
    pw = generate_password_hash("newpass")
    con.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("New User", "new@example.com", pw),
    )
    con.commit()
    new_id = con.execute("SELECT id FROM users WHERE email = ?", ("new@example.com",)).fetchone()["id"]
    con.close()

    with flask_app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"]   = new_id
            sess["user_name"] = "New User"
        response = c.get("/profile")
        assert response.status_code == 200
        body = response.data.decode()
        assert "New User" in body
