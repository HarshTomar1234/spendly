"""
Tests for Step 07 — Add Expense feature.

Covers:
  - Unit tests for insert_expense() in database/queries.py
  - GET /expenses/add: auth guard, 200 response, form structure, all 7 categories
  - POST /expenses/add: auth guard, valid submission, validation errors,
    optional description, DB side-effects, form re-population on error

All tests use a temporary SQLite database via monkeypatching so the real
spendly.db is never touched. Auth is simulated via session_transaction().
"""

import sqlite3
import pytest
from werkzeug.security import generate_password_hash

import database.db as db_module
from database.queries import insert_expense
from app import app as flask_app


# ------------------------------------------------------------------ #
# Constants                                                           #
# ------------------------------------------------------------------ #

VALID_CATEGORIES = [
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
]


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #

@pytest.fixture()
def tmp_db(monkeypatch, tmp_path):
    """
    Fresh temporary SQLite database with the full Spendly schema.
    Monkeypatches get_db() in both db_module and queries module so
    the real spendly.db is never touched.
    Seeds one test user and returns a dict with user_id and the _get_db factory.
    """
    db_path = str(tmp_path / "test_add_expense.db")

    def _get_db():
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    monkeypatch.setattr(db_module, "get_db", _get_db)

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

    pw = generate_password_hash("testpassword")
    con.execute(
        "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
        ("Add Expense User", "addexpense@example.com", pw, "2026-01-01 10:00:00"),
    )
    con.commit()
    user_id = con.execute(
        "SELECT id FROM users WHERE email = ?", ("addexpense@example.com",)
    ).fetchone()["id"]
    con.close()

    return {"user_id": user_id, "get_db": _get_db}


@pytest.fixture()
def client(tmp_db):
    """Flask test client pre-configured for testing, using the patched DB."""
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test-secret-07"
    with flask_app.test_client() as c:
        yield c, tmp_db["user_id"], tmp_db["get_db"]


@pytest.fixture()
def auth_client(client):
    """Test client already authenticated as the seeded test user."""
    c, user_id, get_db = client
    with c.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "Add Expense User"
    return c, user_id, get_db


# ------------------------------------------------------------------ #
# Helper                                                              #
# ------------------------------------------------------------------ #

def _set_session(c, user_id, name="Add Expense User"):
    """Directly inject session data without going through the login route."""
    with c.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = name


# ------------------------------------------------------------------ #
# Unit tests — insert_expense                                         #
# ------------------------------------------------------------------ #

class TestInsertExpense:
    def test_valid_insert_creates_row(self, tmp_db):
        """Valid insert: row appears in the DB with correct field values."""
        user_id = tmp_db["user_id"]
        get_db = tmp_db["get_db"]

        insert_expense(user_id, 50.0, "Food", "2026-03-20", "Lunch")

        con = get_db()
        row = con.execute(
            "SELECT * FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchone()
        con.close()

        assert row is not None, "Expected a row to be inserted into the expenses table"
        assert row["user_id"] == user_id, "user_id field should match the inserted value"
        assert abs(row["amount"] - 50.0) < 0.001, "amount field should be 50.0"
        assert row["category"] == "Food", "category field should be 'Food'"
        assert row["date"] == "2026-03-20", "date field should be '2026-03-20'"
        assert row["description"] == "Lunch", "description field should be 'Lunch'"

    def test_null_description_stored_as_null(self, tmp_db):
        """insert_expense with description=None must store NULL, not a blank string."""
        user_id = tmp_db["user_id"]
        get_db = tmp_db["get_db"]

        insert_expense(user_id, 25.0, "Transport", "2026-03-21", None)

        con = get_db()
        row = con.execute(
            "SELECT description FROM expenses WHERE user_id = ? AND date = ?",
            (user_id, "2026-03-21"),
        ).fetchone()
        con.close()

        assert row is not None, "Expected the expense row to exist in the DB"
        assert row["description"] is None, (
            "description should be stored as NULL when None is passed"
        )

    def test_insert_increments_row_count(self, tmp_db):
        """Each call to insert_expense adds exactly one new row."""
        user_id = tmp_db["user_id"]
        get_db = tmp_db["get_db"]

        con = get_db()
        before = con.execute(
            "SELECT COUNT(*) AS cnt FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchone()["cnt"]
        con.close()

        insert_expense(user_id, 10.0, "Other", "2026-04-01", "Test entry")

        con = get_db()
        after = con.execute(
            "SELECT COUNT(*) AS cnt FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchone()["cnt"]
        con.close()

        assert after == before + 1, (
            "insert_expense should add exactly one row to the expenses table"
        )


# ------------------------------------------------------------------ #
# Route tests — GET /expenses/add                                     #
# ------------------------------------------------------------------ #

class TestGetAddExpense:
    def test_unauthenticated_get_redirects_to_login(self, client):
        """Unauthenticated GET /expenses/add must redirect to /login."""
        c, _, _ = client
        resp = c.get("/expenses/add")
        assert resp.status_code == 302, (
            "Unauthenticated GET should return 302, not 200"
        )
        assert "/login" in resp.headers["Location"], (
            "Unauthenticated GET should redirect to /login"
        )

    def test_authenticated_get_returns_200(self, auth_client):
        """Authenticated GET /expenses/add must return 200."""
        c, _, _ = auth_client
        resp = c.get("/expenses/add")
        assert resp.status_code == 200, (
            "Authenticated GET /expenses/add should return 200"
        )

    def test_get_contains_select_element(self, auth_client):
        """Response body must contain a <select> element for the category dropdown."""
        c, _, _ = auth_client
        resp = c.get("/expenses/add")
        body = resp.data.decode()
        assert "<select" in body, (
            "The add-expense form must include a <select> category dropdown"
        )

    @pytest.mark.parametrize("category", VALID_CATEGORIES)
    def test_get_contains_all_seven_categories(self, auth_client, category):
        """All 7 fixed categories must appear in the category dropdown."""
        c, _, _ = auth_client
        resp = c.get("/expenses/add")
        body = resp.data.decode()
        assert category in body, (
            f"Category '{category}' must appear in the add-expense form"
        )

    def test_get_form_has_post_method(self, auth_client):
        """The form element must declare method POST."""
        c, _, _ = auth_client
        resp = c.get("/expenses/add")
        body = resp.data.decode().lower()
        assert "method" in body, "The form must have a method attribute"
        assert 'method="post"' in body or "method='post'" in body, (
            "The form method must be POST"
        )

    def test_get_form_has_amount_field(self, auth_client):
        """The form must include an amount input field."""
        c, _, _ = auth_client
        resp = c.get("/expenses/add")
        body = resp.data.decode()
        assert 'name="amount"' in body, (
            "The add-expense form must have an amount input named 'amount'"
        )

    def test_get_form_has_date_field(self, auth_client):
        """The form must include a date input field."""
        c, _, _ = auth_client
        resp = c.get("/expenses/add")
        body = resp.data.decode()
        assert 'name="date"' in body, (
            "The add-expense form must have a date input named 'date'"
        )

    def test_get_form_has_description_field(self, auth_client):
        """The form must include a description input field."""
        c, _, _ = auth_client
        resp = c.get("/expenses/add")
        body = resp.data.decode()
        assert 'name="description"' in body, (
            "The add-expense form must have a description field named 'description'"
        )

    def test_get_page_contains_cancel_link_to_profile(self, auth_client):
        """The form must include a cancel link pointing back to /profile."""
        c, _, _ = auth_client
        resp = c.get("/expenses/add")
        body = resp.data.decode()
        assert "/profile" in body, (
            "The add-expense page should include a cancel link to /profile"
        )


# ------------------------------------------------------------------ #
# Route tests — POST /expenses/add                                    #
# ------------------------------------------------------------------ #

class TestPostAddExpense:
    def test_unauthenticated_post_redirects_to_login(self, client):
        """Unauthenticated POST /expenses/add must redirect to /login."""
        c, _, _ = client
        resp = c.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        assert resp.status_code == 302, (
            "Unauthenticated POST should return 302"
        )
        assert "/login" in resp.headers["Location"], (
            "Unauthenticated POST should redirect to /login"
        )

    def test_valid_post_redirects_to_profile(self, auth_client):
        """Valid POST /expenses/add must redirect to /profile."""
        c, _, _ = auth_client
        resp = c.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        assert resp.status_code == 302, (
            "Valid POST should return 302 redirect"
        )
        assert "/profile" in resp.headers["Location"], (
            "Valid POST should redirect to /profile"
        )

    def test_valid_post_inserts_row_in_db(self, auth_client):
        """After a valid POST, the new expense row must exist in the database."""
        c, user_id, get_db = auth_client
        c.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })

        con = get_db()
        row = con.execute(
            "SELECT * FROM expenses WHERE user_id = ? AND date = ? AND category = ?",
            (user_id, "2026-03-20", "Food"),
        ).fetchone()
        con.close()

        assert row is not None, (
            "A new expense row should be present in the DB after a valid POST"
        )
        assert abs(row["amount"] - 50.0) < 0.001, "Stored amount should be 50.0"
        assert row["description"] == "Lunch", "Stored description should be 'Lunch'"

    def test_missing_amount_returns_200(self, auth_client):
        """POST with missing amount must re-render the form (200)."""
        c, _, _ = auth_client
        resp = c.post("/expenses/add", data={
            "amount": "",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        assert resp.status_code == 200, (
            "Missing amount should re-render the form with status 200"
        )

    def test_missing_amount_shows_error(self, auth_client):
        """POST with missing amount must show an error message in the response."""
        c, _, _ = auth_client
        resp = c.post("/expenses/add", data={
            "amount": "",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        body = resp.data.decode()
        assert "error" in body.lower() or "required" in body.lower() or "amount" in body.lower(), (
            "Missing amount should produce a visible error message in the form"
        )

    def test_zero_amount_returns_200(self, auth_client):
        """POST with amount=0 must re-render the form (200)."""
        c, _, _ = auth_client
        resp = c.post("/expenses/add", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        assert resp.status_code == 200, (
            "amount=0 should re-render the form with status 200"
        )

    def test_zero_amount_shows_error(self, auth_client):
        """POST with amount=0 must show an error message."""
        c, _, _ = auth_client
        resp = c.post("/expenses/add", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        body = resp.data.decode()
        assert "error" in body.lower() or "greater" in body.lower() or "zero" in body.lower(), (
            "amount=0 should produce an error message about a non-positive value"
        )

    def test_non_numeric_amount_returns_200(self, auth_client):
        """POST with a non-numeric amount must re-render the form (200)."""
        c, _, _ = auth_client
        resp = c.post("/expenses/add", data={
            "amount": "abc",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        assert resp.status_code == 200, (
            "Non-numeric amount should re-render the form with status 200"
        )

    def test_non_numeric_amount_shows_error(self, auth_client):
        """POST with a non-numeric amount must show an error message."""
        c, _, _ = auth_client
        resp = c.post("/expenses/add", data={
            "amount": "abc",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        body = resp.data.decode()
        assert "error" in body.lower() or "valid" in body.lower() or "number" in body.lower(), (
            "Non-numeric amount should produce an error message"
        )

    def test_invalid_category_returns_200(self, auth_client):
        """POST with a category not in the fixed list must re-render the form (200)."""
        c, _, _ = auth_client
        resp = c.post("/expenses/add", data={
            "amount": "50.0",
            "category": "InvalidCategory",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        assert resp.status_code == 200, (
            "Invalid category should re-render the form with status 200"
        )

    def test_invalid_category_shows_error(self, auth_client):
        """POST with an invalid category must show an error message."""
        c, _, _ = auth_client
        resp = c.post("/expenses/add", data={
            "amount": "50.0",
            "category": "InvalidCategory",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        body = resp.data.decode()
        assert "error" in body.lower() or "invalid" in body.lower() or "category" in body.lower(), (
            "Invalid category should produce an error message"
        )

    @pytest.mark.parametrize("bad_date", [
        "not-a-date",
        "20260320",
        "03-20-2026",
        "2026/03/20",
        "2026-13-01",
        "2026-00-15",
        "abcd-ef-gh",
    ])
    def test_invalid_date_returns_200(self, auth_client, bad_date):
        """POST with a non-YYYY-MM-DD date must re-render the form (200)."""
        c, _, _ = auth_client
        resp = c.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": bad_date,
            "description": "Lunch",
        })
        assert resp.status_code == 200, (
            f"Invalid date '{bad_date}' should re-render the form with status 200"
        )

    @pytest.mark.parametrize("bad_date", [
        "not-a-date",
        "20260320",
        "03-20-2026",
        "2026/03/20",
        "2026-13-01",
        "2026-00-15",
        "abcd-ef-gh",
    ])
    def test_invalid_date_shows_error(self, auth_client, bad_date):
        """POST with a non-YYYY-MM-DD date must show an error message."""
        c, _, _ = auth_client
        resp = c.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": bad_date,
            "description": "Lunch",
        })
        body = resp.data.decode()
        assert "error" in body.lower() or "date" in body.lower() or "format" in body.lower(), (
            f"Invalid date '{bad_date}' should produce an error message"
        )

    def test_no_description_redirects_to_profile(self, auth_client):
        """POST with no description (optional field) must redirect to /profile."""
        c, _, _ = auth_client
        resp = c.post("/expenses/add", data={
            "amount": "30.0",
            "category": "Transport",
            "date": "2026-04-01",
            "description": "",
        })
        assert resp.status_code == 302, (
            "Empty description is optional; POST should redirect (302)"
        )
        assert "/profile" in resp.headers["Location"], (
            "POST with no description should redirect to /profile"
        )

    def test_no_description_stores_null(self, auth_client):
        """POST with blank description must store NULL (not empty string) in the DB."""
        c, user_id, get_db = auth_client
        c.post("/expenses/add", data={
            "amount": "30.0",
            "category": "Transport",
            "date": "2026-04-01",
            "description": "",
        })

        con = get_db()
        row = con.execute(
            "SELECT description FROM expenses WHERE user_id = ? AND date = ? AND category = ?",
            (user_id, "2026-04-01", "Transport"),
        ).fetchone()
        con.close()

        assert row is not None, "The expense row must exist in the DB"
        assert row["description"] is None, (
            "An empty description submitted in the form must be stored as NULL, not empty string"
        )

    def test_error_repopulates_amount(self, auth_client):
        """On a validation error the form should echo the submitted amount back."""
        c, _, _ = auth_client
        resp = c.post("/expenses/add", data={
            "amount": "99.99",
            "category": "InvalidCategory",
            "date": "2026-03-20",
            "description": "My note",
        })
        body = resp.data.decode()
        assert "99.99" in body, (
            "The previously submitted amount should be echoed back when the form re-renders on error"
        )

    def test_error_repopulates_description(self, auth_client):
        """On a validation error the form should echo the submitted description back."""
        c, _, _ = auth_client
        resp = c.post("/expenses/add", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "My special note",
        })
        body = resp.data.decode()
        assert "My special note" in body, (
            "The previously submitted description should be echoed back when the form re-renders on error"
        )

    def test_error_repopulates_date(self, auth_client):
        """On a validation error the form should echo the submitted date back."""
        c, _, _ = auth_client
        resp = c.post("/expenses/add", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-05-15",
            "description": "",
        })
        body = resp.data.decode()
        assert "2026-05-15" in body, (
            "The previously submitted date should be echoed back when the form re-renders on error"
        )

    def test_negative_amount_returns_200(self, auth_client):
        """POST with a negative amount must re-render the form (200)."""
        c, _, _ = auth_client
        resp = c.post("/expenses/add", data={
            "amount": "-10.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Refund attempt",
        })
        assert resp.status_code == 200, (
            "Negative amount should re-render the form with status 200"
        )

    def test_negative_amount_shows_error(self, auth_client):
        """POST with a negative amount must show an error message."""
        c, _, _ = auth_client
        resp = c.post("/expenses/add", data={
            "amount": "-10.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Refund attempt",
        })
        body = resp.data.decode()
        assert "error" in body.lower() or "greater" in body.lower() or "zero" in body.lower(), (
            "Negative amount should produce an error message about a non-positive value"
        )

    def test_valid_post_does_not_insert_for_another_user(self, auth_client):
        """A valid POST by user A must not create a row attributed to user B."""
        c, user_id, get_db = auth_client

        # Insert a second user to ensure isolation
        con = get_db()
        from werkzeug.security import generate_password_hash as gph
        con.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Other User", "other@example.com", gph("pass")),
        )
        con.commit()
        other_id = con.execute(
            "SELECT id FROM users WHERE email = ?", ("other@example.com",)
        ).fetchone()["id"]
        con.close()

        c.post("/expenses/add", data={
            "amount": "75.0",
            "category": "Bills",
            "date": "2026-04-10",
            "description": "Isolation test",
        })

        con = get_db()
        other_rows = con.execute(
            "SELECT * FROM expenses WHERE user_id = ?", (other_id,)
        ).fetchall()
        con.close()

        assert len(other_rows) == 0, (
            "A valid POST should only insert a row for the authenticated user, not another user"
        )

    def test_whitespace_only_description_stores_null(self, auth_client):
        """A description containing only whitespace must be stored as NULL."""
        c, user_id, get_db = auth_client
        c.post("/expenses/add", data={
            "amount": "20.0",
            "category": "Other",
            "date": "2026-04-05",
            "description": "   ",
        })

        con = get_db()
        row = con.execute(
            "SELECT description FROM expenses WHERE user_id = ? AND date = ? AND category = ?",
            (user_id, "2026-04-05", "Other"),
        ).fetchone()
        con.close()

        assert row is not None, "Expense row must exist after a valid POST"
        assert row["description"] is None, (
            "A whitespace-only description should be stripped and stored as NULL"
        )
