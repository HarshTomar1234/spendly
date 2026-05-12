"""
Tests for Step 08 — Edit Expense feature.

Covers:
  - Unit tests for get_expense_by_id() and update_expense() in database/queries.py
  - GET /expenses/<expense_id>/edit: auth guard, 404 for missing/other-user expense,
    200 response, pre-filled form fields, all 7 categories in select
  - POST /expenses/<expense_id>/edit: auth guard, valid submission, redirect to /profile,
    DB side-effects, flash message, validation errors (amount/category/date),
    optional description (NULL), form re-population on error

All tests use a temporary SQLite database via monkeypatching so the real
spendly.db is never touched. Auth is simulated via session_transaction().
"""

import sqlite3
import pytest
from werkzeug.security import generate_password_hash

import database.db as db_module
from database.queries import get_expense_by_id, update_expense
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
    Seeds one primary test user (user_id) and one secondary user
    (other_user_id) for ownership isolation tests.
    Returns a dict with user_id, other_user_id, and the _get_db factory.
    """
    db_path = str(tmp_path / "test_edit_expense.db")

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

    # Seed primary user
    pw = generate_password_hash("testpassword")
    con.execute(
        "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
        ("Edit Expense User", "editexpense@example.com", pw, "2026-01-01 10:00:00"),
    )
    con.commit()
    user_id = con.execute(
        "SELECT id FROM users WHERE email = ?", ("editexpense@example.com",)
    ).fetchone()["id"]

    # Seed secondary user for ownership tests
    con.execute(
        "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
        ("Other User", "other@example.com", pw, "2026-01-02 10:00:00"),
    )
    con.commit()
    other_user_id = con.execute(
        "SELECT id FROM users WHERE email = ?", ("other@example.com",)
    ).fetchone()["id"]
    con.close()

    return {"user_id": user_id, "other_user_id": other_user_id, "get_db": _get_db}


@pytest.fixture()
def client(tmp_db):
    """Flask test client pre-configured for testing, using the patched DB."""
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test-secret-08"
    with flask_app.test_client() as c:
        yield c, tmp_db["user_id"], tmp_db["other_user_id"], tmp_db["get_db"]


@pytest.fixture()
def auth_client(client):
    """Test client already authenticated as the seeded primary test user."""
    c, user_id, other_user_id, get_db = client
    with c.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "Edit Expense User"
    return c, user_id, other_user_id, get_db


@pytest.fixture()
def seeded_expense(tmp_db):
    """
    Inserts one expense row for the primary user and returns its id.
    Also inserts one expense for the other user.
    Returns dict with expense_id (primary user's) and other_expense_id.
    """
    get_db = tmp_db["get_db"]
    user_id = tmp_db["user_id"]
    other_user_id = tmp_db["other_user_id"]

    con = get_db()
    con.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        (user_id, 42.00, "Food", "2026-04-10", "Original description"),
    )
    con.commit()
    expense_id = con.execute(
        "SELECT id FROM expenses WHERE user_id = ? AND date = ?",
        (user_id, "2026-04-10"),
    ).fetchone()["id"]

    con.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        (other_user_id, 99.00, "Bills", "2026-04-11", "Other user's expense"),
    )
    con.commit()
    other_expense_id = con.execute(
        "SELECT id FROM expenses WHERE user_id = ? AND date = ?",
        (other_user_id, "2026-04-11"),
    ).fetchone()["id"]
    con.close()

    return {
        "expense_id": expense_id,
        "other_expense_id": other_expense_id,
        "user_id": user_id,
        "other_user_id": other_user_id,
        "get_db": get_db,
    }


# ------------------------------------------------------------------ #
# Helper                                                              #
# ------------------------------------------------------------------ #

def _inject_session(c, user_id, name="Edit Expense User"):
    """Directly inject session data without going through the login route."""
    with c.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = name


# ------------------------------------------------------------------ #
# Unit tests — get_expense_by_id                                      #
# ------------------------------------------------------------------ #

class TestGetExpenseById:
    def test_correct_owner_returns_dict_with_all_fields(self, seeded_expense):
        """get_expense_by_id with the correct owner must return a dict with all expected fields."""
        expense_id = seeded_expense["expense_id"]
        user_id = seeded_expense["user_id"]

        result = get_expense_by_id(expense_id, user_id)

        assert result is not None, "Expected a dict result for a valid expense_id + user_id"
        assert result["id"] == expense_id, "Returned dict must include correct id"
        assert abs(result["amount"] - 42.00) < 0.001, "Returned dict must have correct amount"
        assert result["category"] == "Food", "Returned dict must have correct category"
        assert result["date"] == "2026-04-10", "Returned dict must have correct date"
        assert "description" in result, "Returned dict must include the description key"

    def test_correct_owner_returns_correct_description(self, seeded_expense):
        """get_expense_by_id must return the stored description value."""
        expense_id = seeded_expense["expense_id"]
        user_id = seeded_expense["user_id"]

        result = get_expense_by_id(expense_id, user_id)

        assert result is not None, "Expected a dict result for a valid expense"
        # The implementation returns "" for None descriptions; accept either non-empty string
        assert "Original description" in result["description"], (
            "Returned dict must have the correct description"
        )

    def test_wrong_user_id_returns_none(self, seeded_expense):
        """get_expense_by_id with a wrong user_id must return None (ownership check)."""
        expense_id = seeded_expense["expense_id"]
        other_user_id = seeded_expense["other_user_id"]

        result = get_expense_by_id(expense_id, other_user_id)

        assert result is None, (
            "get_expense_by_id must return None when user_id does not own the expense"
        )

    def test_nonexistent_expense_id_returns_none(self, seeded_expense):
        """get_expense_by_id with an expense_id that does not exist must return None."""
        user_id = seeded_expense["user_id"]
        nonexistent_id = 999999

        result = get_expense_by_id(nonexistent_id, user_id)

        assert result is None, (
            "get_expense_by_id must return None when the expense_id does not exist"
        )


# ------------------------------------------------------------------ #
# Unit tests — update_expense                                         #
# ------------------------------------------------------------------ #

class TestUpdateExpense:
    def test_correct_owner_updates_all_fields_and_returns_rowcount_1(self, seeded_expense):
        """update_expense with the correct owner must update all fields and return rowcount 1."""
        expense_id = seeded_expense["expense_id"]
        user_id = seeded_expense["user_id"]
        get_db = seeded_expense["get_db"]

        rowcount = update_expense(
            expense_id, user_id, 99.99, "Transport", "2026-05-01", "Updated description"
        )

        assert rowcount == 1, "update_expense must return rowcount 1 for a successful update"

        con = get_db()
        row = con.execute(
            "SELECT amount, category, date, description FROM expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()
        con.close()

        assert row is not None, "The expense row must still exist after update"
        assert abs(row["amount"] - 99.99) < 0.001, "amount must be updated to 99.99"
        assert row["category"] == "Transport", "category must be updated to 'Transport'"
        assert row["date"] == "2026-05-01", "date must be updated to '2026-05-01'"
        assert row["description"] == "Updated description", (
            "description must be updated to 'Updated description'"
        )

    def test_wrong_user_id_returns_rowcount_0(self, seeded_expense):
        """update_expense with a wrong user_id must return rowcount 0."""
        expense_id = seeded_expense["expense_id"]
        other_user_id = seeded_expense["other_user_id"]

        rowcount = update_expense(
            expense_id, other_user_id, 1.00, "Food", "2026-05-01", None
        )

        assert rowcount == 0, (
            "update_expense must return rowcount 0 when user_id does not own the expense"
        )

    def test_wrong_user_id_leaves_db_unchanged(self, seeded_expense):
        """update_expense with a wrong user_id must not alter the DB row."""
        expense_id = seeded_expense["expense_id"]
        user_id = seeded_expense["user_id"]
        other_user_id = seeded_expense["other_user_id"]
        get_db = seeded_expense["get_db"]

        # Capture original values
        con = get_db()
        original = con.execute(
            "SELECT amount, category, date, description FROM expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()
        con.close()

        update_expense(expense_id, other_user_id, 1.00, "Other", "2000-01-01", "malicious")

        con = get_db()
        after = con.execute(
            "SELECT amount, category, date, description FROM expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()
        con.close()

        assert abs(after["amount"] - original["amount"]) < 0.001, (
            "amount must not change when update is rejected due to wrong user_id"
        )
        assert after["category"] == original["category"], (
            "category must not change when update is rejected"
        )
        assert after["date"] == original["date"], (
            "date must not change when update is rejected"
        )

    def test_update_to_null_description_stores_null(self, seeded_expense):
        """update_expense with description=None must store NULL in the DB."""
        expense_id = seeded_expense["expense_id"]
        user_id = seeded_expense["user_id"]
        get_db = seeded_expense["get_db"]

        update_expense(expense_id, user_id, 42.00, "Food", "2026-04-10", None)

        con = get_db()
        row = con.execute(
            "SELECT description FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        con.close()

        assert row["description"] is None, (
            "update_expense with description=None must store NULL, not an empty string"
        )


# ------------------------------------------------------------------ #
# Route tests — Auth guards                                           #
# ------------------------------------------------------------------ #

class TestEditExpenseAuthGuard:
    def test_unauthenticated_get_redirects_to_login(self, client, seeded_expense):
        """Unauthenticated GET /expenses/<id>/edit must redirect to /login."""
        c, _, _, _ = client
        expense_id = seeded_expense["expense_id"]
        resp = c.get(f"/expenses/{expense_id}/edit")
        assert resp.status_code == 302, (
            "Unauthenticated GET /expenses/<id>/edit should return 302"
        )
        assert "/login" in resp.headers["Location"], (
            "Unauthenticated GET should redirect to /login"
        )

    def test_unauthenticated_post_redirects_to_login(self, client, seeded_expense):
        """Unauthenticated POST /expenses/<id>/edit must redirect to /login."""
        c, _, _, _ = client
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "50.0",
            "category": "Food",
            "date": "2026-05-01",
            "description": "Updated",
        })
        assert resp.status_code == 302, (
            "Unauthenticated POST /expenses/<id>/edit should return 302"
        )
        assert "/login" in resp.headers["Location"], (
            "Unauthenticated POST should redirect to /login"
        )


# ------------------------------------------------------------------ #
# Route tests — 404 and ownership                                     #
# ------------------------------------------------------------------ #

class TestEditExpense404AndOwnership:
    def test_get_nonexistent_expense_returns_404(self, client, seeded_expense):
        """GET /expenses/<id>/edit for a non-existent expense_id must return 404."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        nonexistent_id = 999999
        resp = c.get(f"/expenses/{nonexistent_id}/edit")
        assert resp.status_code == 404, (
            "GET for a non-existent expense_id must return 404"
        )

    def test_get_another_users_expense_returns_404(self, client, seeded_expense):
        """GET /expenses/<id>/edit for another user's expense must return 404."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        # other_expense_id belongs to other_user_id, not user_id
        other_expense_id = seeded_expense["other_expense_id"]
        resp = c.get(f"/expenses/{other_expense_id}/edit")
        assert resp.status_code == 404, (
            "GET for another user's expense must return 404 (ownership check)"
        )


# ------------------------------------------------------------------ #
# Route tests — GET happy path                                        #
# ------------------------------------------------------------------ #

class TestGetEditExpenseHappyPath:
    def test_authenticated_get_returns_200(self, client, seeded_expense):
        """Authenticated GET /expenses/<id>/edit must return 200."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.get(f"/expenses/{expense_id}/edit")
        assert resp.status_code == 200, (
            "Authenticated GET /expenses/<id>/edit should return 200"
        )

    def test_get_form_prefilled_with_amount(self, client, seeded_expense):
        """GET /expenses/<id>/edit must pre-fill the form with the current amount."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        # The seeded expense has amount=42.0; check for "42" in the body
        assert "42" in body, (
            "The edit form must be pre-filled with the current expense amount"
        )

    def test_get_form_prefilled_with_date(self, client, seeded_expense):
        """GET /expenses/<id>/edit must pre-fill the form with the current date."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert "2026-04-10" in body, (
            "The edit form must be pre-filled with the current expense date"
        )

    def test_get_form_prefilled_with_description(self, client, seeded_expense):
        """GET /expenses/<id>/edit must pre-fill the form with the current description."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert "Original description" in body, (
            "The edit form must be pre-filled with the current expense description"
        )

    def test_get_form_prefilled_with_category(self, client, seeded_expense):
        """GET /expenses/<id>/edit must reflect the current category in the select."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        # The seeded expense has category="Food"
        assert "Food" in body, (
            "The edit form must show the current category (Food) in the select element"
        )

    def test_get_form_has_select_element(self, client, seeded_expense):
        """GET /expenses/<id>/edit must render a <select> element for category."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert "<select" in body, (
            "The edit form must include a <select> element for category"
        )

    @pytest.mark.parametrize("category", VALID_CATEGORIES)
    def test_get_form_contains_all_seven_categories(self, client, seeded_expense, category):
        """All 7 fixed category options must appear in the edit form's select element."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert category in body, (
            f"Category '{category}' must appear as an option in the edit form"
        )

    def test_get_form_has_amount_field(self, client, seeded_expense):
        """GET /expenses/<id>/edit must include an amount input field."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert 'name="amount"' in body, (
            "The edit form must have an amount input named 'amount'"
        )

    def test_get_form_has_date_field(self, client, seeded_expense):
        """GET /expenses/<id>/edit must include a date input field."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert 'name="date"' in body, (
            "The edit form must have a date input named 'date'"
        )

    def test_get_form_has_description_field(self, client, seeded_expense):
        """GET /expenses/<id>/edit must include a description field."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert 'name="description"' in body, (
            "The edit form must have a description field named 'description'"
        )

    def test_get_page_has_cancel_link_to_profile(self, client, seeded_expense):
        """GET /expenses/<id>/edit must include a cancel link back to /profile."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert "/profile" in body, (
            "The edit form must include a cancel link pointing to /profile"
        )

    def test_get_form_has_post_method(self, client, seeded_expense):
        """The edit form element must declare method POST."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode().lower()
        assert 'method="post"' in body or "method='post'" in body, (
            "The edit form must use method=POST"
        )


# ------------------------------------------------------------------ #
# Route tests — POST happy path                                       #
# ------------------------------------------------------------------ #

class TestPostEditExpenseHappyPath:
    def test_valid_post_redirects_to_profile(self, client, seeded_expense):
        """Valid POST /expenses/<id>/edit must redirect to /profile with status 302."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "75.50",
            "category": "Transport",
            "date": "2026-05-01",
            "description": "Updated trip",
        })
        assert resp.status_code == 302, (
            "A valid POST to /expenses/<id>/edit must return 302"
        )
        assert "/profile" in resp.headers["Location"], (
            "A valid POST to /expenses/<id>/edit must redirect to /profile"
        )

    def test_valid_post_updates_db_row(self, client, seeded_expense):
        """After a valid POST, the DB row must reflect the new values."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        get_db = seeded_expense["get_db"]

        c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "75.50",
            "category": "Transport",
            "date": "2026-05-01",
            "description": "Updated trip",
        })

        con = get_db()
        row = con.execute(
            "SELECT amount, category, date, description FROM expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()
        con.close()

        assert row is not None, "The expense row must still exist after a valid POST"
        assert abs(row["amount"] - 75.50) < 0.001, "amount must be updated to 75.50"
        assert row["category"] == "Transport", "category must be updated to 'Transport'"
        assert row["date"] == "2026-05-01", "date must be updated to '2026-05-01'"
        assert row["description"] == "Updated trip", (
            "description must be updated to 'Updated trip'"
        )

    def test_valid_post_flashes_expense_updated_message(self, client, seeded_expense):
        """After a valid POST, the flash message 'Expense updated!' must appear on the next page."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]

        c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "75.50",
            "category": "Transport",
            "date": "2026-05-01",
            "description": "Updated trip",
        })

        # Follow the redirect to /profile to observe the flash message
        resp = c.get("/profile")
        body = resp.data.decode()
        assert "Expense updated!" in body, (
            "The flash message 'Expense updated!' must appear after a valid POST"
        )

    def test_valid_post_does_not_alter_other_users_expense(self, client, seeded_expense):
        """A valid POST by user A must not modify user B's expense row."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        other_expense_id = seeded_expense["other_expense_id"]
        get_db = seeded_expense["get_db"]

        # Capture other user's expense values before the update
        con = get_db()
        before = con.execute(
            "SELECT amount, category FROM expenses WHERE id = ?",
            (other_expense_id,),
        ).fetchone()
        con.close()

        c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "1.00",
            "category": "Other",
            "date": "2026-05-01",
            "description": "",
        })

        con = get_db()
        after = con.execute(
            "SELECT amount, category FROM expenses WHERE id = ?",
            (other_expense_id,),
        ).fetchone()
        con.close()

        assert abs(after["amount"] - before["amount"]) < 0.001, (
            "Another user's expense amount must not be modified by a different user's POST"
        )
        assert after["category"] == before["category"], (
            "Another user's expense category must not be modified by a different user's POST"
        )


# ------------------------------------------------------------------ #
# Route tests — POST validation errors                                #
# ------------------------------------------------------------------ #

class TestPostEditExpenseValidationErrors:
    def test_missing_amount_returns_200(self, client, seeded_expense):
        """POST with missing amount must re-render the form with status 200."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "",
            "category": "Food",
            "date": "2026-05-01",
            "description": "Some note",
        })
        assert resp.status_code == 200, (
            "Missing amount should re-render the form with status 200"
        )

    def test_missing_amount_shows_error_message(self, client, seeded_expense):
        """POST with missing amount must show a visible error message."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "",
            "category": "Food",
            "date": "2026-05-01",
            "description": "Some note",
        })
        body = resp.data.decode()
        assert "error" in body.lower() or "required" in body.lower() or "amount" in body.lower(), (
            "Missing amount must produce a visible error message in the form"
        )

    def test_zero_amount_returns_200(self, client, seeded_expense):
        """POST with amount=0 must re-render the form with status 200."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-05-01",
            "description": "Some note",
        })
        assert resp.status_code == 200, (
            "amount=0 should re-render the form with status 200"
        )

    def test_zero_amount_shows_error_message(self, client, seeded_expense):
        """POST with amount=0 must show a visible error message."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-05-01",
            "description": "Some note",
        })
        body = resp.data.decode()
        assert "error" in body.lower() or "greater" in body.lower() or "zero" in body.lower(), (
            "amount=0 must produce an error message about a non-positive value"
        )

    def test_negative_amount_returns_200(self, client, seeded_expense):
        """POST with a negative amount must re-render the form with status 200."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "-5.00",
            "category": "Food",
            "date": "2026-05-01",
            "description": "Refund attempt",
        })
        assert resp.status_code == 200, (
            "Negative amount should re-render the form with status 200"
        )

    def test_negative_amount_shows_error_message(self, client, seeded_expense):
        """POST with a negative amount must show a visible error message."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "-5.00",
            "category": "Food",
            "date": "2026-05-01",
            "description": "Refund attempt",
        })
        body = resp.data.decode()
        assert "error" in body.lower() or "greater" in body.lower() or "zero" in body.lower(), (
            "Negative amount must produce an error message about a non-positive value"
        )

    def test_non_numeric_amount_returns_200(self, client, seeded_expense):
        """POST with a non-numeric amount must re-render the form with status 200."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "not-a-number",
            "category": "Food",
            "date": "2026-05-01",
            "description": "Some note",
        })
        assert resp.status_code == 200, (
            "Non-numeric amount should re-render the form with status 200"
        )

    def test_non_numeric_amount_shows_error_message(self, client, seeded_expense):
        """POST with a non-numeric amount must show a visible error message."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "not-a-number",
            "category": "Food",
            "date": "2026-05-01",
            "description": "Some note",
        })
        body = resp.data.decode()
        assert "error" in body.lower() or "valid" in body.lower() or "number" in body.lower(), (
            "Non-numeric amount must produce an error message"
        )

    def test_missing_category_returns_200(self, client, seeded_expense):
        """POST with missing category must re-render the form with status 200."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "50.00",
            "category": "",
            "date": "2026-05-01",
            "description": "Some note",
        })
        assert resp.status_code == 200, (
            "Missing category should re-render the form with status 200"
        )

    def test_missing_category_shows_error_message(self, client, seeded_expense):
        """POST with missing category must show a visible error message."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "50.00",
            "category": "",
            "date": "2026-05-01",
            "description": "Some note",
        })
        body = resp.data.decode()
        assert "error" in body.lower() or "required" in body.lower() or "category" in body.lower(), (
            "Missing category must produce a visible error message"
        )

    def test_invalid_category_returns_200(self, client, seeded_expense):
        """POST with a category not in the fixed list must re-render the form with status 200."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "50.00",
            "category": "InvalidCategory",
            "date": "2026-05-01",
            "description": "Some note",
        })
        assert resp.status_code == 200, (
            "Invalid category should re-render the form with status 200"
        )

    def test_invalid_category_shows_error_message(self, client, seeded_expense):
        """POST with an invalid category must show a visible error message."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "50.00",
            "category": "InvalidCategory",
            "date": "2026-05-01",
            "description": "Some note",
        })
        body = resp.data.decode()
        assert "error" in body.lower() or "invalid" in body.lower() or "category" in body.lower(), (
            "Invalid category must produce a visible error message"
        )

    def test_missing_date_returns_200(self, client, seeded_expense):
        """POST with missing date must re-render the form with status 200."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "50.00",
            "category": "Food",
            "date": "",
            "description": "Some note",
        })
        assert resp.status_code == 200, (
            "Missing date should re-render the form with status 200"
        )

    def test_missing_date_shows_error_message(self, client, seeded_expense):
        """POST with missing date must show a visible error message."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "50.00",
            "category": "Food",
            "date": "",
            "description": "Some note",
        })
        body = resp.data.decode()
        assert "error" in body.lower() or "required" in body.lower() or "date" in body.lower(), (
            "Missing date must produce a visible error message"
        )

    @pytest.mark.parametrize("bad_date", [
        "not-a-date",
        "20260501",
        "05-01-2026",
        "2026/05/01",
        "2026-13-01",
        "2026-00-15",
        "abcd-ef-gh",
    ])
    def test_invalid_date_format_returns_200(self, client, seeded_expense, bad_date):
        """POST with a non-YYYY-MM-DD date must re-render the form with status 200."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "50.00",
            "category": "Food",
            "date": bad_date,
            "description": "Some note",
        })
        assert resp.status_code == 200, (
            f"Invalid date '{bad_date}' should re-render the form with status 200"
        )

    @pytest.mark.parametrize("bad_date", [
        "not-a-date",
        "20260501",
        "05-01-2026",
        "2026/05/01",
        "2026-13-01",
        "2026-00-15",
        "abcd-ef-gh",
    ])
    def test_invalid_date_format_shows_error_message(self, client, seeded_expense, bad_date):
        """POST with a non-YYYY-MM-DD date must show a visible error message."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "50.00",
            "category": "Food",
            "date": bad_date,
            "description": "Some note",
        })
        body = resp.data.decode()
        assert "error" in body.lower() or "date" in body.lower() or "format" in body.lower(), (
            f"Invalid date '{bad_date}' must produce a visible error message"
        )


# ------------------------------------------------------------------ #
# Route tests — POST edge cases                                       #
# ------------------------------------------------------------------ #

class TestPostEditExpenseEdgeCases:
    def test_blank_description_redirects_to_profile(self, client, seeded_expense):
        """POST with blank description (optional) must redirect to /profile — no error."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "50.00",
            "category": "Food",
            "date": "2026-05-01",
            "description": "",
        })
        assert resp.status_code == 302, (
            "Blank description is optional; POST should redirect (302)"
        )
        assert "/profile" in resp.headers["Location"], (
            "POST with blank description should redirect to /profile"
        )

    def test_blank_description_stores_null_in_db(self, client, seeded_expense):
        """POST with blank description must store NULL (not empty string) in the DB."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        get_db = seeded_expense["get_db"]

        c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "50.00",
            "category": "Food",
            "date": "2026-05-01",
            "description": "",
        })

        con = get_db()
        row = con.execute(
            "SELECT description FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        con.close()

        assert row is not None, "The expense row must exist after update"
        assert row["description"] is None, (
            "A blank description submitted in the edit form must be stored as NULL"
        )

    def test_whitespace_only_description_stores_null_in_db(self, client, seeded_expense):
        """POST with a whitespace-only description must store NULL in the DB."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        get_db = seeded_expense["get_db"]

        c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "50.00",
            "category": "Food",
            "date": "2026-05-01",
            "description": "   ",
        })

        con = get_db()
        row = con.execute(
            "SELECT description FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        con.close()

        assert row is not None, "The expense row must exist after update"
        assert row["description"] is None, (
            "A whitespace-only description must be stripped and stored as NULL"
        )

    def test_error_retains_submitted_amount_in_form(self, client, seeded_expense):
        """On validation error the form must echo the last-submitted amount value."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "123.45",
            "category": "InvalidCategory",
            "date": "2026-05-01",
            "description": "My note",
        })
        body = resp.data.decode()
        assert "123.45" in body, (
            "The last-submitted amount must be echoed back when the form re-renders on error"
        )

    def test_error_retains_submitted_description_in_form(self, client, seeded_expense):
        """On validation error the form must echo the last-submitted description value."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-05-01",
            "description": "Special retained note",
        })
        body = resp.data.decode()
        assert "Special retained note" in body, (
            "The last-submitted description must be echoed back when the form re-renders on error"
        )

    def test_error_retains_submitted_date_in_form(self, client, seeded_expense):
        """On validation error the form must echo the last-submitted date value."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        resp = c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-06-15",
            "description": "",
        })
        body = resp.data.decode()
        assert "2026-06-15" in body, (
            "The last-submitted date must be echoed back when the form re-renders on error"
        )

    def test_error_does_not_update_db_row(self, client, seeded_expense):
        """On a validation error the DB row must remain unchanged."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        get_db = seeded_expense["get_db"]

        # Attempt an invalid POST (amount=0)
        c.post(f"/expenses/{expense_id}/edit", data={
            "amount": "0",
            "category": "Transport",
            "date": "2026-06-01",
            "description": "Should not persist",
        })

        con = get_db()
        row = con.execute(
            "SELECT amount, category, date FROM expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()
        con.close()

        # Original values must be intact
        assert abs(row["amount"] - 42.00) < 0.001, (
            "A failed validation must not alter the amount in the DB"
        )
        assert row["category"] == "Food", (
            "A failed validation must not alter the category in the DB"
        )
        assert row["date"] == "2026-04-10", (
            "A failed validation must not alter the date in the DB"
        )
