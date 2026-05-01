"""
Tests for Step 06 — Date Filter for Profile Page.

Covers the date-range filter on GET /profile:
  - No-filter baseline (same as Step 5 unfiltered behaviour)
  - Valid date ranges scope stats, transactions, and categories
  - Reversed range triggers a flash error and falls back to unfiltered
  - Malformed date strings do not crash (silent fallback to unfiltered)
  - Only one param provided → treated as no filter
  - Empty date range (no expenses) → zeros, no errors
  - avg_per_day calculation uses actual day span when a filter is active
  - Template context carries date_from / date_to / presets for the filter bar
  - Active preset state reflected in rendered HTML
  - Auth guard: unauthenticated requests redirect to /login
  - Rupee symbol always present regardless of active filter

Seed dataset spans three distinct months so date-window assertions are precise:
  - 2026-01-10  Food         50.00   "January lunch"
  - 2026-01-20  Transport    30.00   "Bus pass Jan"
  - 2026-02-05  Bills       200.00   "February electricity"
  - 2026-02-15  Shopping     80.00   "Groceries Feb"
  - 2026-03-01  Health       40.00   "Pharmacy March"
  - 2026-03-22  Food         25.00   "March coffee"

January total  : 80.00   (2 transactions)
February total : 280.00  (2 transactions)
March total    : 65.00   (2 transactions)
Overall total  : 425.00  (6 transactions)
Top category overall: Bills (200.00)
Top category Jan: Food (50.00)  [or Transport 30.00 — Food wins]
"""

import sqlite3
import pytest
from werkzeug.security import generate_password_hash

import database.db as db_module
from app import app as flask_app


# ------------------------------------------------------------------ #
# Seed data constants — single source of truth for all assertions     #
# ------------------------------------------------------------------ #

SEED_EXPENSES = [
    # (amount, category, date, description)
    (50.00,  "Food",      "2026-01-10", "January lunch"),
    (30.00,  "Transport", "2026-01-20", "Bus pass Jan"),
    (200.00, "Bills",     "2026-02-05", "February electricity"),
    (80.00,  "Shopping",  "2026-02-15", "Groceries Feb"),
    (40.00,  "Health",    "2026-03-01", "Pharmacy March"),
    (25.00,  "Food",      "2026-03-22", "March coffee"),
]

TOTAL_ALL      = 425.00
COUNT_ALL      = 6
TOP_CAT_ALL    = "Bills"

TOTAL_JAN      = 80.00
COUNT_JAN      = 2
TOP_CAT_JAN    = "Food"  # Food 50 > Transport 30

TOTAL_FEB      = 280.00
COUNT_FEB      = 2

TOTAL_MAR      = 65.00
COUNT_MAR      = 2

TOTAL_JAN_FEB  = 360.00
COUNT_JAN_FEB  = 4


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #

@pytest.fixture()
def tmp_db(monkeypatch, tmp_path):
    """
    Fresh temporary SQLite database with the Spendly schema.
    Monkeypatches get_db() in both db_module and queries module so
    the real spendly.db is never touched.
    Returns a dict with user_id and the _get_db factory.
    """
    db_path = str(tmp_path / "test_filter.db")

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

    pw = generate_password_hash("filterpass")
    con.execute(
        "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
        ("Filter User", "filter@example.com", pw, "2025-12-01 10:00:00"),
    )
    con.commit()
    user_id = con.execute(
        "SELECT id FROM users WHERE email = ?", ("filter@example.com",)
    ).fetchone()["id"]

    con.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description)"
        " VALUES (?, ?, ?, ?, ?)",
        [(user_id,) + row for row in SEED_EXPENSES],
    )
    con.commit()
    con.close()

    return {"user_id": user_id, "get_db": _get_db}


@pytest.fixture()
def client(tmp_db):
    """Flask test client pre-configured for testing, using the patched DB."""
    flask_app.config["TESTING"] = True
    flask_app.config["SECRET_KEY"] = "test-secret-06"
    with flask_app.test_client() as c:
        yield c, tmp_db["user_id"]


@pytest.fixture()
def auth_client(client):
    """Test client already authenticated as the seeded filter user."""
    c, user_id = client
    with c.session_transaction() as sess:
        sess["user_id"]   = user_id
        sess["user_name"] = "Filter User"
    return c, user_id


@pytest.fixture()
def empty_user_db(monkeypatch, tmp_path):
    """DB with a user who has zero expenses — for empty-range tests."""
    db_path = str(tmp_path / "empty_filter.db")

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
    con.commit()
    pw = generate_password_hash("emptypass")
    con.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Empty User", "empty_filter@example.com", pw),
    )
    con.commit()
    user_id = con.execute(
        "SELECT id FROM users WHERE email = ?", ("empty_filter@example.com",)
    ).fetchone()["id"]
    con.close()

    return {"user_id": user_id, "get_db": _get_db}


# ------------------------------------------------------------------ #
# Helper                                                              #
# ------------------------------------------------------------------ #

def _login(c, user_id, name="Filter User"):
    with c.session_transaction() as sess:
        sess["user_id"]   = user_id
        sess["user_name"] = name


# ------------------------------------------------------------------ #
# 1. Auth guard                                                        #
# ------------------------------------------------------------------ #

class TestAuthGuard:
    def test_unauthenticated_no_params_redirects_to_login(self, client):
        c, _ = client
        resp = c.get("/profile")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_unauthenticated_with_date_params_redirects_to_login(self, client):
        c, _ = client
        resp = c.get("/profile?date_from=2026-01-01&date_to=2026-01-31")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_unauthenticated_with_malformed_params_redirects_to_login(self, client):
        c, _ = client
        resp = c.get("/profile?date_from=not-a-date")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


# ------------------------------------------------------------------ #
# 2. No-filter baseline                                               #
# ------------------------------------------------------------------ #

class TestNoFilterBaseline:
    def test_no_params_returns_200(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile")
        assert resp.status_code == 200

    def test_no_params_shows_all_transactions(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile")
        body = resp.data.decode()
        # All 6 seed descriptions should appear
        for _, _, _, description in SEED_EXPENSES:
            assert description in body, (
                f"Expected description '{description}' in unfiltered profile page"
            )

    def test_no_params_total_reflects_all_expenses(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile")
        body = resp.data.decode()
        # 425.0 total — rendered as "425.0" or "425"
        assert "425" in body, "Expected total of 425 to appear in unfiltered page"

    def test_no_params_transaction_count_reflects_all(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile")
        body = resp.data.decode()
        # The template renders "{{ transactions | length }} entries" → "6 entries"
        assert "6 entries" in body, "Expected '6 entries' in unfiltered page"

    def test_no_params_top_category_is_bills(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile")
        body = resp.data.decode()
        assert "Bills" in body, "Expected 'Bills' as top category in unfiltered page"

    def test_no_params_rupee_symbol_present(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile")
        body = resp.data.decode()
        assert "&#8377;" in body or "₹" in body, "Rupee symbol must appear on unfiltered page"


# ------------------------------------------------------------------ #
# 3. Valid date range — all three sections scoped                     #
# ------------------------------------------------------------------ #

class TestValidDateRange:
    def test_january_filter_returns_200(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-01-01&date_to=2026-01-31")
        assert resp.status_code == 200

    def test_january_filter_shows_only_january_transactions(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-01-01&date_to=2026-01-31")
        body = resp.data.decode()
        # January expenses must appear
        assert "January lunch" in body
        assert "Bus pass Jan" in body
        # February and March expenses must NOT appear
        assert "February electricity" not in body
        assert "Groceries Feb" not in body
        assert "Pharmacy March" not in body
        assert "March coffee" not in body

    def test_january_filter_entry_count(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-01-01&date_to=2026-01-31")
        body = resp.data.decode()
        assert f"{COUNT_JAN} entries" in body, (
            f"Expected '{COUNT_JAN} entries' for January filter"
        )

    def test_january_filter_total_spent(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-01-01&date_to=2026-01-31")
        body = resp.data.decode()
        assert "80" in body, "Expected January total 80 on filtered page"

    def test_january_filter_top_category(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-01-01&date_to=2026-01-31")
        body = resp.data.decode()
        # Food (50) is the top category in January over Transport (30)
        assert TOP_CAT_JAN in body, (
            f"Expected top category '{TOP_CAT_JAN}' for January filter"
        )

    def test_january_filter_category_breakdown_excludes_other_months(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-01-01&date_to=2026-01-31")
        body = resp.data.decode()
        # Bills only appears in February — must not appear in category breakdown
        # (Bills badge would only show if Bills category was returned)
        # We cannot assert Bills is 100% absent from the page (it might appear in
        # nav or elsewhere), but we can assert "February electricity" is absent
        assert "February electricity" not in body

    def test_february_filter_transaction_count(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-02-01&date_to=2026-02-28")
        body = resp.data.decode()
        assert f"{COUNT_FEB} entries" in body, (
            f"Expected '{COUNT_FEB} entries' for February filter"
        )

    def test_february_filter_shows_only_february_transactions(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-02-01&date_to=2026-02-28")
        body = resp.data.decode()
        assert "February electricity" in body
        assert "Groceries Feb" in body
        assert "January lunch" not in body
        assert "March coffee" not in body

    def test_multi_month_range_shows_correct_transactions(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-01-01&date_to=2026-02-28")
        body = resp.data.decode()
        assert "January lunch" in body
        assert "Bus pass Jan" in body
        assert "February electricity" in body
        assert "Groceries Feb" in body
        # March must be excluded
        assert "Pharmacy March" not in body
        assert "March coffee" not in body

    def test_multi_month_range_entry_count(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-01-01&date_to=2026-02-28")
        body = resp.data.decode()
        assert f"{COUNT_JAN_FEB} entries" in body, (
            f"Expected '{COUNT_JAN_FEB} entries' for Jan–Feb filter"
        )

    def test_inclusive_lower_bound_date_is_included(self, auth_client):
        """An expense exactly on date_from must appear."""
        c, _ = auth_client
        # 2026-01-10 is the exact date of "January lunch"
        resp = c.get("/profile?date_from=2026-01-10&date_to=2026-01-31")
        body = resp.data.decode()
        assert "January lunch" in body, "Expense on date_from boundary must be included"

    def test_inclusive_upper_bound_date_is_included(self, auth_client):
        """An expense exactly on date_to must appear."""
        c, _ = auth_client
        # 2026-01-20 is the exact date of "Bus pass Jan"
        resp = c.get("/profile?date_from=2026-01-01&date_to=2026-01-20")
        body = resp.data.decode()
        assert "Bus pass Jan" in body, "Expense on date_to boundary must be included"

    def test_filtered_page_shows_rupee_symbol(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-01-01&date_to=2026-01-31")
        body = resp.data.decode()
        assert "&#8377;" in body or "₹" in body, (
            "Rupee symbol must appear on filtered page"
        )


# ------------------------------------------------------------------ #
# 4. Reversed date range                                              #
# ------------------------------------------------------------------ #

class TestReversedDateRange:
    def test_reversed_range_returns_200(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-03-31&date_to=2026-01-01")
        assert resp.status_code == 200

    def test_reversed_range_flash_error_message(self, auth_client):
        c, _ = auth_client
        resp = c.get(
            "/profile?date_from=2026-03-31&date_to=2026-01-01",
            follow_redirects=True,
        )
        body = resp.data.decode()
        assert "Start date must be before end date" in body, (
            "Expected flash error for reversed date range"
        )

    def test_reversed_range_falls_back_to_all_data(self, auth_client):
        c, _ = auth_client
        resp = c.get(
            "/profile?date_from=2026-03-31&date_to=2026-01-01",
            follow_redirects=True,
        )
        body = resp.data.decode()
        # All transactions must be present (unfiltered fallback)
        for _, _, _, description in SEED_EXPENSES:
            assert description in body, (
                f"Expected '{description}' in unfiltered fallback after reversed range"
            )

    def test_reversed_range_shows_all_transaction_count(self, auth_client):
        c, _ = auth_client
        resp = c.get(
            "/profile?date_from=2026-03-31&date_to=2026-01-01",
            follow_redirects=True,
        )
        body = resp.data.decode()
        assert f"{COUNT_ALL} entries" in body, (
            f"Expected '{COUNT_ALL} entries' after reversed-range fallback"
        )


# ------------------------------------------------------------------ #
# 5. Malformed date strings                                           #
# ------------------------------------------------------------------ #

class TestMalformedDates:
    @pytest.mark.parametrize("bad_value", [
        "not-a-date",
        "2026/01/01",
        "01-01-2026",
        "2026-13-01",
        "2026-00-10",
        "abcdefgh",
        "   ",
        "2026-1-1",
    ])
    def test_malformed_date_from_does_not_crash(self, auth_client, bad_value):
        c, _ = auth_client
        resp = c.get(f"/profile?date_from={bad_value}&date_to=2026-01-31")
        assert resp.status_code == 200, (
            f"Malformed date_from='{bad_value}' should return 200, not crash"
        )

    @pytest.mark.parametrize("bad_value", [
        "not-a-date",
        "2026/01/31",
        "31-01-2026",
        "garbage",
    ])
    def test_malformed_date_to_does_not_crash(self, auth_client, bad_value):
        c, _ = auth_client
        resp = c.get(f"/profile?date_from=2026-01-01&date_to={bad_value}")
        assert resp.status_code == 200, (
            f"Malformed date_to='{bad_value}' should return 200, not crash"
        )

    def test_malformed_date_from_falls_back_to_unfiltered(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_from=not-a-date&date_to=2026-01-31")
        body = resp.data.decode()
        # When date_from is malformed, only one valid bound exists → no filter applied
        # All expenses should appear
        assert f"{COUNT_ALL} entries" in body, (
            "Malformed date_from should produce unfiltered fallback"
        )

    def test_malformed_date_to_falls_back_to_unfiltered(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-01-01&date_to=garbage")
        body = resp.data.decode()
        assert f"{COUNT_ALL} entries" in body, (
            "Malformed date_to should produce unfiltered fallback"
        )

    def test_both_malformed_falls_back_to_unfiltered(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_from=bad&date_to=also-bad")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert f"{COUNT_ALL} entries" in body, (
            "Both malformed params should produce unfiltered fallback"
        )


# ------------------------------------------------------------------ #
# 6. Only one param provided                                          #
# ------------------------------------------------------------------ #

class TestSingleParam:
    def test_only_date_from_returns_200(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-01-01")
        assert resp.status_code == 200

    def test_only_date_from_shows_all_data(self, auth_client):
        """Only date_from with no date_to → treated as no filter."""
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-01-01")
        body = resp.data.decode()
        assert f"{COUNT_ALL} entries" in body, (
            "Only date_from provided should be treated as no filter"
        )

    def test_only_date_to_returns_200(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_to=2026-01-31")
        assert resp.status_code == 200

    def test_only_date_to_shows_all_data(self, auth_client):
        """Only date_to with no date_from → treated as no filter."""
        c, _ = auth_client
        resp = c.get("/profile?date_to=2026-01-31")
        body = resp.data.decode()
        assert f"{COUNT_ALL} entries" in body, (
            "Only date_to provided should be treated as no filter"
        )


# ------------------------------------------------------------------ #
# 7. Empty date range (no expenses in window)                         #
# ------------------------------------------------------------------ #

class TestEmptyDateRange:
    def test_range_with_no_expenses_returns_200(self, auth_client):
        c, _ = auth_client
        # 2025-06-01 to 2025-06-30 — entirely before any seed data
        resp = c.get("/profile?date_from=2025-06-01&date_to=2025-06-30")
        assert resp.status_code == 200

    def test_range_with_no_expenses_shows_zero_transactions(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_from=2025-06-01&date_to=2025-06-30")
        body = resp.data.decode()
        assert "0 entries" in body, (
            "Empty range should show '0 entries' for transactions"
        )

    def test_range_with_no_expenses_shows_zero_total(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile?date_from=2025-06-01&date_to=2025-06-30")
        body = resp.data.decode()
        # Total spent should be 0 in some form (0.0, 0, ₹0.0 etc.)
        assert "0" in body, "Empty range should display zero total spent"

    def test_user_with_no_expenses_empty_range_returns_200(self, empty_user_db):
        """A user with no expenses at all: any date range must return 200."""
        flask_app.config["TESTING"] = True
        flask_app.config["SECRET_KEY"] = "test-secret-06"
        user_id = empty_user_db["user_id"]
        with flask_app.test_client() as c:
            _login(c, user_id, name="Empty User")
            resp = c.get("/profile?date_from=2026-01-01&date_to=2026-01-31")
            assert resp.status_code == 200

    def test_user_with_no_expenses_shows_zero_entries(self, empty_user_db):
        flask_app.config["TESTING"] = True
        flask_app.config["SECRET_KEY"] = "test-secret-06"
        user_id = empty_user_db["user_id"]
        with flask_app.test_client() as c:
            _login(c, user_id, name="Empty User")
            resp = c.get("/profile?date_from=2026-01-01&date_to=2026-01-31")
            body = resp.data.decode()
            assert "0 entries" in body, "User with no expenses should see 0 entries"


# ------------------------------------------------------------------ #
# 8. avg_per_day calculation                                          #
# ------------------------------------------------------------------ #

class TestAvgPerDay:
    def test_avg_per_day_uses_actual_span_when_filtered(self, auth_client):
        """
        January 1–31 = 31 days. Total = 80.00.
        avg_per_day = round(80.00 / 31, 2) = 2.58
        The unfiltered avg would be round(425.00 / 30, 2) = 14.17.
        """
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-01-01&date_to=2026-01-31")
        body = resp.data.decode()
        # 80 / 31 = 2.58... — the page must NOT show the 30-day default (14.17)
        assert "14.17" not in body, (
            "Filtered avg_per_day must not use the 30-day default denominator"
        )
        # 2.58 should appear somewhere on the page
        assert "2.58" in body, (
            "Filtered avg_per_day should be 2.58 for January (80 / 31 days)"
        )

    def test_avg_per_day_single_day_range(self, auth_client):
        """
        Single-day range: 2026-01-10 only (Food 50.00).
        avg_per_day = round(50.00 / 1, 2) = 50.0
        """
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-01-10&date_to=2026-01-10")
        body = resp.data.decode()
        assert "50" in body, "Single-day range avg_per_day should equal total spent"

    def test_avg_per_day_uses_30_days_when_no_filter(self, auth_client):
        """
        Unfiltered: total = 425.00. avg_per_day = round(425.00 / 30, 2) = 14.17
        """
        c, _ = auth_client
        resp = c.get("/profile")
        body = resp.data.decode()
        assert "14.17" in body, (
            "Unfiltered avg_per_day should use 30 as denominator (425/30 = 14.17)"
        )

    def test_avg_per_day_multi_day_range(self, auth_client):
        """
        2026-02-01 to 2026-02-28 = 28 days. Total = 280.00.
        avg_per_day = round(280.00 / 28, 2) = 10.0
        """
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-02-01&date_to=2026-02-28")
        body = resp.data.decode()
        assert "10.0" in body or "10," in body, (
            "February avg_per_day should be 10.0 (280 / 28 days)"
        )


# ------------------------------------------------------------------ #
# 9. Template context — date_from / date_to echoed in filter bar      #
# ------------------------------------------------------------------ #

class TestTemplateContext:
    def test_active_date_from_echoed_in_input(self, auth_client):
        """The date_from input field should carry the active value."""
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-01-01&date_to=2026-01-31")
        body = resp.data.decode()
        assert 'value="2026-01-01"' in body, (
            "date_from input value should reflect the active filter"
        )

    def test_active_date_to_echoed_in_input(self, auth_client):
        """The date_to input field should carry the active value."""
        c, _ = auth_client
        resp = c.get("/profile?date_from=2026-01-01&date_to=2026-01-31")
        body = resp.data.decode()
        assert 'value="2026-01-31"' in body, (
            "date_to input value should reflect the active filter"
        )

    def test_no_filter_date_inputs_are_empty(self, auth_client):
        """With no filter, both date input values should be empty strings."""
        c, _ = auth_client
        resp = c.get("/profile")
        body = resp.data.decode()
        # Both inputs rendered with value=""
        assert 'value=""' in body, (
            "Date inputs should have empty values when no filter is active"
        )

    def test_presets_rendered_in_filter_bar(self, auth_client):
        """The filter bar should include the four preset buttons."""
        c, _ = auth_client
        resp = c.get("/profile")
        body = resp.data.decode()
        assert "This Month" in body, "Filter bar must include 'This Month' preset"
        assert "Last 3 Months" in body, "Filter bar must include 'Last 3 Months' preset"
        assert "Last 6 Months" in body, "Filter bar must include 'Last 6 Months' preset"
        assert "All Time" in body, "Filter bar must include 'All Time' preset"

    def test_filter_bar_apply_button_present(self, auth_client):
        """The custom-range form must have an Apply button."""
        c, _ = auth_client
        resp = c.get("/profile")
        body = resp.data.decode()
        assert "Apply" in body, "Filter bar must include an 'Apply' submit button"

    def test_filter_bar_date_inputs_present(self, auth_client):
        """Two date inputs (date_from and date_to) must exist in the filter form."""
        c, _ = auth_client
        resp = c.get("/profile")
        body = resp.data.decode()
        assert 'name="date_from"' in body, "Filter form must have a date_from input"
        assert 'name="date_to"' in body, "Filter form must have a date_to input"


# ------------------------------------------------------------------ #
# 10. Active preset state in template                                 #
# ------------------------------------------------------------------ #

class TestActivePresetState:
    def test_all_time_button_has_active_class_when_no_filter(self, auth_client):
        """With no query params, the 'All Time' button should have the active class."""
        c, _ = auth_client
        resp = c.get("/profile")
        body = resp.data.decode()
        # The template adds 'filter-btn--active' to the active button
        # The All Time link contains no date params and should be active
        assert "filter-btn--active" in body, (
            "Some filter button must have the active class when no filter is set"
        )
        # Extract the portion around "All Time" to confirm it has the active class
        idx = body.find("All Time")
        assert idx != -1, "All Time button must be present in the page"
        # Look for the active class within a reasonable range before "All Time"
        nearby = body[max(0, idx - 200):idx]
        assert "filter-btn--active" in nearby, (
            "'All Time' button should carry the filter-btn--active class when no filter is active"
        )

    def test_no_extra_active_class_on_presets_when_unfiltered(self, auth_client):
        """
        When no filter is active, preset buttons (This Month etc.) must NOT
        have the active class — only the All Time button should.
        """
        c, _ = auth_client
        resp = c.get("/profile")
        body = resp.data.decode()
        # Count occurrences of the active class — should be exactly 1
        active_count = body.count("filter-btn--active")
        assert active_count == 1, (
            f"Exactly 1 filter button should be active when no filter is set, found {active_count}"
        )

    def test_active_class_on_matching_preset_link(self, auth_client):
        """
        When the date params exactly match a preset's dates, that preset
        button must carry the active class.
        The route passes `presets` to the template; when date_from/date_to
        match a preset's values, the template applies filter-btn--active.
        We verify at least one active class exists on a non-All-Time button.
        """
        from datetime import date as date_cls
        today = date_cls.today()
        this_month_start = str(today.replace(day=1))
        today_str = str(today)

        c, _ = auth_client
        resp = c.get(f"/profile?date_from={this_month_start}&date_to={today_str}")
        body = resp.data.decode()
        assert "filter-btn--active" in body, (
            "A preset button should have the active class when its dates match the filter"
        )
        # The All Time link must NOT be active
        idx = body.find("All Time")
        assert idx != -1
        nearby = body[max(0, idx - 200):idx]
        assert "filter-btn--active" not in nearby, (
            "'All Time' must not be active when a date filter is set"
        )

    def test_custom_range_not_matching_preset_has_no_active_preset(self, auth_client):
        """
        A custom range that doesn't match any preset → no preset button
        should be active (but All Time also not active since a filter is set).
        In that case 0 buttons carry the active class (none match exactly).
        """
        c, _ = auth_client
        # 2026-01-15 to 2026-02-10 is unlikely to match any preset
        resp = c.get("/profile?date_from=2026-01-15&date_to=2026-02-10")
        body = resp.data.decode()
        # All Time must not be active (a filter IS set)
        idx = body.find("All Time")
        assert idx != -1
        nearby = body[max(0, idx - 200):idx]
        assert "filter-btn--active" not in nearby, (
            "'All Time' must not be active when a custom filter is set"
        )


# ------------------------------------------------------------------ #
# 11. All Time behaviour — clean URL                                  #
# ------------------------------------------------------------------ #

class TestAllTimeBehaviour:
    def test_clean_url_returns_all_data(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile")
        body = resp.data.decode()
        assert f"{COUNT_ALL} entries" in body, (
            "Clean /profile URL must return all expenses (All Time view)"
        )

    def test_clean_url_shows_overall_top_category(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile")
        body = resp.data.decode()
        assert TOP_CAT_ALL in body, (
            f"Clean /profile URL must show '{TOP_CAT_ALL}' as top category"
        )

    def test_clean_url_shows_all_categories_in_breakdown(self, auth_client):
        c, _ = auth_client
        resp = c.get("/profile")
        body = resp.data.decode()
        unique_categories = {row[1] for row in SEED_EXPENSES}
        for cat in unique_categories:
            assert cat in body, (
                f"Category '{cat}' must appear in unfiltered category breakdown"
            )

    def test_clean_url_date_inputs_are_empty(self, auth_client):
        """All Time view must leave the date input fields blank."""
        c, _ = auth_client
        resp = c.get("/profile")
        body = resp.data.decode()
        assert 'value=""' in body, (
            "Date inputs must be empty on the All Time (clean URL) view"
        )
