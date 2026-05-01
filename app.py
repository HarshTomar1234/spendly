import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from werkzeug.security import check_password_hash
from database.db import get_db, init_db, seed_db, create_user, get_user_by_email

app = Flask(__name__)
app.secret_key = "spendly-dev-secret"


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

    user = {
        "name":         "Demo User",
        "email":        "demo@spendly.com",
        "member_since": "April 2026",
        "initials":     "DU",
    }

    transactions = [
        {"date": "25 Apr 2026", "description": "Dinner with friends",    "category": "Food",          "amount": 2200},
        {"date": "20 Apr 2026", "description": "Notebook",               "category": "Other",         "amount":  800},
        {"date": "17 Apr 2026", "description": "Groceries",              "category": "Shopping",      "amount": 6520},
        {"date": "13 Apr 2026", "description": "Streaming subscription", "category": "Entertainment", "amount": 1875},
        {"date": "10 Apr 2026", "description": "Pharmacy",               "category": "Health",        "amount": 3000},
        {"date": "07 Apr 2026", "description": "Electricity bill",       "category": "Bills",         "amount": 12000},
        {"date": "05 Apr 2026", "description": "Monthly bus pass",       "category": "Transport",     "amount": 4500},
        {"date": "03 Apr 2026", "description": "Lunch at cafe",          "category": "Food",          "amount": 1250},
    ]

    total_spent = sum(t["amount"] for t in transactions)

    stats = {
        "total_spent":       total_spent,
        "transaction_count": len(transactions),
        "top_category":      "Bills",
        "avg_per_day":       round(total_spent / 30),
    }

    categories = [
        {"name": "Bills",         "amount": 12000, "pct": 37},
        {"name": "Shopping",      "amount":  6520, "pct": 20},
        {"name": "Transport",     "amount":  4500, "pct": 14},
        {"name": "Food",          "amount":  3450, "pct": 11},
        {"name": "Health",        "amount":  3000, "pct":  9},
        {"name": "Entertainment", "amount":  1875, "pct":  6},
        {"name": "Other",         "amount":   800, "pct":  3},
    ]

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
    )


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
    app.run(debug=True, port=5001)
