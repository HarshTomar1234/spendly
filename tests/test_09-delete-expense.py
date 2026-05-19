"""
Tests for Step 09 — Delete Expense feature.

Covers:
  - Unit tests for delete_expense(expense_id, user_id) in database/queries.py:
      * valid expense_id + correct user_id  → row removed from DB
      * valid expense_id + wrong user_id    → row remains (ownership guard)
      * non-existent expense_id             → no error raised, DB unchanged

  - Route POST /expenses/<id>/delete:
      * unauthenticated → 302 redirect to /login
      * authenticated, own expense → 302 redirect to /profile, row deleted from DB
      * authenticated, other user's expense → 404, row still in DB
      * authenticated, non-existent id → 404

  - Wrong-method guard:
      * GET /expenses/<id>/delete → 405 Method Not Allowed

  - Profile page integration:
      * deleted expense no longer appears in /profile transaction list
      * profile page contains a delete form/button for each transaction row

All tests use a temporary SQLite file (via tmp_path) that is monkeypatched
over get_db() so the real spendly.db is never touched.
Auth is simulated directly via session_transaction() — no login form needed.
"""

import sqlite3
import pytest
from werkzeug.security import generate_password_hash

import database.db as db_module
from database.queries import delete_expense
from app import app as flask_app


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #

@pytest.fixture()
def tmp_db(monkeypatch, tmp_path):
    """
    Fresh temporary SQLite database with the full Spendly schema.

    Monkeypatches get_db() in both db_module and queries module so
    the real spendly.db is never touched.

    Seeds:
      - One primary test user  (user_id)
      - One secondary test user (other_user_id)

    Returns a dict with:
      user_id, other_user_id, get_db (factory function)
    """
    db_path = str(tmp_path / "test_delete_expense.db")

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

    # Primary user
    con.execute(
        "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
        ("Delete Test User", "deletetest@example.com", pw, "2026-01-01 10:00:00"),
    )
    con.commit()
    user_id = con.execute(
        "SELECT id FROM users WHERE email = ?", ("deletetest@example.com",)
    ).fetchone()["id"]

    # Secondary user (for ownership tests)
    con.execute(
        "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
        ("Other User", "other@example.com", pw, "2026-01-02 10:00:00"),
    )
    con.commit()
    other_user_id = con.execute(
        "SELECT id FROM users WHERE email = ?", ("other@example.com",)
    ).fetchone()["id"]

    con.close()

    return {
        "user_id": user_id,
        "other_user_id": other_user_id,
        "get_db": _get_db,
    }


@pytest.fixture()
def client(tmp_db):
    """
    Flask test client pre-configured for testing against the patched DB.
    Yields a 4-tuple: (client, user_id, other_user_id, get_db).
    """
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test-secret-09"
    with flask_app.test_client() as c:
        yield c, tmp_db["user_id"], tmp_db["other_user_id"], tmp_db["get_db"]


@pytest.fixture()
def seeded_expense(tmp_db):
    """
    Inserts one expense row for the primary user and one for the secondary user.

    Returns a dict with:
      expense_id       – belongs to user_id
      other_expense_id – belongs to other_user_id
      user_id
      other_user_id
      get_db
    """
    get_db = tmp_db["get_db"]
    user_id = tmp_db["user_id"]
    other_user_id = tmp_db["other_user_id"]

    con = get_db()
    con.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        (user_id, 55.00, "Food", "2026-04-15", "Lunch at office"),
    )
    con.commit()
    expense_id = con.execute(
        "SELECT id FROM expenses WHERE user_id = ? AND date = ?",
        (user_id, "2026-04-15"),
    ).fetchone()["id"]

    con.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        (other_user_id, 120.00, "Bills", "2026-04-20", "Electricity bill"),
    )
    con.commit()
    other_expense_id = con.execute(
        "SELECT id FROM expenses WHERE user_id = ? AND date = ?",
        (other_user_id, "2026-04-20"),
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

def _inject_session(c, user_id, name="Delete Test User"):
    """Set session variables directly without going through the login route."""
    with c.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = name


def _row_exists(get_db, expense_id):
    """Return True if an expense row with the given id is present in the DB."""
    con = get_db()
    row = con.execute(
        "SELECT id FROM expenses WHERE id = ?", (expense_id,)
    ).fetchone()
    con.close()
    return row is not None


# ------------------------------------------------------------------ #
# Unit tests — delete_expense()                                       #
# ------------------------------------------------------------------ #

class TestDeleteExpenseUnit:
    def test_correct_owner_removes_row_from_db(self, seeded_expense):
        """delete_expense with valid expense_id and correct user_id must remove the row."""
        expense_id = seeded_expense["expense_id"]
        user_id = seeded_expense["user_id"]
        get_db = seeded_expense["get_db"]

        # Confirm the row exists before deletion
        assert _row_exists(get_db, expense_id), (
            "Pre-condition: expense row must exist before calling delete_expense"
        )

        delete_expense(expense_id, user_id)

        assert not _row_exists(get_db, expense_id), (
            "delete_expense with the correct user_id must remove the row from the DB"
        )

    def test_wrong_user_id_leaves_row_intact(self, seeded_expense):
        """delete_expense with valid expense_id but wrong user_id must not remove the row."""
        expense_id = seeded_expense["expense_id"]
        other_user_id = seeded_expense["other_user_id"]
        get_db = seeded_expense["get_db"]

        # No error should be raised
        delete_expense(expense_id, other_user_id)

        assert _row_exists(get_db, expense_id), (
            "delete_expense with the wrong user_id must leave the expense row intact"
        )

    def test_wrong_user_id_does_not_raise(self, seeded_expense):
        """delete_expense with a wrong user_id must complete without raising any exception."""
        expense_id = seeded_expense["expense_id"]
        other_user_id = seeded_expense["other_user_id"]

        # Should not raise
        try:
            delete_expense(expense_id, other_user_id)
        except Exception as exc:
            pytest.fail(
                f"delete_expense raised an unexpected exception with wrong user_id: {exc}"
            )

    def test_nonexistent_expense_id_does_not_raise(self, seeded_expense):
        """delete_expense with a non-existent expense_id must complete without raising."""
        user_id = seeded_expense["user_id"]
        nonexistent_id = 999999

        try:
            delete_expense(nonexistent_id, user_id)
        except Exception as exc:
            pytest.fail(
                f"delete_expense raised an unexpected exception for a non-existent id: {exc}"
            )

    def test_nonexistent_expense_id_leaves_db_unchanged(self, seeded_expense):
        """delete_expense with a non-existent expense_id must leave existing rows untouched."""
        user_id = seeded_expense["user_id"]
        expense_id = seeded_expense["expense_id"]
        get_db = seeded_expense["get_db"]
        nonexistent_id = 999999

        delete_expense(nonexistent_id, user_id)

        assert _row_exists(get_db, expense_id), (
            "delete_expense with a non-existent id must not affect other rows in the DB"
        )

    def test_delete_does_not_remove_other_users_expense(self, seeded_expense):
        """Deleting the primary user's expense must leave the secondary user's expense intact."""
        expense_id = seeded_expense["expense_id"]
        user_id = seeded_expense["user_id"]
        other_expense_id = seeded_expense["other_expense_id"]
        get_db = seeded_expense["get_db"]

        delete_expense(expense_id, user_id)

        assert _row_exists(get_db, other_expense_id), (
            "Deleting one user's expense must not remove another user's expense row"
        )


# ------------------------------------------------------------------ #
# Route tests — Auth guard                                            #
# ------------------------------------------------------------------ #

class TestDeleteExpenseAuthGuard:
    def test_unauthenticated_post_redirects_to_login(self, client, seeded_expense):
        """Unauthenticated POST /expenses/<id>/delete must return 302 to /login."""
        c, _, _, _ = client
        expense_id = seeded_expense["expense_id"]

        resp = c.post(f"/expenses/{expense_id}/delete")

        assert resp.status_code == 302, (
            "Unauthenticated POST /expenses/<id>/delete must return 302"
        )
        assert "/login" in resp.headers["Location"], (
            "Unauthenticated POST must redirect to /login"
        )

    def test_unauthenticated_post_does_not_delete_row(self, client, seeded_expense):
        """Unauthenticated POST must not remove the expense row from the DB."""
        c, _, _, _ = client
        expense_id = seeded_expense["expense_id"]
        get_db = seeded_expense["get_db"]

        c.post(f"/expenses/{expense_id}/delete")

        assert _row_exists(get_db, expense_id), (
            "Unauthenticated POST must not delete the expense row from the DB"
        )


# ------------------------------------------------------------------ #
# Route tests — Happy path (own expense)                              #
# ------------------------------------------------------------------ #

class TestDeleteExpenseHappyPath:
    def test_authenticated_post_own_expense_returns_302(self, client, seeded_expense):
        """Authenticated POST for own expense must return 302."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]

        resp = c.post(f"/expenses/{expense_id}/delete")

        assert resp.status_code == 302, (
            "Authenticated POST for own expense must return 302 (redirect)"
        )

    def test_authenticated_post_own_expense_redirects_to_profile(self, client, seeded_expense):
        """Authenticated POST for own expense must redirect to /profile."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]

        resp = c.post(f"/expenses/{expense_id}/delete")

        assert "/profile" in resp.headers["Location"], (
            "Authenticated POST for own expense must redirect to /profile"
        )

    def test_authenticated_post_own_expense_removes_row_from_db(self, client, seeded_expense):
        """After authenticated POST for own expense, the row must no longer exist in the DB."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        get_db = seeded_expense["get_db"]

        c.post(f"/expenses/{expense_id}/delete")

        assert not _row_exists(get_db, expense_id), (
            "The expense row must be removed from the DB after a successful delete"
        )

    def test_authenticated_post_does_not_remove_other_users_row(self, client, seeded_expense):
        """Deleting own expense via the route must not remove another user's expense row."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]
        other_expense_id = seeded_expense["other_expense_id"]
        get_db = seeded_expense["get_db"]

        c.post(f"/expenses/{expense_id}/delete")

        assert _row_exists(get_db, other_expense_id), (
            "Deleting own expense must not remove another user's expense from the DB"
        )


# ------------------------------------------------------------------ #
# Route tests — Ownership guard (other user's expense)               #
# ------------------------------------------------------------------ #

class TestDeleteExpenseOwnershipGuard:
    def test_post_other_users_expense_returns_404(self, client, seeded_expense):
        """Authenticated POST targeting another user's expense must return 404."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        other_expense_id = seeded_expense["other_expense_id"]

        resp = c.post(f"/expenses/{other_expense_id}/delete")

        assert resp.status_code == 404, (
            "POST for another user's expense must return 404 (ownership guard)"
        )

    def test_post_other_users_expense_leaves_row_in_db(self, client, seeded_expense):
        """After a 404 ownership rejection, the other user's expense row must still exist."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        other_expense_id = seeded_expense["other_expense_id"]
        get_db = seeded_expense["get_db"]

        c.post(f"/expenses/{other_expense_id}/delete")

        assert _row_exists(get_db, other_expense_id), (
            "The other user's expense row must remain in the DB after a 404 ownership rejection"
        )


# ------------------------------------------------------------------ #
# Route tests — Non-existent expense                                  #
# ------------------------------------------------------------------ #

class TestDeleteExpenseNonExistent:
    def test_post_nonexistent_id_returns_404(self, client, seeded_expense):
        """Authenticated POST for a non-existent expense id must return 404."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        nonexistent_id = 999999

        resp = c.post(f"/expenses/{nonexistent_id}/delete")

        assert resp.status_code == 404, (
            "POST for a non-existent expense id must return 404"
        )


# ------------------------------------------------------------------ #
# Route tests — Wrong method guard                                    #
# ------------------------------------------------------------------ #

class TestDeleteExpenseWrongMethod:
    def test_get_returns_405(self, client, seeded_expense):
        """GET /expenses/<id>/delete must return 405 Method Not Allowed."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]

        resp = c.get(f"/expenses/{expense_id}/delete")

        assert resp.status_code == 405, (
            "GET /expenses/<id>/delete must return 405 Method Not Allowed"
        )

    def test_get_unauthenticated_returns_405(self, client, seeded_expense):
        """GET /expenses/<id>/delete must return 405 even when unauthenticated."""
        c, _, _, _ = client
        expense_id = seeded_expense["expense_id"]

        resp = c.get(f"/expenses/{expense_id}/delete")

        assert resp.status_code == 405, (
            "GET /expenses/<id>/delete must return 405 regardless of auth state"
        )


# ------------------------------------------------------------------ #
# Profile page integration tests                                      #
# ------------------------------------------------------------------ #

class TestDeleteExpenseProfileIntegration:
    def test_deleted_expense_absent_from_profile_transactions(self, client, seeded_expense):
        """After deletion, the expense's description must not appear in /profile transactions."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]

        # Delete the expense
        c.post(f"/expenses/{expense_id}/delete")

        # Re-inject session (redirect clears nothing, but let's be explicit)
        _inject_session(c, user_id)
        resp = c.get("/profile")
        body = resp.data.decode()

        # The seeded description is "Lunch at office"
        assert "Lunch at office" not in body, (
            "The deleted expense description must not appear in the /profile transaction list"
        )

    def test_profile_contains_delete_form_for_existing_expense(self, client, seeded_expense):
        """The /profile page must contain a delete form (POST action) for the expense row."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]

        resp = c.get("/profile")
        body = resp.data.decode()

        assert f"/expenses/{expense_id}/delete" in body, (
            "The /profile page must include a form action pointing to the delete route "
            "for each transaction row"
        )

    def test_profile_contains_delete_button(self, client, seeded_expense):
        """The /profile page must contain a Delete button (or link) for the transaction row."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)

        resp = c.get("/profile")
        body = resp.data.decode()

        assert "Delete" in body, (
            "The /profile page must include a 'Delete' button for transaction rows"
        )

    def test_profile_returns_200_after_delete(self, client, seeded_expense):
        """After deleting an expense, /profile must still load with status 200."""
        c, user_id, _, _ = client
        _inject_session(c, user_id)
        expense_id = seeded_expense["expense_id"]

        c.post(f"/expenses/{expense_id}/delete")
        _inject_session(c, user_id)
        resp = c.get("/profile")

        assert resp.status_code == 200, (
            "/profile must return 200 after an expense has been deleted"
        )
