import os
import sqlite3
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from werkzeug.security import check_password_hash
from database.db import get_db, init_db, seed_db, create_user, get_user_by_email
from database.queries import (
    get_user_by_id,
    get_recent_transactions,
    get_summary_stats,
    get_category_breakdown,
)

app = Flask(__name__)
app.secret_key = "spendly-dev-secret"


# ------------------------------------------------------------------ #
# Presentation helpers                                                #
# ------------------------------------------------------------------ #

def initials_from_name(name):
    return "".join(w[0].upper() for w in name.split() if w)


def format_member_since(created_at):
    """'2026-05-01 12:34:56' → 'May 2026'"""
    try:
        dt = datetime.strptime(created_at[:10], "%Y-%m-%d")
        return dt.strftime("%B %Y")
    except (ValueError, TypeError):
        return created_at


def format_display_date(iso_date):
    """'2026-04-03' → '03 Apr 2026'"""
    try:
        dt = datetime.strptime(iso_date, "%Y-%m-%d")
        return dt.strftime("%d %b %Y")
    except (ValueError, TypeError):
        return iso_date


def _first_of_month_n_ago(n, from_date):
    m, y = from_date.month - n, from_date.year
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    if session.get("user_id"):
        return redirect(url_for("profile"))
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("profile"))

    if request.method == "GET":
        return render_template("register.html")

    name             = request.form.get("name", "").strip()
    email            = request.form.get("email", "").strip()
    password         = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not name:
        return render_template("register.html", error="Name is required.")
    if not email:
        return render_template("register.html", error="Email is required.")
    if not password:
        return render_template("register.html", error="Password is required.")
    if password != confirm_password:
        return render_template("register.html", error="Passwords do not match.")

    try:
        create_user(name, email, password)
    except sqlite3.IntegrityError:
        return render_template("register.html", error="Email already registered.")

    flash("Account created! Please sign in.")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("profile"))

    if request.method == "GET":
        return render_template("login.html")

    if request.method == "POST":
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Invalid email or password.")
            return render_template("login.html")

        user = get_user_by_email(email)
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.")
            return render_template("login.html")

        session.clear()
        session["user_id"]   = user["id"]
        session["user_name"] = user["name"]
        return redirect(url_for("profile"))

    abort(405)


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    uid = session["user_id"]
    row = get_user_by_id(uid)
    if row is None:
        session.clear()
        return redirect(url_for("login"))

    user = {
        "name":         row["name"],
        "email":        row["email"],
        "member_since": format_member_since(row["member_since"]),
        "initials":     initials_from_name(row["name"]),
    }

    # Parse and validate date filter params
    raw_from = request.args.get("date_from", "").strip()
    raw_to   = request.args.get("date_to",   "").strip()

    date_from_obj = date_to_obj = None
    if raw_from:
        try:
            date_from_obj = datetime.strptime(raw_from, "%Y-%m-%d").date()
        except ValueError:
            pass
    if raw_to:
        try:
            date_to_obj = datetime.strptime(raw_to, "%Y-%m-%d").date()
        except ValueError:
            pass

    if date_from_obj and date_to_obj and date_from_obj > date_to_obj:
        flash("Start date must be before end date.")
        date_from_obj = date_to_obj = None

    date_from = str(date_from_obj) if date_from_obj else None
    date_to   = str(date_to_obj)   if date_to_obj   else None

    # Compute preset date ranges
    today = date.today()
    presets = {
        "this_month":    {"label": "This Month",    "date_from": str(today.replace(day=1)),            "date_to": str(today)},
        "last_3_months": {"label": "Last 3 Months", "date_from": str(_first_of_month_n_ago(3, today)), "date_to": str(today)},
        "last_6_months": {"label": "Last 6 Months", "date_from": str(_first_of_month_n_ago(6, today)), "date_to": str(today)},
    }

    raw_stats   = get_summary_stats(uid, date_from=date_from, date_to=date_to)
    total_spent = raw_stats["total_spent"]

    if date_from_obj and date_to_obj:
        days        = (date_to_obj - date_from_obj).days + 1
        avg_per_day = round(total_spent / max(days, 1), 2)
        filter_label = f"{format_display_date(date_from)} – {format_display_date(date_to)}"
    else:
        avg_per_day  = round(total_spent / 30, 2)
        filter_label = "all time"

    stats = {
        "total_spent":       total_spent,
        "transaction_count": raw_stats["transaction_count"],
        "top_category":      raw_stats["top_category"],
        "avg_per_day":       avg_per_day,
    }

    transactions = [
        {**t, "date": format_display_date(t["date"])}
        for t in get_recent_transactions(uid, date_from=date_from, date_to=date_to)
    ]

    categories = get_category_breakdown(uid, date_from=date_from, date_to=date_to)

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
        date_from=date_from or "",
        date_to=date_to or "",
        presets=presets,
        filter_label=filter_label,
    )


@app.route("/analytics")
def analytics():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    return render_template("analytics.html")


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    with app.app_context():
        init_db()
        seed_db()
    app.run(debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true", port=5001)
